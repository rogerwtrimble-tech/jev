"""Run the API (`python -m jev` / `jev serve`) or ask from the CLI (`jev ask "..." --location "Austin, TX"`)."""

from __future__ import annotations

import argparse
import asyncio
import json

from jev.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="jev")
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="Run the FastAPI server (default)")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    ask = sub.add_parser("ask", help="Ask a single question from the command line")
    ask.add_argument("question", nargs="?", default=None)
    ask.add_argument("--location", default=None)
    batch = sub.add_parser("batch", help="Run all configured questions")
    batch.add_argument("--location", default=None)
    args = parser.parse_args()

    if args.cmd in (None, "serve"):
        import uvicorn

        uvicorn.run(
            "jev.api:app",
            host=getattr(args, "host", "0.0.0.0"),
            port=getattr(args, "port", 8000),
            reload=getattr(args, "reload", False),
        )
        return

    asyncio.run(_cli(args))


async def _cli(args) -> None:
    from jev.pipeline import Jev
    from jev.questions import load_questions

    settings = get_settings()
    jev = Jev.from_settings(settings)
    try:
        if args.cmd == "ask":
            results = [await jev.ask(args.question, args.location)]
        else:
            qs, _ = load_questions(settings)
            results = [await jev.ask(q, args.location or settings.default_location) for q in qs]
        for r in results:
            print(json.dumps(r.model_dump(mode="json"), indent=2))
    finally:
        await jev.aclose()


if __name__ == "__main__":
    main()
