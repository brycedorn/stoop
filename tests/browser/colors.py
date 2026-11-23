"""Match colors: the palette switch, the fill slider, both remembered, and the fade as you zoom in to street level."""
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL

S = "window.__stoop"
res, errs = [], []


def check(name, ok, detail=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def ready(page):
    page.wait_for_function(f"{S} && {S}.map() && {S}.map().loaded()", timeout=120000)
    page.wait_for_timeout(1200)


def idle(page):
    page.evaluate(f"() => new Promise(r => {{ const m = {S}.map(); m.once('idle', r); m.triggerRepaint(); }})")


def opacity_at(page, z):
    """The fill layer's opacity at zoom z for a non-hovered neighborhood (evaluates the interpolate by hand)."""
    return page.evaluate("""(z) => { const e = window.__stoop.map().getPaintProperty('fill', 'fill-opacity');
      const stops = []; for (let i = 3; i < e.length; i += 2) stops.push([e[i], e[i + 1][1] * e[i + 1][2][3]]);
      if (z <= stops[0][0]) return stops[0][1]; if (z >= stops.at(-1)[0]) return stops.at(-1)[1];
      for (let i = 1; i < stops.length; i++) if (z <= stops[i][0]) { const [z0, a] = stops[i - 1], [z1, b] = stops[i]; return a + (b - a) * (z - z0) / (z1 - z0); } }""", z)


with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(URL + "rank.html"); page.evaluate("() => localStorage.clear()")
    page.goto(URL); ready(page)
    page.evaluate(f"() => {S}.map().jumpTo({{center: [-73.93, 40.715], zoom: 11}})"); page.wait_for_timeout(800); idle(page)
    check("default palette is plum", page.get_attribute('#legend [data-pal="plum"]', "aria-checked") == "true")
    expr = str(page.evaluate("() => window.__stoop.map().getPaintProperty('fill', 'fill-color')"))
    check("map uses the plum colors", "134,64,154" in expr)   # #86409a, the fourth step
    page.screenshot(path=str(OUT / "colors_plum_z11.png"), clip={"x": 400, "y": 72, "width": 1040, "height": 828})
    # fades with zoom
    o11, o16 = opacity_at(page, 11), opacity_at(page, 16)
    check("colors fade at street level", o16 < o11 * 0.6, (round(o11, 2), round(o16, 2)))
    page.evaluate(f"() => {S}.map().jumpTo({{center: [-73.985, 40.74], zoom: 15.5}})"); page.wait_for_timeout(800); idle(page)
    page.screenshot(path=str(OUT / "colors_plum_z15.png"), clip={"x": 400, "y": 72, "width": 1040, "height": 828})
    # switch palette
    page.click('#legend [data-pal="teal"]'); page.wait_for_timeout(400)
    expr = str(page.evaluate("() => window.__stoop.map().getPaintProperty('fill', 'fill-color')"))
    check("teal applies to the map", "31,130,120" in expr)   # #1f8278
    check("teal shows as picked", page.get_attribute('#legend [data-pal="teal"]', "aria-checked") == "true")
    sw = page.evaluate("() => getComputedStyle(document.querySelector('#legend .swatches span:last-child')).backgroundColor")
    check("legend swatches follow", "11, 95, 88" in sw, sw)
    # fill slider
    page.evaluate("() => { const s = document.getElementById('fillK'); s.value = 30; s.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.wait_for_timeout(300)
    check("fill slider scales the colors", abs(opacity_at(page, 11) - 0.3 * o11) < 0.02, round(opacity_at(page, 11), 3))
    page.evaluate(f"() => {S}.map().jumpTo({{center: [-73.93, 40.715], zoom: 11}})"); page.wait_for_timeout(600); idle(page)
    page.screenshot(path=str(OUT / "colors_teal_fill30.png"), clip={"x": 400, "y": 72, "width": 1040, "height": 828})
    # remembered after a reload
    page.reload(); ready(page)
    check("palette remembered", page.evaluate(f"() => {S}.state.palette") == "teal")
    check("fill remembered", abs(page.evaluate(f"() => {S}.state.fill") - 0.3) < 1e-9)
    # dark theme: indigo, then open a neighborhood so the hexes draw in the same colors
    page.click('#legend [data-pal="indigo"]'); page.evaluate("() => { const s = document.getElementById('fillK'); s.value = 100; s.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.click("#themeSeg [aria-label*='Dark'], #themeSeg input[value='dark'] + span") if page.locator("#themeSeg input[value='dark']").count() else None
    page.wait_for_timeout(2500); ready(page)
    page.click("#ranking li .row"); page.wait_for_timeout(1500); idle(page)
    hexc = str(page.evaluate("() => window.__stoop.map().getLayer('hex-fill') && window.__stoop.map().getPaintProperty('hex-fill', 'fill-color')"))
    dark = page.evaluate("() => document.documentElement.dataset.theme")
    check("hexes use the same palette", "rgba(" in hexc and ("135,151,240" in hexc if dark == "dark" else "63,81,201" in hexc), dark)
    page.screenshot(path=str(OUT / "colors_indigo_dark_hexes.png"))
    # phone: the legend controls fit
    ph = b.new_context(viewport={"width": 390, "height": 844}).new_page()
    ph.on("pageerror", lambda e: errs.append(str(e)))
    ph.goto(URL); ready(ph)
    fits = ph.evaluate("() => { const l = document.querySelector('.legend-look'); if (!l) return 'missing'; const r = l.getBoundingClientRect(); return r.right <= innerWidth && l.scrollWidth <= l.clientWidth + 1; }")
    check("phone: color controls fit", fits is True, fits)
    ph.screenshot(path=str(OUT / "colors_phone.png"))
    b.close()
check("no page errors", not errs, "; ".join(errs[:3]))
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
