"""Partner mode end to end: import, rename, switch, remove, pins, detail, hex view, sharing, bad links, phone."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL, context
S = "window.__stoop"
res, errs = [], []


def check(name, ok, detail=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def open_(ctx, url, clear=False):
    p = ctx.new_page()
    p.on("pageerror", lambda e: errs.append(f"{url[-40:]}: {e}"))
    p.on("console", lambda m: m.type == "error" and "favicon" not in m.text and errs.append(f"console: {m.text[:120]}"))
    if clear:
        p.goto(URL + "rank.html")
        p.evaluate("() => localStorage.clear()")
    p.goto(url)
    if "rank.html" not in url:
        p.wait_for_function(f"{S} && {S}.map()", timeout=120000)
        p.wait_for_timeout(800)
    return p


def st(p, expr):
    return p.evaluate(f"() => {expr}")


def people_txt(p):
    return p.inner_text("#people")


with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    ctx = context(b, viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])

    # 1. returned link: import, note, rename clears note, remove clears note
    me = open_(ctx, URL + "#w=gym:30,commute:20&rent=4000&bd=1&min=50", clear=True)
    me.close()
    back = URL + "index.html#add=1&pn=Sam&pw=dogs:30,running:22&ppin=40.7527,-73.9772,Grand Central"
    me = open_(ctx, back)
    check("import: note shows", "priorities are in" in people_txt(me))
    check("import: priorities tab open", st(me, f"{S}.state.tab") == "priorities")
    me.click('#people [data-who="1"]'); me.wait_for_timeout(200)
    me.fill("#personName", "Samantha"); me.press("#personName", "Enter"); me.wait_for_timeout(300)
    check("rename clears the note", "priorities are in" not in people_txt(me), people_txt(me)[:80])
    check("rename applies", st(me, f"{S}.state.people[1].name") == "Samantha")
    me.click("#removePartner"); me.wait_for_timeout(300)
    t = people_txt(me)
    check("remove: no note, no partner", "priorities are in" not in t and st(me, f"{S}.state.people.length") == 1, t[:80])
    check("remove: back to editing you", st(me, f"{S}.state.editing") == 0)
    me.close()

    # 2. remove right after import (the reported bug)
    me = open_(ctx, back)
    me.click('#people [data-who="1"]'); me.wait_for_timeout(200)
    me.click("#removePartner"); me.wait_for_timeout(300)
    check("import then remove: note gone", "priorities are in" not in people_txt(me), people_txt(me)[:80])
    me.reload(); me.wait_for_function(f"{S} && {S}.map()", timeout=120000); me.wait_for_timeout(600)
    me.click("#tab-priorities")
    check("after reload: no partner, no note", st(me, f"{S}.state.people.length") == 1 and "priorities are in" not in people_txt(me))
    check("after reload: address bar has no import", "add=1" not in st(me, "location.hash"))

    # 3. add a partner by hand, presets, scoring rules
    me.click("#addPartner"); me.wait_for_timeout(300)
    check("add by hand: editing partner", st(me, f"{S}.state.editing") == 1)
    me.click("#presets button[data-p='Runner']"); me.wait_for_timeout(400)
    you_w = st(me, f"JSON.stringify({S}.state.people[0].weights)")
    par_w = st(me, f"JSON.stringify({S}.state.people[1].weights)")
    check("preset changes only the partner", you_w != par_w)
    me.click('#people [data-who="0"]'); me.wait_for_timeout(300)
    yw = json.loads(you_w)
    first_rank = me.locator("#rank .rk").first.get_attribute("data-k")
    check("switching shows your list", yw[first_rank] == max(yw.values()), first_rank)
    check("combined = lower of the two, everywhere",
          st(me, f"{S}.results().filter(r => r.total != null).every(r => Math.abs(r.total - Math.min(...r.totals)) < 1e-9)"))
    check("ranking ordered by combined score",
          st(me, f"(() => {{ const v = {S}.results().filter(r => r.rank).map(r => r.total); return v.every((x, i) => !i || v[i-1] >= x); }})()"))
    me.click("#reset"); me.wait_for_timeout(300)
    check("reset touches only the person being edited", st(me, f"JSON.stringify({S}.state.people[1].weights)") == par_w)

    # 4. partner commute pin: pick, then delete that pin
    me.click('#people [data-who="1"]'); me.wait_for_timeout(200)
    n_opts = me.locator("#partnerPin option").count()
    me.select_option("#partnerPin", index=n_opts - 1); me.wait_for_timeout(500)
    pin = st(me, f"{S}.state.people[1].pin")
    check("partner pin set", pin is not None, pin)
    check("partner's commute changes their scores",
          st(me, f"{S}.results().slice(0, 30).some(r => r.totals[0] != null && r.totals[1] != null && Math.abs(r.totals[0] - r.totals[1]) > 0.01)"))
    me.click("#destBox summary"); me.wait_for_timeout(300)
    rm = me.locator("#destMenu button[aria-label^='Remove']")
    check("commute menu has remove buttons", rm.count() > 0, rm.count())
    if rm.count():
        rm.last.click(); me.wait_for_timeout(500)
    if me.locator("#destBox[open]").count():
        me.click("#destBox summary")
    me.wait_for_timeout(200)
    sel = me.input_value("#partnerPin") if me.locator("#partnerPin").count() else "n/a"
    check("deleted pin: partner falls back to same as yours", sel == "-1" and st(me, f"{S}.state.people[1].pin") is None or sel == "-1", (sel, st(me, f"{S}.state.people[1].pin")))

    # 5. detail panel and hex view with a partner
    me.click("#tab-matches"); me.wait_for_timeout(200)
    me.click("#ranking li .row"); me.wait_for_timeout(1200)
    d = me.inner_text("#detail")
    check("detail shows both scores", "Ranked by the lower of the two" in d and "for both" in d)
    hexes = st(me, f"{S}.map().querySourceFeatures('hexes').length")
    check("hex view renders with a partner", hexes > 0, hexes)
    me.mouse.move(1000, 450); me.wait_for_timeout(400)
    me.keyboard.press("Escape"); me.wait_for_timeout(300)

    # 6. partner link to a fresh browser
    me.click("#tab-priorities"); me.click("#copyLink"); me.wait_for_timeout(300)
    link = me.evaluate("() => navigator.clipboard.readText()")
    ctx2 = context(b, viewport={"width": 1440, "height": 900})
    p2 = open_(ctx2, link)
    check("partner link: two people in a fresh browser", st(p2, f"{S}.state.people.length") == 2)
    top = f"JSON.stringify({S}.results().slice(0,5).map(r => r.id))"
    check("partner link: same combined top 5", st(p2, top) == st(me, top))
    p2.close(); ctx2.close()

    # 7. invite round trip with a hostile name
    me.click("#invite"); me.wait_for_timeout(300)
    inv = me.evaluate("() => navigator.clipboard.readText()")
    phctx = context(b, viewport={"width": 390, "height": 844}, permissions=["clipboard-read", "clipboard-write"])
    ph = open_(phctx, inv)
    ph.fill("#name", "<img src=x onerror=alert(1)>Bob"); ph.click("#send"); ph.wait_for_timeout(300)
    ret = ph.input_value("#sendLink")
    check("ranking page strips markup from the name", "%3C" not in ret and "<" not in ret, ret[:110])
    me2 = open_(ctx, ret)
    nm = st(me2, f"{S}.state.people[1].name")
    check("imported name is plain text", "<" not in nm and ">" not in nm, nm)
    check("import replaced the old partner", st(me2, f"{S}.state.people.length") == 2)
    me2.close(); ph.close(); phctx.close()

    # 8. malformed links
    n0 = len(errs)
    for bad in ["#add=1&pn=X", "#add=1&pw=bogus:abc,running:-5&ppin=91,999,x", "#pw=running:10", "#w=&pw=&pn=", "#add=1&pw=running:10&ppin=,,"]:
        p = open_(ctx, URL + bad); p.close()
    check("malformed links load without errors", len(errs) == n0, errs[n0:n0 + 2])

    # 9. plain link + old 5K link
    p = open_(ctx, URL + "#w=running:10,run5k:30")
    check("plain link: one person, 5K weight carried",
          st(p, f"{S}.state.people.length") == 1 and st(p, f"{S}.state.people[0].weights.running") == 30)
    p.close()

    # 10. phone, dark theme
    dctx = context(b, viewport={"width": 390, "height": 844}, color_scheme="dark")
    p = open_(dctx, back); p.wait_for_timeout(500)
    p.screenshot(path=str(OUT / "phone_import_dark.png"))
    check("phone: partner bar fits", p.evaluate("() => { const e = document.getElementById('people'); return e.scrollWidth <= e.clientWidth + 1; }"))
    dctx.close()
    b.close()
check("no page or console errors", not errs, "; ".join(errs[:4]))
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
