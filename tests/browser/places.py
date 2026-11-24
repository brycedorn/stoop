"""Your bars & restaurants, edited in the browser: find a place (the lookup is answered locally, no network), add it,
see it on the map and in its neighborhood's details, keep it after a reload, remove / undo / reset; plus the key's
ringed icons. Works whatever the built list holds (the public site ships none)."""
import json
from playwright.sync_api import sync_playwright
from common import ARGS, URL, context

S = "window.__stoop"
res, errs = [], []
LINK = "#w=running:30,commute:25,rent:20,green:10&rent=4000&bd=1&min=50"
NAME = "Stoop Test Diner"


def check(name, ok, detail=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def ready(page):
    page.wait_for_function(f"{S} && {S}.map() && {S}.map().loaded()", timeout=120000)
    page.wait_for_timeout(1200)


def open_editor(page):
    page.evaluate("() => { document.querySelector('#layersBox').open = true; }")
    page.wait_for_timeout(150)
    if not page.evaluate("document.querySelector('#plEd').open"):
        page.click("#plEd > summary")
    page.wait_for_timeout(150)


n_places = lambda page: page.evaluate("(window.STOOP_LAYERS.places || []).length")

with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    ctx = context(b, viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(URL + LINK); ready(page)
    page.evaluate("localStorage.removeItem('stoop.places.v1')"); page.reload(); ready(page)
    # the map's recount of "your places within walk" agrees with the pipeline's for the built list
    gap = page.evaluate(f"""() => Math.max(0, ...{S}.results().map(r => r.f.properties)
      .filter(p => p.metrics.fav_within_walk != null).map(p => Math.abs({S}.placesWithinWalk(p) - p.metrics.fav_within_walk)))""")
    check("within-walk recount matches the built figure", gap < 0.5, round(gap, 3))

    # the place sits at the label point of the top match, so it's inside that neighborhood
    top = page.evaluate(f"() => {{ const r = {S}.results().find(r => r.rank === 1); return [r.id, r.f.properties.label]; }}")
    lon, lat = top[1]
    hit = [{"name": NAME, "lat": str(lat), "lon": str(lon), "display_name": NAME + ", New York",
            "address": {"house_number": "1", "road": "Test Street", "neighbourhood": "Testville", "suburb": "Manhattan Community Board 3", "borough": "Manhattan"}}]
    asked = []
    page.route("https://nominatim.openstreetmap.org/**", lambda r: (asked.append(r.request.url), r.fulfill(status=200, content_type="application/json", body=json.dumps(hit))))

    check("places row shows even with an empty list", page.evaluate("!!document.querySelector('#plEd')"))
    n0 = n_places(page)
    open_editor(page)
    page.fill("#placeInput", "test diner"); page.press("#placeInput", "Enter"); page.wait_for_timeout(500)
    where = page.text_content(".pl-hit span") or ""
    check("find: one lookup, bounded to NYC", len(asked) == 1 and "bounded=1" in asked[0] and "test+diner" in asked[0].lower(), asked[:1])
    check("result shows street, neighborhood, borough (no community board)", where == "1 Test Street, Testville, Manhattan", where)
    check("keyboard lands on the first result", page.evaluate("document.activeElement.classList.contains('pl-hit')"))
    page.click(".pl-hit"); page.wait_for_timeout(900)
    check("added: one more place", n_places(page) == n0 + 1, [n0, n_places(page)])
    check("added: listed with an Undo", NAME in page.text_content(".pl-list") and page.is_visible("#undoPlace"))
    on_map = page.evaluate(f"() => {{ const m = {S}.map(); m.jumpTo({{ center: [{lon}, {lat}], zoom: 16 }}); return new Promise(r => m.once('idle', () => r(m.queryRenderedFeatures({{ layers: ['places'] }}).some(f => f.properties.name === '{NAME}')))); }}")
    check("added: on the map", on_map)
    page.click("#ranking li button.row >> nth=0"); page.wait_for_timeout(800)   # the top match, sorted best first
    check("the top match is open", page.evaluate(f"{S}.state.selected") == top[0])
    check("added: in that neighborhood's details", NAME in (page.text_content("#detail") or ""))
    walk = page.evaluate("""() => [...document.querySelectorAll('#detail tr')].map(tr => [...tr.cells].map(c => c.textContent))
      .find(c => c[0] === 'Your places within walk')""")
    check("added: counted in 'Your places within walk'", walk and float(walk[1].replace(",", "")) >= 1, walk)

    page.reload(); ready(page)
    check("kept after a reload", n_places(page) == n0 + 1 and NAME in page.evaluate("JSON.stringify(window.STOOP_LAYERS.places)"))
    check("not in a shared link", NAME.split()[0] not in page.evaluate("location.href"))
    open_editor(page)
    page.click(f"[data-unplace='{NAME}']"); page.wait_for_timeout(400)
    check("remove", n_places(page) == n0 and page.evaluate("document.activeElement.id") == "undoPlace")
    page.click("#undoPlace"); page.wait_for_timeout(400)
    check("undo", n_places(page) == n0 + 1)
    if n0:   # a built list: removing one of its places hides every branch, and Reset brings them back
        first = page.evaluate("window.STOOP_LAYERS.places.find(r => r[2] !== '%s')[2]" % NAME)
        k = page.evaluate("(n) => window.STOOP_LAYERS.places.filter(r => r[2] === n).length", first)
        page.click(f"[data-unplace={json.dumps(first)}]"); page.wait_for_timeout(400)
        check("remove a built place: all its branches", n_places(page) == n0 + 1 - k, [n0, k, n_places(page)])
        page.click("#resetPlaces"); page.wait_for_timeout(400)
        check("reset: the built list again", n_places(page) == n0 and not page.is_visible("#resetPlaces"))
    page.evaluate("localStorage.removeItem('stoop.places.v1')")

    # the key's ringed icons: one box draws the dot and both rings, so they can't drift apart
    page.reload(); ready(page)
    page.evaluate("() => { document.querySelector('#layersBox').open = true; }"); page.wait_for_timeout(200)
    rings = page.evaluate("""() => ['.sw-bus', '.key-ic .pin'].map(s => { const cs = getComputedStyle(document.querySelector('#layersMenu ' + s));
      return [s, cs.borderTopStyle, cs.boxShadow.includes('0px 0px 0px') && !cs.boxShadow.includes('inset')]; })""")
    check("ringed icons: border rings, no outer spread shadows", all(r[1] == "solid" and not r[2] for r in rings), rings)
    m = page.evaluate("() => { const r = document.querySelector('#layersMenu').getBoundingClientRect(); return [r.bottom, innerHeight]; }")
    check("layers menu stays inside the window", m[0] <= m[1], m)
    b.close()
check("no page errors", not errs, "; ".join(errs[:3]))
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
