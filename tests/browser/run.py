"""Run the browser suites against the site in web/ (or --url).

    python tests/browser/run.py              # every suite, against a server started here on a free port
    python tests/browser/run.py e2e menus    # just these
    python tests/browser/run.py --url http://localhost:8765/

Needs `pip install playwright` and `playwright install chromium`, plus built data in web/data
(`python -m stoop run`, or `python -m stoop demo` for fake data; some checks expect real layers).
Software WebGL is slow: the full set takes several minutes.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
WEB = HERE.parent.parent / "web"
SUITES = ["feat", "invite", "e2e", "menus", "colors"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("suites", nargs="*", default=SUITES, help=f"any of {', '.join(SUITES)}")
    ap.add_argument("--url", help="test a site that's already being served")
    args = ap.parse_args()
    server = None
    url = args.url
    if not url:
        port = free_port()
        server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=WEB,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://localhost:{port}/"
        for _ in range(50):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except OSError:
                time.sleep(0.1)
    env = {**os.environ, "STOOP_URL": url, "PYTHONIOENCODING": "utf-8"}
    failed = []
    try:
        for name in args.suites:
            print(f"\n== {name} ({url})", flush=True)
            r = subprocess.run([sys.executable, "-u", str(HERE / f"{name}.py")], env=env, cwd=HERE, text=True,
                               capture_output=True, encoding="utf-8", errors="replace")
            out = r.stdout + (r.stderr if r.returncode and "Traceback" in r.stderr else "")
            print(out.rstrip(), flush=True)
            if r.returncode or re.search(r"^FAIL ", r.stdout, re.M):
                failed.append(name)
    finally:
        if server:
            server.terminate()
    print(f"\n{len(args.suites) - len(failed)}/{len(args.suites)} suites passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
