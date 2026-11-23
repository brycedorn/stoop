"""Shared settings for the browser suites (see run.py). Each suite is a plain script, not a pytest file: it needs
Playwright, a browser and the site served over http."""
import os
from pathlib import Path

URL = os.environ.get("STOOP_URL", "http://localhost:8765/").rstrip("/") + "/"
OUT = Path(os.environ.get("STOOP_SHOTS", Path(__file__).parent / "shots"))   # screenshots, for a look by eye
OUT.mkdir(parents=True, exist_ok=True)
# WebGL in software, so the map renders in a headless browser without a GPU
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
