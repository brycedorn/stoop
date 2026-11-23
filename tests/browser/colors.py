"""Match colors: the palette switch, the fill slider, both remembered, and the fade as you zoom in to street level."""
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL

S = "window.__stoop"
res, errs = [], []


def check(name, ok, detail=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


# Which side of each outline the edges band lands on: query the band 6 px either side of several border
# segments and test each point against the shape (point in polygon). layer: "edge" (neighborhoods) or "hex-edge".
SIDE_JS = """async ([layer, shapes]) => {
  const m = window.__stoop.map();
  const inPoly = (pt, poly) => { let c = false; for (const ring of poly) for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c; } return c; };
  const inGeom = (pt, g) => g.type === 'Polygon' ? inPoly(pt, g.coordinates) : g.coordinates.some((p) => inPoly(pt, p));
  let inside = 0, outside = 0;
  for (const [key, val, g, zoom] of shapes) {
    const ring = g.type === 'Polygon' ? g.coordinates[0] : g.coordinates[0][0];
    m.setFilter(layer, ['==', ['get', key], val]);
    for (let k = 0; k < 6; k++) {
      const i = Math.floor((ring.length - 1) * (k + 0.5) / 6), a = ring[i], b = ring[i + 1], mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      m.jumpTo({ center: mid, zoom });
      await new Promise((res) => { m.once('idle', res); m.triggerRepaint(); });
      const pa = m.project(a), pb = m.project(b), pm = m.project(mid), len = Math.hypot(pb.x - pa.x, pb.y - pa.y);
      if (len < 4) continue;
      for (const sgn of [1, -1]) {
        const q = { x: pm.x - sgn * (pb.y - pa.y) / len * 6, y: pm.y + sgn * (pb.x - pa.x) / len * 6 };
        const ll = m.unproject(q);
        if (m.queryRenderedFeatures([q.x, q.y], { layers: [layer] }).length) inGeom([ll.lng, ll.lat], g) ? inside++ : outside++;
      }
    }
  }
  m.setFilter(layer, null);
  return [inside, outside];
}"""


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
    # edges: the shapes stay clear and a band inside each outline carries the color
    page.click('#legend [data-shade="edge"]'); page.wait_for_timeout(400)
    st = page.evaluate("""() => { const m = window.__stoop.map();
      return { fill: JSON.stringify(m.getPaintProperty('fill', 'fill-opacity')), edge: JSON.stringify(m.getPaintProperty('edge', 'line-opacity')),
               off: JSON.stringify(m.getPaintProperty('edge', 'line-offset')) }; }""")
    check("edges: no fill inside the shapes", st["fill"].endswith(",0.22,0]"), st["fill"])
    check("edges: band drawn at the fill strength", "0.3" in st["edge"], st["edge"])
    check("edges: band offset to one side", '"zoom"' in st["off"], st["off"][:60])
    chip = page.evaluate("() => { const b = document.querySelector('#legend [data-pal]').getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; }")
    check("palette chips are rounded rectangles", chip[0] > chip[1], chip)
    page.screenshot(path=str(OUT / "colors_edges.png"), clip={"x": 400, "y": 72, "width": 1040, "height": 828})
    hoods = page.evaluate(f"() => {S}.results().filter(r => r.visible && r.total != null).slice(0, 3).map(r => ['id', r.id, r.f.geometry, 15])")
    ins, outs = page.evaluate(SIDE_JS, ["edge", hoods])
    check("edges: neighborhood band is on the inside", ins >= 12 and outs <= 1, (ins, outs))
    page.click("#ranking li .row"); page.wait_for_timeout(1500)
    hx = page.evaluate("() => window.__stoop.map().getSource('hexes')._data.features.slice(0, 3).map(f => ['i', f.properties.i, f.geometry, 16.5])")
    ins, outs = page.evaluate(SIDE_JS, ["hex-edge", hx])
    check("edges: hex band is on the inside", ins >= 12 and outs <= 1, (ins, outs))
    # hover: an edge hex (cut to the outline) shows its whole outline, drawn above the neighborhood borders
    pt = page.evaluate("""() => { const m = window.__stoop.map(), bx = m.getContainer().getBoundingClientRect();
      for (const f of m.getSource('hexes')._data.features.filter((f) => f.geometry.type === 'MultiPolygon')) {
        const ring = f.geometry.coordinates[0][0]; let x = 0, y = 0; ring.slice(0, -1).forEach((c) => { x += c[0]; y += c[1]; });
        const q = m.project([x / (ring.length - 1), y / (ring.length - 1)]);
        if (q.x > 10 && q.y > 10 && q.x < bx.width - 10 && q.y < bx.height - 10 && m.queryRenderedFeatures(q, { layers: ['hex-fill'] })[0]?.id === f.id)
          return [q.x + bx.left, q.y + bx.top, f.id]; } return null; }""")
    if pt:
        page.mouse.move(pt[0], pt[1]); page.wait_for_timeout(300)
        hv = page.evaluate("""(id) => { const m = window.__stoop.map(), ids = m.getStyle().layers.map((l) => l.id);
          return { state: !!m.getFeatureState({ source: 'hexes', id }).hover, above: ids.indexOf('hex-hover') > ids.indexOf('line'),
                   drawn: m.queryRenderedFeatures({ layers: ['hex-hover'] }).length > 0 }; }""", pt[2])
        check("hex hover: edge hex outlined above the borders", all(hv.values()), hv)
    else:
        check("hex hover: edge hex outlined above the borders", False, "no edge hex on screen")
    page.keyboard.press("Escape"); page.wait_for_timeout(300)
    # remembered after a reload
    page.reload(); ready(page)
    check("edges remembered", page.evaluate(f"() => {S}.state.shade") == "edge")
    # first load with Edges saved: the bands draw straight away, no Fill/Edges toggle needed
    page.evaluate(f"() => {S}.map().jumpTo({{center: [-73.93, 40.715], zoom: 11}})"); page.wait_for_timeout(800); idle(page)
    first = page.evaluate("""() => { const m = window.__stoop.map();
      return { n: m.queryRenderedFeatures({ layers: ['edge'] }).length, op: JSON.stringify(m.getPaintProperty('edge', 'line-opacity')),
               color: JSON.stringify(m.getPaintProperty('edge', 'line-color')) }; }""")
    check("edges: drawn on first load", first["n"] > 20 and "rgba(0,0,0,0)" != first["color"].strip('"') and '"case"' in first["op"], first["n"])
    # the classes move when the filters change: the bands must follow the fill
    page.evaluate("() => { const r = document.getElementById('budget') || document.querySelector('input[type=range][aria-label*=rent i]'); r.value = +r.value - 800; r.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.wait_for_timeout(600)
    th = page.evaluate("""() => { const m = window.__stoop.map();
      const step = (e) => Array.isArray(e) ? (e[0] === 'step' ? e : e.map(step).find(Boolean)) : null;
      const cuts = (e) => { const st = step(e); return st ? [3, 5, 7, 9].map((i) => +st[i].toFixed(3)) : null; };
      return [cuts(m.getPaintProperty('fill', 'fill-color')), cuts(m.getPaintProperty('edge', 'line-color'))]; }""")
    check("edges: band classes follow the filters", th[0] is not None and th[0] == th[1], th)
    page.click('#legend [data-shade="fill"]'); page.wait_for_timeout(300)
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
