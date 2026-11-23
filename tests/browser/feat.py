"""Dog runs, the rental card, partner mode basics, the partner link and old 5K links."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL
res, errs = [], []
def check(name, ok, detail=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)
def ready(page):
    page.wait_for_function("window.__stoop && window.__stoop.map() && window.__stoop.map().loaded()", timeout=120000)
    page.wait_for_timeout(1200)
with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    # clear storage from another page, then load the map fresh (changing only the hash would make the app reload itself)
    page.goto(URL + "rank.html"); page.evaluate("() => localStorage.clear()"); page.goto(URL); ready(page)
    S = "window.__stoop"
    facs = page.evaluate(f"() => Object.keys({S}.state.people[0].weights)")
    check("dogs is a factor, 5K routes is not", "dogs" in facs and "run5k" not in facs)
    # dog runs on the map
    page.evaluate(f"() => {S}.map().jumpTo({{center: [-73.98, 40.775], zoom: 14}})"); page.wait_for_timeout(2500)
    n = page.evaluate(f"() => {S}.map().querySourceFeatures('dogs').length")
    check("dog runs drawn on the map", n > 0, n)
    # rental fact on the detail card
    page.click("#ranking li .row"); page.wait_for_timeout(800)
    txt = page.inner_text("#detail")
    check("detail shows rentals on the market", "Rentals on the market" in txt, txt[txt.find("Rentals"):txt.find("Rentals") + 110].replace("\n", " | "))
    page.screenshot(path=str(OUT / "detail.png"))
    page.keyboard.press("Escape"); page.wait_for_timeout(300)
    # partner mode
    page.click("#tab-priorities"); page.click("#addPartner"); page.wait_for_timeout(500)
    check("partner added and being edited", page.evaluate(f"() => {S}.state.people.length === 2 && {S}.state.editing === 1"))
    page.fill("#personName", "Sam"); page.press("#personName", "Tab"); page.wait_for_timeout(300)
    page.click("#presets button[data-p='Runner']") if page.locator("#presets button[data-p='Runner']").count() else None
    page.wait_for_timeout(500)
    diff = page.evaluate(f"() => JSON.stringify({S}.state.people[0].weights) !== JSON.stringify({S}.state.people[1].weights)")
    check("partner has their own weights", diff)
    ok = page.evaluate(f"""() => {S}.results().filter(r => r.total != null).slice(0, 40).every(r => Math.abs(r.total - Math.min(...r.totals)) < 1e-9)""")
    check("combined score is the lower of the two", ok)
    opts = page.locator("#partnerPin option").count()
    if opts > 2:
        page.select_option("#partnerPin", index=2); page.wait_for_timeout(800)
    check("partner can pick their own commute pin", opts >= 2, f"{opts} options")
    page.screenshot(path=str(OUT / "priorities.png"))
    page.click("#tab-matches"); page.wait_for_timeout(500)
    both = page.inner_text("#ranking li .score .both")
    check("list rows show both scores", "·" in both, both)
    page.screenshot(path=str(OUT / "matches.png"))
    # persistence
    page.reload(); ready(page)
    check("partner survives a reload", page.evaluate(f"() => {S}.state.people.length === 2 && {S}.state.people[1].name === 'Sam'"))
    # share link
    page.click("#tab-priorities"); page.click("#copyLink"); page.wait_for_timeout(500)
    link = page.evaluate("() => navigator.clipboard.readText()")
    check("partner link carries both rankings and pins", all(x in link for x in ("pw=", "pn=Sam", "pins=")), link[:140])
    p2 = ctx.new_page(); p2.on("pageerror", lambda e: errs.append(str(e)))
    p2.goto(URL + "rank.html"); p2.evaluate("() => localStorage.clear()"); p2.goto(link); ready(p2)
    st = p2.evaluate(f"() => ({{n: {S}.state.people.length, name: {S}.state.people[1]?.name, pin: {S}.state.people[1]?.pin}})")
    check("partner link opens both people", st["n"] == 2 and st["name"] == "Sam", st)
    p2.close()
    # old link with a 5K weight
    p3 = ctx.new_page(); p3.on("pageerror", lambda e: errs.append(str(e)))
    p3.goto(URL + "#w=running:10,run5k:30,commute:20&rent=5000"); ready(p3)
    check("old 5K weight carries into running", p3.evaluate(f"() => {S}.state.people[0].weights.running") == 30)
    check("a plain link drops the partner", p3.evaluate(f"() => {S}.state.people.length") == 1)
    p3.close()
    b.close()
check("no page errors", not errs, "; ".join(errs[:3]))
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
