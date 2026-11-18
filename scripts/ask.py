"""Ask OrderPal a question from the terminal and see the answer, its sources and the timings.

    python3 -m scripts.ask "can I cancel my order after 5 minutes?"
    python3 -m scripts.ask --show-prompt "how long does a card refund take"   # see what the LLM sees
"""
import argparse
import asyncio

from app.db import make_pool
from app.rag import retriever
from app.rag.answer import SYSTEM_PROMPT, answer, build_prompt


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--show-prompt", action="store_true")
    args = ap.parse_args()

    pool = make_pool()
    await pool.open(wait=True)
    try:
        if args.show_prompt:
            chunks = await retriever.search(pool, args.question, k=args.k)
            print("=" * 30, "SYSTEM", "=" * 30, f"\n{SYSTEM_PROMPT}\n")
            print("=" * 30, "PROMPT", "=" * 30, f"\n{build_prompt(args.question, chunks)}\n")
        r = await answer(pool, args.question, k=args.k)
    finally:
        await pool.close()

    print(f"{'✅ answerable' if r['answerable'] else '🤷 not answerable'}\n\n{r['answer']}\n")
    for c in r["citations"]:
        print(f"  [{c['n']}] {c['section']}  (similarity {c['score']})")
    t = r["timings_ms"]
    print(f"\nretrieval {t['retrieval']} ms · LLM {t['llm']} ms")


if __name__ == "__main__":
    asyncio.run(main())
