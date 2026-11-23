"""Top-bar dropdowns and the Reset button at several screen widths."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL
res = []
def check(name, ok, detail=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)
with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    for w, h in ((1440, 900), (1280, 800), (1024, 768), (390, 844)):
        page = b.new_page(viewport={"width": w, "height": h})
        page.goto(URL + "#w=gym:30&rent=3000&bd=1&min=45")
        page.wait_for_function("window.__stoop && window.__stoop.map()", timeout=120000); page.wait_for_timeout(1000)
        mobile = w < 861
        if mobile: page.click("#filtersToggle"); page.wait_for_timeout(300)
        # Reset button: visible (filters differ from defaults) and on the toggle's line
        r = page.evaluate("""() => { const vis = [...document.querySelectorAll('.reset-filters')].filter(b => b.offsetParent);
          if (vis.length !== 1) return { n: vis.length };
          const a = vis[0].getBoundingClientRect(), ref = (vis[0].classList.contains('reset-by-count') ? document.getElementById('count') : document.querySelector('.toggle')).getBoundingClientRect();
          return { n: 1, which: vis[0].className, dy: Math.round((a.top + a.height / 2) - (ref.top + ref.height / 2)), gapx: Math.round(a.left - ref.right), below: Math.round(a.top - ref.bottom), inView: a.right <= innerWidth };}""")
        ok = r.get("n") == 1 and r["inView"] and ((not mobile and abs(r["dy"]) <= 2 and 0 <= r["gapx"] <= 16) or (mobile and r["below"] >= 0))
        check(f"{w}: one Reset, placed and aligned", ok, r)
        page.screenshot(path=str(OUT / f"top_{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": 140 if not mobile else 420})
        # commute menu
        page.click("#destBox summary"); page.wait_for_timeout(300)
        m = page.evaluate("""() => { const r = (id) => { const b = document.getElementById(id).getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), Math.round(b.width), Math.round(b.height)]; };
          return { menu: r('destMenu'), input: r('addrInput'), vw: innerWidth }; }""")
        check(f"{w}: commute menu wide enough, address box full height", m["menu"][2] >= min(320, w - 32) - 1 and m["input"][3] >= 34 and m["input"][2] >= 150, m)
        check(f"{w}: commute menu inside the window", m["menu"][0] >= 0 and m["menu"][1] <= m["vw"], m["menu"])
        mb = page.locator("#destMenu").bounding_box()
        page.screenshot(path=str(OUT / f"destmenu_{w}.png"), clip={"x": mb["x"] - 4, "y": mb["y"] - 4, "width": min(mb["width"] + 8, w - mb["x"] + 4), "height": min(mb["height"] + 8, h - mb["y"] + 4)})
        page.click("#destBox summary"); page.wait_for_timeout(200)
        # radius menu
        page.click("#areaBox summary"); page.wait_for_timeout(300)
        a = page.evaluate("""() => { const r = (el) => { const b = el.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), Math.round(b.width), Math.round(b.height), Math.round(b.top)]; };
          const head = document.querySelector('.area-range .range-head'), sl = document.getElementById('areaKm');
          return { menu: r(document.getElementById('areaMenu')), slider: r(sl), head: r(head), vw: innerWidth }; }""")
        check(f"{w}: radius slider full width, under its label", a["slider"][2] >= a["menu"][2] - 40 and a["slider"][4] > a["head"][4], a)
        check(f"{w}: radius menu inside the window", a["menu"][0] >= 0 and a["menu"][1] <= a["vw"], a["menu"])
        ab = page.locator("#areaMenu").bounding_box()
        page.screenshot(path=str(OUT / f"areamenu_{w}.png"), clip={"x": ab["x"] - 4, "y": ab["y"] - 4, "width": min(ab["width"] + 8, w - ab["x"] + 4), "height": ab["height"] + 8})
        page.click("#areaBox summary")
        # borough menu checkboxes keep their size
        page.click("#boroughBox summary" if page.locator("#boroughBox").count() else "details:has(#boroughs) summary"); page.wait_for_timeout(200)
        cb = page.evaluate("() => { const i = document.querySelector('#boroughs input'); const b = i.getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; }")
        check(f"{w}: borough checkboxes 16 px", cb == [16, 16], cb)
        page.close()
    b.close()
# One-row top bar on laptop and desktop screens, with Reset showing and with wider text (Mac fonts run wider):
# the over-budget toggle stays on the controls' row and the bar keeps its height. Narrow windows may wrap.
ROW = """() => { const t = document.querySelector('.topbar'), kids = [...document.querySelectorAll('.filters > *')].filter(e => e.offsetParent);
  const tg = document.querySelector('.filters .toggle').getBoundingClientRect(), first = kids[0].getBoundingClientRect();
  return { h: Math.round(t.getBoundingClientRect().height), dy: Math.round(tg.bottom - first.bottom), fit: t.className.replace('topbar', '').trim() }; }"""
with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    for wide in (False, True):
        for w in (1680, 1512, 1440, 1366, 1280):
            page = b.new_page(viewport={"width": w, "height": 800})
            page.goto(URL + "#w=gym:30&rent=3000&bd=1&min=45")
            page.wait_for_function("window.__stoop && window.__stoop.map()", timeout=120000)
            if wide: page.add_style_tag(content=".topbar { letter-spacing: .05em; }")
            page.wait_for_timeout(600)
            r = page.evaluate(ROW)
            check(f"{w}{' wide text' if wide else ''}: top bar one row", r["h"] <= 76 and abs(r["dy"]) <= 2, r)
            page.screenshot(path=str(OUT / f"top_row_{w}{'_wide' if wide else ''}.png"), clip={"x": 0, "y": 0, "width": w, "height": 100})
            page.close()
    b.close()
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
