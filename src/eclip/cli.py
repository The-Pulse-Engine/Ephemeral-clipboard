import argparse
import asyncio
import math
import sys
from collections.abc import Callable, Sequence
from typing import TypeVar

from . import __version__, protocol
from .relay import Relay, serve

T = TypeVar("T", int, float)


def _positive(kind: Callable[[str], T]) -> Callable[[str], T]:
    def parse(text: str) -> T:
        value = kind(text)
        # isfinite refuses nan (which passes "<= 0") and inf (which turns the limit off)
        if not (math.isfinite(value) and value > 0):
            raise argparse.ArgumentTypeError(f"must be a finite number above zero, got {text}")
        return value

    return parse


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
    serve_parser.add_argument(
        "--ttl", type=_positive(float), default=300, help="Connection lifetime in seconds."
    )
    serve_parser.add_argument("--max-rooms", type=_positive(int), default=1000)
    serve_parser.add_argument("--max-ip-connections", type=_positive(int), default=20)
    serve_parser.add_argument(
        "--max-message", type=_positive(int), default=protocol.MAX_MESSAGE, help="In bytes."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "send":
        sys.exit("send: not implemented yet")
    elif args.command == "receive":
        sys.exit("receive: not implemented yet")
    elif args.command == "serve":
        relay = Relay(args.ttl, args.max_rooms, args.max_ip_connections, args.max_message)
        asyncio.run(serve(args.host, args.port, relay))


if __name__ == "__main__":
    main()
