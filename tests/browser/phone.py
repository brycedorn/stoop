"""Phones: the list comes first under a still map strip that opens full screen; a lighter map (fill only, five pins,
transit and places from street zoom, no hex download); and none of it on a desktop-width window."""
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL, context

S = "window.__stoop"
res, errs = [], []
LINK = "#w=running:30,commute:25,rent:20,green:10&rent=4000&bd=1&min=50"


def check(name, ok, detail=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def ready(page):
    page.wait_for_function(f"{S} && {S}.map() && {S}.map().loaded()", timeout=120000)
    page.wait_for_timeout(1500)


def rect(page, sel):
    return page.evaluate(f"() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }}")


with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    ctx = context(b, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    hexreq = []
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("request", lambda r: hexreq.append(r.url) if "hexes.js" in r.url else None)
    # a saved Edges choice from a desktop visit: the phone still fills
    page.goto(URL); page.evaluate("() => localStorage.setItem('stoop.state.v2', JSON.stringify({ shade: 'edge' }))")
    page.goto("about:blank"); page.goto(URL + LINK); ready(page)   # (a hash-only change would reload the app mid-test)

    check("no hex download on a phone", not hexreq and not page.evaluate("!!window.STOOP_HEXES"))
    m = rect(page, "#mapwrap")
    check("strip is about 30% of the screen", 0.25 * 844 <= m[3] <= 0.35 * 844, m)
    check("strip is still (a finger on it scrolls the page)", not page.evaluate(f"{S}.map().dragPan.isEnabled()"))
    check("strip: only the ramp shows", page.is_hidden(".map-tools") and page.is_hidden(".legend-card .colorby") and page.is_hidden(".legend-look"))
    check("saved Edges: a phone still fills", page.evaluate(f"{S}.map().getPaintProperty('fill', 'fill-opacity')[4][1]") > 0.5)
    pins = page.evaluate("() => [...document.querySelectorAll('.mk .pin')].map(p => p.textContent.trim()).filter(Boolean)")
    check("five numbered pins", sorted(pins) == ["1", "2", "3", "4", "5"], pins)
    late = page.evaluate(f"() => {{ const m = {S}.map(); return ['subway-lines', 'grocery'].filter(id => m.getLayer(id)).map(id => m.getLayer(id).minzoom); }}")
    check("transit and places start at street zoom", late and all(z >= 13 for z in late), late)
    parks = page.evaluate(f"() => {S}.map().getLayer('parks-fill')?.minzoom || 0")
    check("parks stay at city zoom", parks < 13, parks)
    sizes = page.evaluate("() => ['#search', '#sort'].map(s => parseFloat(getComputedStyle(document.querySelector(s)).fontSize))")
    check("text fields at 16px (no zoom on focus)", all(s >= 16 for s in sizes), sizes)

    page.evaluate("window.scrollTo(0, 900)"); page.wait_for_timeout(400)
    m, t = rect(page, "#mapwrap"), rect(page, ".tabs")
    check("scrolled: strip stays at the top, tabs under it", abs(m[1]) < 1 and abs(t[1] - (m[1] + m[3])) < 2, [m, t])
    page.screenshot(path=str(OUT / "phone_scrolled.png"))

    # pick from the list: the strip frames it, not too close
    row = page.locator("#ranking li button.row").nth(2)
    row.evaluate("el => el.scrollIntoView({ block: 'center' })"); page.wait_for_timeout(300)
    bb = row.bounding_box(); page.touchscreen.tap(bb["x"] + 60, bb["y"] + bb["height"] / 2); page.wait_for_timeout(1800)
    sel = page.evaluate(f"{S}.state.selected")
    check("list pick opens the sheet", sel and page.is_visible("#detail"), sel)
    check("strip keeps the streets around it", page.evaluate(f"{S}.map().getZoom()") <= 12.01, page.evaluate(f"{S}.map().getZoom()"))
    page.screenshot(path=str(OUT / "phone_pick.png"))
    page.locator("#closeDetail").tap(); page.wait_for_timeout(500)

    # the strip opens the map full screen
    page.locator("#mapOpen").tap(); page.wait_for_timeout(900)
    m = rect(page, "#mapwrap")
    check("Map: full screen, pans and zooms", m[2] == 390 and m[3] >= 840 and page.evaluate(f"{S}.map().dragPan.isEnabled()"), m)
    check("full screen: List, layers and color-by", page.is_visible("#mapClose") and page.is_visible("#layersBox") and page.is_visible(".legend-card .colorby"))
    first = page.evaluate(f"() => {S}.results().find(r => r.rank === 1).id")
    pt = page.evaluate(f"(id) => {{ const m = {S}.map(), r = {S}.results().find(r => r.id === id); const q = m.project(r.f.properties.label); return [q.x, q.y + 14]; }}", first)
    page.touchscreen.tap(pt[0], pt[1]); page.wait_for_timeout(1500)
    check("tap a neighborhood: its sheet opens", page.evaluate(f"{S}.state.selected") == first and page.is_visible("#detail"))
    check("no tooltip over the sheet", page.is_hidden("#tooltip") or page.evaluate("getComputedStyle(document.getElementById('tooltip')).display") == "none")
    page.screenshot(path=str(OUT / "phone_full_tap.png"))
    page.keyboard.press("Escape"); page.wait_for_timeout(400)
    check("Esc: closes the sheet first", page.evaluate(f"{S}.state.selected") is None and page.evaluate("document.body.classList.contains('map-full')"))
    page.keyboard.press("Escape"); page.wait_for_timeout(800)
    check("Esc again: back to the list, strip still", not page.evaluate("document.body.classList.contains('map-full')") and not page.evaluate(f"{S}.map().dragPan.isEnabled()"))

    # a window widened past the phone width behaves as a desktop again
    page.locator("#mapOpen").tap(); page.wait_for_timeout(500)
    page.set_viewport_size({"width": 1280, "height": 844}); page.wait_for_timeout(1200)
    pins = page.evaluate("() => [...document.querySelectorAll('.mk .pin')].map(p => p.textContent.trim()).filter(Boolean).length")
    check("widened: desktop map again", not page.evaluate("document.body.classList.contains('map-full')") and page.evaluate(f"{S}.map().dragPan.isEnabled()")
          and page.is_hidden("#mapOpen") and pins == 10, pins)
    late = page.evaluate(f"() => {S}.map().getLayer('subway-lines')?.minzoom || 0")
    check("widened: transit back to its own zoom", late < 13, late)
    ctx.close()

    # desktop: none of the phone pieces
    dp = context(b, viewport={"width": 1440, "height": 900}).new_page()
    dp.on("pageerror", lambda e: errs.append(str(e)))
    dp.goto(URL + LINK); ready(dp)
    check("desktop: no Map/List buttons, map pans", dp.is_hidden("#mapOpen") and dp.is_hidden("#mapClose") and dp.evaluate(f"{S}.map().dragPan.isEnabled()"))
    check("desktop: hexes loaded", dp.evaluate("!!window.STOOP_HEXES"))
    b.close()
check("no page errors", not errs, "; ".join(errs[:3]))
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
