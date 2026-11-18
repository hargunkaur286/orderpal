"""Talk to the agent from the terminal and watch which tools it calls.

    python3 -m scripts.chat --user 3                          # interactive: it remembers the conversation
    python3 -m scripts.chat --user 3 "where is my last order?"   # one message, new conversation
    python3 -m scripts.chat --user 3 --results                # also print raw tool output

Interactive commands:  /new  start a new conversation   /prefs  show remembered preferences   /quit
"""
import argparse
import asyncio

from app import repo
from app.agent.graph import build_agent, run_agent
from app.agent.memory import make_checkpointer
from app.db import make_pool


def show(r: dict, results: bool) -> None:
    for i, tc in enumerate(r["tool_calls"], 1):
        print(f"🔧 {i}. {tc['tool']}({', '.join(f'{k}={v!r}' for k, v in tc['args'].items())})")
        if results:
            print(f"     → {r['tool_results'][i - 1][:300]}")
    print(f"\n🤖 {r['reply']}\n   ({r['llm_calls']} LLM calls · {r['ms']} ms · "
          f"{r['history_messages']} messages in conversation)\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("message", nargs="?")
    ap.add_argument("--user", type=int, default=1)
    ap.add_argument("--results", action="store_true")
    args = ap.parse_args()

    pool = make_pool()
    await pool.open(wait=True)
    async with make_checkpointer() as (_, saver):
        agent = build_agent(saver)
        try:
            if args.message:
                show(await run_agent(agent, pool, args.user, args.message), args.results)
                return
            conv = None
            print(f"Chatting as user {args.user}. /new, /prefs, /quit\n")
            while (msg := input("you> ").strip()) != "/quit":
                if msg == "/new":
                    conv = None
                    print("(new conversation)\n")
                elif msg == "/prefs":
                    print(await repo.get_preferences(pool, args.user), "\n")
                elif msg:
                    r = await run_agent(agent, pool, args.user, msg, conv)
                    conv = r["conversation_id"]
                    show(r, args.results)
        finally:
            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
