/* The ranking page: a partner ranks what matters to them and sends it back as a link that adds them to the map
   (index.html#add=1&pn=…&pw=…&ppin=…). Nothing here is stored or sent anywhere except the address lookup. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const DATA = window.STOOP_DATA;
  if (!DATA) { $("nodata").hidden = false; return; }
  const META = DATA.meta;
  const { GROUPS, OTHER, ICON_PATHS, RANK_WEIGHTS } = window.STOOP_UI;
  // "Familiar areas" is built from the map owner's own liked neighborhoods: it means nothing to someone else
  const PERSONAL = new Set(["familiarity", "favorites"]);
  const FACTORS = Object.keys(META.factors).filter((k) => META.factors[k].available && !PERSONAL.has(k));
  // the help text's first clause: what it measures, without the scoring details
  const gist = (k) => String(META.factors[k].help || "").split(/(?<=[a-z)])[:.](?:\s|$)|\s\(/)[0].replace(/\s*\($/, "");
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const darkQuery = matchMedia("(prefers-color-scheme: dark)");
  const theme = () => {
    const t = document.documentElement.dataset.theme;
    return t === "dark" || (t !== "light" && darkQuery.matches) ? "dark" : "light";
  };
  const GROUP_OF = Object.fromEntries(GROUPS.flatMap((g) => g.keys.map((k) => [k, g])));
  const color = (k) => (GROUP_OF[k] || OTHER).color[theme()];
  const icon = (k) => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON_PATHS[k] || "M12 12h.01"}"/></svg>`;
  const GRIP = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>';
  const cleanName = (s) => String(s || "").replace(/[^\p{L}\p{N} .'-]/gu, "").trim().slice(0, 20);

  // Who asked: rank.html#from=Alex
  const from = cleanName(new URLSearchParams(location.hash.slice(1)).get("from"));
  if (from) {
    $("lede").textContent = `${from} is looking for a place for the two of you. Put what matters most to you at the top, then send it back: the map will rank NYC neighborhoods for both of you.`;
    $("send").textContent = `Send to ${from}`;
  }

  // Start from the site's defaults, most important first; the factors at 0 sit below the line
  const w0 = META.weights || {};
  let order = FACTORS.filter((k) => (w0[k] || 0) > 0).sort((a, b) => (w0[b] || 0) - (w0[a] || 0) || FACTORS.indexOf(a) - FACTORS.indexOf(b));
  let off = FACTORS.filter((k) => !((w0[k] || 0) > 0));
  const list = $("rank");

  function render() {
    const item = (k, i, on) => `<li class="rk${on ? "" : " rk-off"}" data-k="${k}" style="--tc:${color(k)}">
        <button class="rk-grip" type="button" aria-label="${esc(META.factors[k].label)}: ${on ? `rank ${i + 1} of ${order.length}` : "doesn't matter"}. Use arrow keys to move.">${GRIP}</button>
        <span class="wic">${icon(k)}</span>
        <span class="rk-name">${esc(META.factors[k].label)}<small class="rk-help">${esc(gist(k))}</small></span>
        <span class="rk-share">${on ? i + 1 : ""}</span></li>`;
    list.innerHTML = order.map((k, i) => item(k, i, true)).join("") +
      `<li class="rk-line" data-line aria-hidden="true"><span>Doesn't matter</span></li>` + off.map((k) => item(k, 0, false)).join("");
  }
  // the list's DOM order -> order / off
  function readDom() {
    order = []; off = [];
    let below = false;
    for (const el of list.children) {
      if (el.dataset.line != null) { below = true; continue; }
      (below ? off : order).push(el.dataset.k);
    }
  }
  const rects = () => new Map([...list.children].map((el) => [el.dataset.k || "line", el.getBoundingClientRect().top]));
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  function flip(before, skip) {
    if (still.matches) return;
    for (const el of list.children) {
      const was = before.get(el.dataset.k || "line");
      if (el === skip || was == null) continue;
      const dy = was - el.getBoundingClientRect().top;
      if (Math.abs(dy) < 1) continue;
      el.style.transition = "none"; el.style.transform = `translateY(${dy}px)`;
      el.getBoundingClientRect();
      el.style.transition = "transform .25s ease-out"; el.style.transform = "";
    }
  }
  const announce = (k) => {
    const r = order.indexOf(k);
    $("rankLive").textContent = `${META.factors[k].label}: ${r >= 0 ? `rank ${r + 1} of ${order.length}` : "doesn't matter"}`;
  };

  // Drag: the card follows the pointer and the others slide out of its way. Touch drags only from the grip.
  let drag = null;
  list.addEventListener("pointerdown", (e) => {
    const el = e.target.closest(".rk");
    if (!el || e.button > 0 || (e.pointerType === "touch" && !e.target.closest(".rk-grip"))) return;
    e.preventDefault();
    drag = { el, id: e.pointerId, grabY: e.clientY - el.getBoundingClientRect().top };
    list.setPointerCapture(e.pointerId);
    el.classList.add("dragging"); list.classList.add("sorting");
  });
  list.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const el = drag.el, mid = e.clientY - drag.grabY + el.offsetHeight / 2;
    const next = [...list.children].filter((c) => c !== el).find((c) => { const b = c.getBoundingClientRect(); return mid < b.top + b.height / 2; }) || null;
    if (next !== el.nextElementSibling) { const before = rects(); list.insertBefore(el, next); flip(before, el); }
  });
  const end = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const k = drag.el.dataset.k;
    drag.el.classList.remove("dragging"); list.classList.remove("sorting");
    drag = null;
    readDom(); render(); announce(k);
  };
  list.addEventListener("pointerup", end);
  list.addEventListener("pointercancel", end);
  list.addEventListener("keydown", (e) => {
    const grip = e.target.closest(".rk-grip");
    if (!grip || !["ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    const el = grip.closest(".rk"), k = el.dataset.k;
    const target = e.key === "ArrowUp" ? el.previousElementSibling : el.nextElementSibling;
    if (!target) return;
    const before = rects();
    if (e.key === "ArrowUp") list.insertBefore(el, target); else list.insertBefore(target, el);
    flip(before);
    readDom(); render(); announce(k);
    list.querySelector(`.rk[data-k="${k}"] .rk-grip`)?.focus();
  });

  // Commute: an address looked up with OpenStreetMap Nominatim (the only request this page makes)
  let pin = null;
  $("addrForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("addr").value.trim();
    if (!q) { pin = null; $("addrMsg").textContent = ""; return; }
    $("addrMsg").textContent = "Looking it up…";
    try {
      const url = "https://nominatim.openstreetmap.org/search?" + new URLSearchParams({
        q: `${q}, New York, NY`, format: "json", limit: "1", viewbox: "-74.26,40.92,-73.70,40.49", bounded: "1" });
      const hit = (await (await fetch(url, { headers: { Accept: "application/json" } })).json())[0];
      if (!hit) { pin = null; $("addrMsg").textContent = "Couldn't find that in NYC. Try adding the borough or a cross street."; return; }
      pin = { lat: +(+hit.lat).toFixed(5), lon: +(+hit.lon).toFixed(5), name: cleanName(q.length > 28 ? q.slice(0, 27) : q) || "Work" };
      $("addrMsg").textContent = `Found: ${hit.display_name.split(",").slice(0, 3).join(",")}`;
    } catch (err) {
      $("addrMsg").textContent = "The address lookup isn't reachable right now. You can send your priorities without it.";
    }
  });

  // Send: the map's address with this person's priorities, as a link to share back
  function link() {
    const weights = order.map((k, i) => `${k}:${RANK_WEIGHTS[i] ?? 2}`).join(",");
    const h = new URLSearchParams({ add: "1", pn: cleanName($("name").value) || "Partner", pw: weights });
    if (pin) h.set("ppin", `${pin.lat},${pin.lon},${pin.name}`);
    return new URL("index.html", location.href).href.split("#")[0] + "#" + h.toString().replace(/%3A/g, ":").replace(/%2C/g, ",");
  }
  $("send").addEventListener("click", async () => {
    if (!order.length) { $("sendMsg").textContent = "Put at least one thing above the line first."; return; }
    if (!cleanName($("name").value)) { $("name").focus(); $("sendMsg").textContent = "Add your name first, so the map can tell your scores apart."; return; }
    const url = link(), to = from || "them";
    $("sendLink").value = url; $("sendLink").hidden = false;
    try {
      if (navigator.share && matchMedia("(hover: none)").matches) {
        await navigator.share({ title: "My neighborhood priorities", url });
        $("sendMsg").textContent = `Shared. When ${to} opens it, the map ranks for both of you.`;
        return;
      }
      await navigator.clipboard.writeText(url);
      $("sendMsg").textContent = `Link copied. Send it to ${to}; opening it adds your priorities to their map.`;
    } catch (err) {
      $("sendMsg").textContent = `Copy the link below and send it to ${to}.`;
      $("sendLink").select();
    }
  });

  render();
})();
