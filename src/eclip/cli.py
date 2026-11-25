import argparse
import asyncio
from collections.abc import Sequence

from . import __version__
from .relay import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eclip",
        description="Send a secret from one computer to another.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("send", help="Send the clipboard contents.")
    receive_parser = subparsers.add_parser("receive", help="Receive a secret.")
    receive_parser.add_argument("code", help="The short eclip code.")
    serve_parser = subparsers.add_parser("serve", help="Run the relay.")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "send":
        print("send: not implemented yet")
    elif args.command == "receive":
        print("receive: not implemented yet")
    elif args.command == "serve":
        asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()
