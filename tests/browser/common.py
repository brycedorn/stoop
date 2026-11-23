"""Shared settings for the browser suites (see run.py). Each suite is a plain script, not a pytest file: it needs
Playwright, a browser and the site served over http."""
import os
from pathlib import Path

URL = os.environ.get("STOOP_URL", "http://localhost:8765/").rstrip("/") + "/"
OUT = Path(os.environ.get("STOOP_SHOTS", Path(__file__).parent / "shots"))   # screenshots, for a look by eye
OUT.mkdir(parents=True, exist_ok=True)
# WebGL in software, so the map renders in a headless browser without a GPU
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]

# Every suite starts from a clean browser, which would open the first-visit guide over the map. Mark it seen
# (on every page load, so it survives the suites' localStorage.clear()); the intro suite walks the guide itself.
SKIP_INTRO = "try { localStorage.setItem('stoop.intro.v1', 'done'); } catch (e) {}"


def context(browser, **kw):
    ctx = browser.new_context(**kw)
    ctx.add_init_script(SKIP_INTRO)
    return ctx
