"""First-visit guide: shown once to a new visitor, never over a shared link or saved settings; the match colors stay
hidden until the priorities are confirmed, then fade in."""
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL, context

S = "window.__stoop"
res, errs = [], []


def check(name, ok, detail=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def ready(page):
    page.wait_for_function(f"{S} && {S}.map() && {S}.map().loaded()", timeout=120000)
    page.wait_for_timeout(1200)


def fill_k(page):
    """The fill layer's opacity factor at city zoom (state.fill times the guide's veil)."""
    return page.evaluate("() => { const e = window.__stoop.map().getPaintProperty('fill', 'fill-opacity'); return e[4][1]; }")


def fresh(b, **kw):
    """A browser with nothing saved: no settings, and the guide not seen (unlike context(), which skips it)."""
    ctx = b.new_context(**kw)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    return ctx, page


with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    ctx, page = fresh(b, viewport={"width": 1440, "height": 900})
    page.goto(URL); ready(page)
    check("new visitor: welcome shows", page.evaluate(f"{S}.intro()") == "welcome")
    check("welcome: colors held back", fill_k(page) == 0, fill_k(page))
    check("welcome: page behind can't be tabbed into", page.evaluate("document.querySelector('.topbar').inert && document.getElementById('panel').inert"))
    check("welcome: focus on its heading", page.evaluate("document.activeElement.id") == "introTitle")
    page.screenshot(path=str(OUT / "intro_welcome.png"))

    page.click("[data-go=priorities]"); page.wait_for_timeout(600)
    check("step 1: priorities tab open", page.evaluate(f"{S}.state.tab") == "priorities")
    lifted = page.evaluate("""() => { const r = document.getElementById('rank').getBoundingClientRect();
      const el = document.elementFromPoint(r.left + 40, r.top + 20); return !!el.closest('#rank'); }""")
    check("step 1: the list is above the dimmed page and usable", lifted)
    check("step 1: colors still held back", fill_k(page) == 0)
    page.screenshot(path=str(OUT / "intro_priorities.png"))

    page.click("[data-go=reveal]"); page.wait_for_timeout(1800)
    check("step 2: colors faded in", page.evaluate(f"{S}.veil()") == 1 and fill_k(page) > 0.5, fill_k(page))
    check("step 2: matches tab open", page.evaluate(f"{S}.state.tab") == "matches")
    n = page.evaluate(f"{S}.results().filter(r => r.rank).length")
    check("step 2: says how many fit", f"{n} neighborhood" in page.inner_text("#intro"), n)
    check("step 2: map usable", not page.evaluate("document.getElementById('map').inert") and page.is_hidden("#introScrim"))
    page.screenshot(path=str(OUT / "intro_reveal.png"))

    page.click("[data-go=done]"); page.wait_for_timeout(300)
    check("done: card gone, remembered", page.is_hidden("#intro") and page.evaluate("localStorage.getItem('stoop.intro.v1')") == "done")
    page.reload(); ready(page)
    check("return visit: no guide", page.evaluate(f"{S}.intro()") is None and fill_k(page) > 0.5)

    page.click("#introReplay"); page.wait_for_timeout(600)
    check("How it works: replays the welcome", page.evaluate(f"{S}.intro()") == "welcome" and fill_k(page) == 0)
    page.keyboard.press("Escape"); page.wait_for_timeout(800)
    check("Esc: closes it, colors back", page.evaluate(f"{S}.intro()") is None and fill_k(page) > 0.5)
    ctx.close()

    # a shared link opens straight on the ranking it carries
    ctx, page = fresh(b, viewport={"width": 1440, "height": 900})
    page.goto(URL + "#w=gym:30,commute:20&rent=4000"); ready(page)
    check("shared link: no guide", page.evaluate(f"{S}.intro()") is None and fill_k(page) > 0.5)
    ctx.close()

    # someone with settings saved before the guide existed doesn't get it either
    ctx, page = fresh(b, viewport={"width": 1440, "height": 900})
    page.goto(URL); page.evaluate("() => { localStorage.clear(); localStorage.setItem('stoop.state.v2', JSON.stringify({ budget: 4000 })); }")
    page.reload(); ready(page)
    check("saved settings: no guide", page.evaluate(f"{S}.intro()") is None)
    ctx.close()

    # leaving halfway: it comes back next time
    ctx, page = fresh(b, viewport={"width": 1440, "height": 900})
    page.goto(URL); ready(page)
    page.click("[data-go=priorities]"); page.reload(); ready(page)
    check("left halfway: guide shows again", page.evaluate(f"{S}.intro()") == "welcome")
    ctx.close()

    # phone: the card sits inside the screen at every step, its buttons reachable
    ctx, ph = fresh(b, viewport={"width": 390, "height": 844})
    ph.goto(URL); ready(ph)
    for step, nxt in (("welcome", "priorities"), ("priorities", "reveal"), ("reveal", "done")):
        box = ph.evaluate("() => { const r = document.getElementById('intro').getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; }")
        btn = ph.evaluate(f"() => {{ const r = document.querySelector('[data-go={nxt}]').getBoundingClientRect(); return r.bottom <= innerHeight && r.height >= 40; }}")
        check(f"phone {step}: card on screen, button reachable", box[0] >= 0 and box[1] <= 390 and box[2] >= 0 and box[3] <= 844 and btn, box)
        ph.screenshot(path=str(OUT / f"intro_phone_{step}.png"))
        ph.click(f"[data-go={nxt}]"); ph.wait_for_timeout(1500)
    check("phone: done", ph.evaluate(f"{S}.intro()") is None)
    ctx.close()

    # the suites' own context() skips it
    page = context(b, viewport={"width": 1280, "height": 800}).new_page()
    page.goto(URL); ready(page)
    check("test contexts skip the guide", page.evaluate(f"{S}.intro()") is None)
    b.close()
check("no page errors", not errs, "; ".join(errs[:3]))
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
