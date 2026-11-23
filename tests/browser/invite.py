"""The partner ranking page round trip: invite link, rank on a phone, link back, import."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from common import ARGS, OUT, URL
res, errs = [], []
def check(name, ok, detail=""):
    res.append(bool(ok)); print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)
with sync_playwright() as pw:
    b = pw.chromium.launch(args=ARGS)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    # you: set up a known ranking first
    me = ctx.new_page(); me.on("pageerror", lambda e: errs.append(str(e)))
    me.goto(URL); me.evaluate("() => localStorage.clear()")
    me.close(); me = ctx.new_page(); me.on("pageerror", lambda e: errs.append(str(e)))
    me.goto(URL + "#w=gym:30,commute:20&rent=4000&bd=1&min=50")
    me.wait_for_function("window.__stoop && window.__stoop.map()", timeout=120000); me.wait_for_timeout(1500)
    mine = me.evaluate("() => JSON.stringify(window.__stoop.state.people[0].weights)")
    me.click("#tab-priorities"); me.fill("#people ~ * #personName", "x") if False else None
    me.click("#invite"); me.wait_for_timeout(400)
    inv = me.evaluate("() => navigator.clipboard.readText()")
    check("invite link points at the ranking page", "rank.html" in inv, inv)
    # partner: the ranking page, on a phone-sized screen
    ph = b.new_context(viewport={"width": 390, "height": 844}, permissions=["clipboard-read", "clipboard-write"]).new_page()
    ph.on("pageerror", lambda e: errs.append(str(e)))
    ph.goto(URL + "rank.html#from=Alex"); ph.wait_for_timeout(1000)
    check("page says who asked", "Alex" in ph.inner_text("#lede"))
    n0 = ph.locator("#rank .rk").count()
    check("all factors listed", n0 >= 12, n0)
    ph.screenshot(path=str(OUT / "rank_phone.png"), full_page=True)
    # move "Dog runs" to the top with the keyboard
    grip = ph.locator('#rank .rk[data-k="dogs"] .rk-grip')
    grip.focus()
    for _ in range(25): ph.keyboard.press("ArrowUp")
    first = ph.locator("#rank .rk").first.get_attribute("data-k")
    check("keyboard moves a factor to the top", first == "dogs", first)
    ph.click("#send"); ph.wait_for_timeout(300)
    check("asks for a name before sending", "name" in ph.inner_text("#sendMsg").lower())
    ph.fill("#name", "Sam"); ph.click("#send"); ph.wait_for_timeout(500)
    back = ph.input_value("#sendLink")
    check("send makes a link back to the map", "index.html#add=1" in back and "pn=Sam" in back and "dogs:30" in back, back[:120])
    # add a commute place by hand (the page's lookup needs the internet)
    back += "&ppin=40.7527,-73.9772,Grand Central"
    # you open it
    me.close(); me = ctx.new_page(); me.on("pageerror", lambda e: errs.append(str(e)))
    me.goto(back); me.wait_for_function("window.__stoop && window.__stoop.map()", timeout=120000); me.wait_for_timeout(1500)
    st = me.evaluate("() => ({w: JSON.stringify(window.__stoop.state.people[0].weights), n: window.__stoop.state.people.length, name: window.__stoop.state.people[1]?.name, dogs: window.__stoop.state.people[1]?.weights.dogs, pin: window.__stoop.state.people[1]?.pin, rent: window.__stoop.state.budget})")
    check("your own ranking and must-haves unchanged", json.loads(st["w"]) == json.loads(mine) and st["rent"] == 4000, (mine, st["w"]))
    check("partner added with their ranking", st["n"] == 2 and st["name"] == "Sam" and st["dogs"] == 30)
    check("their commute place became their pin", st["pin"] == {"lat": 40.7527, "lon": -73.9772}, st["pin"])
    check("note says it arrived", "Sam's priorities are in" in me.inner_text("#people"))
    check("address bar cleaned up", "add=1" not in me.evaluate("() => location.hash"))
    me.screenshot(path=str(OUT / "imported.png"))
    b.close()
check("no page errors", not errs, "; ".join(errs[:3]))
print(f"{sum(res)}/{len(res)} passed")
raise SystemExit(0 if all(res) else 1)
