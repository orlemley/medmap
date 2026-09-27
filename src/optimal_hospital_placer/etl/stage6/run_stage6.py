"""Stage 6 dispatcher.

Recommended hackathon workflow:
  python run_stage6.py screen
  python run_stage6.py fast

Or in one command:
  python run_stage6.py pipeline

Precise road routing is intentionally deferred until after Stage 7 has reduced
this output to a very small finalist set.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def call(script: str, args: list[str]) -> int:
    return subprocess.run([sys.executable, str(HERE / script), *args], check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["screen", "fast", "pipeline"])
    known, rest = parser.parse_known_args()

    if known.command == "screen":
        return call("run_stage6a.py", rest)
    if known.command == "fast":
        return call("run_stage6_fast.py", rest)

    # Pipeline intentionally uses Stage 6A defaults. For custom screening policy,
    # run `screen` explicitly first, then `fast`.
    rc = call("run_stage6a.py", [])
    if rc != 0:
        return rc
    return call("run_stage6_fast.py", rest)


if __name__ == "__main__":
    raise SystemExit(main())
