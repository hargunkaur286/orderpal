"""Scores retrieval against your hand-labelled questions.

    python3 -m evals.run_retrieval --list       # print every chunk label you can use
    python3 -m evals.run_retrieval              # score: recall@1, recall@5, MRR, plus every miss
    python3 -m evals.run_retrieval --k 3        # change k
    python3 -m evals.run_retrieval --mode vector   # one retrieval mode (default: rerank)
    python3 -m evals.run_retrieval --compare    # every mode side by side, plus results per question type
    python3 -m evals.run_retrieval --min-recall1 0.75   # CI gate: exit 1 if quality regresses

Labels are the chunk's first line, e.g. "Refund Policy > Time limits", not the chunk id:
ids change every time you re-ingest, but headings don't, so the eval set survives re-chunking.
"""
import argparse
import asyncio
import json
from pathlib import Path

from app.db import make_pool
from app.rag import retriever

EVAL_FILE = Path(__file__).parent / "retrieval.jsonl"


def label(chunk_content: str) -> str:
    return chunk_content.splitlines()[0]


def load_cases() -> list[dict]:
    cases = []
    for n, line in enumerate(EVAL_FILE.read_text().splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("//"):
            try:
                case = json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit(f"retrieval.jsonl line {n}, column {e.colno}: {e.msg}\n  {line}\n"
                                 f"  {' ' * (e.colno - 1)}^ here")
            case["line"] = n
            cases.append(case)
    return cases


async def all_labels(pool) -> list[str]:
    async with pool.connection() as conn:
        rows = await (await conn.execute("SELECT DISTINCT split_part(content, E'\\n', 1) AS l "
                                         "FROM chunks ORDER BY l")).fetchall()
    return [r["l"] for r in rows]


async def list_labels(pool) -> None:
    print("\n".join(await all_labels(pool)))


async def graded_cases(pool) -> tuple[list[dict], int]:
    cases = load_cases()
    graded = [c for c in cases if c["relevant"]]            # out-of-scope cases have no right chunk
    known = set(await all_labels(pool))
    for case in graded:
        if unknown := set(case["relevant"]) - known:
            raise SystemExit(f"line {case['line']}: no chunk is labelled {sorted(unknown)}. "
                             f"Check spelling with --list.")
    return graded, len(cases) - len(graded)


async def ranks(pool, graded: list[dict], k: int, mode: str) -> list[tuple[dict, int | None, list[str]]]:
    out = []
    for case in graded:
        ranked = [label(r["content"]) for r in await retriever.search(pool, case["q"], k=k, mode=mode)]
        # first position (1-based) where any relevant chunk appears
        rank = next((i for i, l in enumerate(ranked, 1) if l in set(case["relevant"])), None)
        out.append((case, rank, ranked))
    return out


def metrics(results, k: int) -> dict[str, float]:
    n = len(results)
    rs = [r for _, r, _ in results]
    return {"recall@1": sum(r == 1 for r in rs) / n,
            "recall@3": sum(r is not None and r <= 3 for r in rs) / n,
            f"recall@{k}": sum(r is not None for r in rs) / n,
            "MRR": sum(1 / r for r in rs if r) / n}


async def score(pool, k: int, mode: str) -> dict[str, float]:
    graded, skipped = await graded_cases(pool)
    results = await ranks(pool, graded, k, mode)
    m = metrics(results, k)
    print(f"{len(graded)} graded questions ({skipped} out-of-scope skipped), k={k}, mode={mode}\n")
    print(f"  recall@1  {m['recall@1']:6.1%}   right chunk ranked first")
    print(f"  recall@3  {m['recall@3']:6.1%}   right chunk in top 3")
    print(f"  recall@{k}  {m[f'recall@{k}']:6.1%}   right chunk anywhere in top {k}")
    print(f"  MRR       {m['MRR']:6.3f}   average of 1/rank (1.0 = always first)\n")
    for case, rank, ranked in results:
        if rank != 1:
            where = f"rank {rank}" if rank else f"NOT in top {k}"
            print(f"✗ [{case.get('type', '?')}] {case['q']!r}: {where}")
            print(f"     wanted: {case['relevant']}")
            print(f"     got:    {ranked[:3]}")
    return m


async def compare(pool, k: int) -> None:
    graded, _ = await graded_cases(pool)
    modes = ["vector", "keyword", "hybrid", "rerank"]
    per_mode = {m: await ranks(pool, graded, k, m) for m in modes}
    print(f"{len(graded)} graded questions, k={k}\n")
    print(f"  {'mode':9}" + "".join(f"{name:>10}" for name in metrics(per_mode['vector'], k)))
    for m in modes:
        vals = metrics(per_mode[m], k)
        print(f"  {m:9}" + "".join(f"{v:>10.3f}" if name == "MRR" else f"{v:>10.1%}" for name, v in vals.items()))
    print("\n  recall@1 by question type")
    types = sorted({c.get("type", "?") for c in graded})
    print(f"  {'type':11}{'n':>3}" + "".join(f"{m:>9}" for m in modes))
    for t in types:
        row = [sum(r == 1 for c, r, _ in per_mode[m] if c.get("type") == t) for m in modes]
        n = sum(c.get("type") == t for c in graded)
        print(f"  {t:11}{n:>3}" + "".join(f"{x / n:>9.0%}" for x in row))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--mode", default="rerank", choices=["vector", "keyword", "hybrid", "rerank"])
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--min-recall1", type=float, help="fail (exit 1) if recall@1 is below this")
    args = ap.parse_args()
    pool = make_pool()
    await pool.open(wait=True)
    try:
        if args.list:
            await list_labels(pool)
        elif args.compare:
            await compare(pool, args.k)
        else:
            m = await score(pool, args.k, args.mode)
            if args.min_recall1 is not None and m["recall@1"] < args.min_recall1:
                raise SystemExit(f"FAIL: recall@1 {m['recall@1']:.1%} is below the gate {args.min_recall1:.0%}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
