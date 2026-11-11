/* stoop map: weighting, filtering and ranking all happen here in the browser. */
(function () {
  "use strict";

  const DATA = window.STOOP_DATA;
  const $ = (id) => document.getElementById(id);
  if (!DATA) { $("nodata").hidden = false; return; }

  const META = DATA.meta;
  const GEO = DATA.geojson;
  const FEATS = GEO.features;
  const BY_ID = new Map(FEATS.map((f) => [f.properties.id, f]));
  const FACTORS = Object.keys(META.factors);
  const AVAILABLE = FACTORS.filter((k) => META.factors[k].available);
  const BOROUGHS = [...new Set(FEATS.map((f) => f.properties.borough))].sort();
  const RESIDENTIAL = FEATS.filter((f) => f.properties.residential).length;
  const STORE_KEY = "stoop.state.v2";
  const SHORT_KEY = "stoop.shortlist.v1";
  const MOBILE = () => matchMedia("(max-width: 860px)").matches;

  // Factor groups: the tag color says which group, the icon says which factor, the text says it in words.
  // Three hues only: dataviz's categorical slots 1-3 are the set that passes all-pairs (validate_palette.js
  // --pairs all, light and dark); a fourth hue fails, so the fourth group is neutral ink.
  const GROUPS = [
    { id: "cost", title: "Cost & space", keys: ["rent", "size", "space"], color: { light: "#2a78d6", dark: "#3987e5" } },
    { id: "move", title: "Getting around", keys: ["commute", "airports", "citibike", "errands"], color: { light: "#eb6834", dark: "#d95926" } },
    { id: "life", title: "Lifestyle & outdoors", keys: ["running", "run5k", "gym", "runhex", "green", "favorites", "familiarity"], color: { light: "#1baf7a", dark: "#199e70" } },
    { id: "env", title: "Safety & environment", keys: ["safety", "quiet", "flood"], color: { light: "#6f6d68", dark: "#9a988f" } },
  ];
  const GROUP_OF = Object.fromEntries(GROUPS.flatMap((g) => g.keys.map((k) => [k, g])));
  const OTHER = { id: "other", title: "Other", keys: [], color: { light: "#6f6d68", dark: "#9a988f" } };
  const groupOf = (k) => GROUP_OF[k] || OTHER;
  const groupColor = (k) => groupOf(k).color[theme()];
  // 24px stroke icons, one per factor (shape carries identity alongside the group color)
  const ICON_PATHS = {
    rent: "M12 3v18M16.5 7H10a3 3 0 0 0 0 6h4a3 3 0 0 1 0 6H7",
    size: "M4 4h16v16H4zM4 12h7v8M15 4v5",
    space: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM16.5 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 20c0-3 2.4-5 5.5-5s5.5 2 5.5 5M13.5 15.3c.9-.2 1.9-.3 3-.3 3.1 0 5 2 5 5",
    commute: "M7 3h10a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3zM4 10h16M8 21l2-4M16 21l-2-4M8.5 13.5h.01M15.5 13.5h.01",
    citibike: "M5.5 18.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM18.5 18.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5.5 15l4-7h5.5l3.5 7M9.5 8 8 5H6M12 15l3-7",
    errands: "M5 8h14l-1.2 12H6.2zM9 8V6.5a3 3 0 0 1 6 0V8",
    running: "M4 19c4.5 0 3.5-7 8-7s3.5-7 8-7M18 3l2 2-2 2",
    green: "M12 22v-5M12 2.5l6 8.5h-3.2l4.2 6H5l4.2-6H6z",
    favorites: "M7 3v7a2 2 0 0 0 4 0V3M9 12v9M17 3c-1.7 1.6-2 5.5 0 7.5V21",
    familiarity: "M12 20s-7.5-4.4-7.5-10A4.2 4.2 0 0 1 12 7.3 4.2 4.2 0 0 1 19.5 10c0 5.6-7.5 10-7.5 10z",
    gym: "M6.5 7v10M17.5 7v10M3.5 9.5v5M20.5 9.5v5M6.5 12h11",
    airports: "M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z",
    bus: "M7 3.5h10A2.5 2.5 0 0 1 19.5 6v10.5h-15V6A2.5 2.5 0 0 1 7 3.5zM4.5 11h15M7.5 20v-3.5M16.5 20v-3.5M8 14h.01M16 14h.01",
    safety: "M12 3l7.5 3v6c0 4.2-3.1 7.4-7.5 9-4.4-1.6-7.5-4.8-7.5-9V6z",
    quiet: "M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
    flood: "M3 15c2.2 0 2.2-2 4.5-2s2.3 2 4.5 2 2.2-2 4.5-2 2.3 2 4.5 2M3 19.5c2.2 0 2.2-2 4.5-2s2.3 2 4.5 2 2.2-2 4.5-2 2.3 2 4.5 2M12 3v6M9.5 6.5 12 9l2.5-2.5",
  };
  ICON_PATHS.run5k = "M4 19c0-3.5 3-4 5.5-4S15 14 15 11s-3-3.5-3-3.5M15 3.5v8M15 3.5h5l-1.5 2.25L20 8h-5";
  ICON_PATHS.runhex = "M12 2.5l8.2 4.75v9.5L12 21.5l-8.2-4.75v-9.5zM8 13.5c1.5 0 1.2-3 3-3s1.5 3 3 3 1.2-3 2-3";
  const icon = (k) => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON_PATHS[k] || "M12 12h.01"}"/></svg>`;
  // A tag: tinted chip + colored icon (identity) + ink text (dataviz: text never wears the series color)
  const tag = (k, { weak = false, text = null } = {}) =>
    `<span class="tag${weak ? " weak" : ""}" style="--tc:${groupColor(k)}" title="${esc(META.factors[k]?.label || k)}">${icon(k)}${weak ? "low " : ""}${esc(text ?? short(k))}</span>`;
  const SHORT = {
    favorites: "Your places", gym: "Gyms", airports: "Airports", runhex: "Runner traffic", run5k: "5K routes", familiarity: "Familiar area", size: "Apartment size",
    space: "Breathing room", citibike: "Citi Bike", errands: "Errands", flood: "Flood safety", green: "Green space",
  };
  const short = (k) => SHORT[k] || META.factors[k].label;

  // Sequential ramp, 5 classes (dataviz reference blue). Light: light->dark = low->high.
  // Dark mode flips the anchor: classes get lighter as the match improves.
  const RAMP = {
    // validated with dataviz validate_palette.js --ordinal against the basemap land (#f2f2f0 / #1a1a19)
    light: ["#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    dark: ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
  };
  const BASEMAP = {
    light: "https://tiles.openfreemap.org/styles/positron",
    dark: "https://tiles.openfreemap.org/styles/dark",
  };
  const darkQuery = matchMedia("(prefers-color-scheme: dark)");
  // Theme: Auto follows the system; Light/Dark pin it (data-theme on <html>, set before first paint in index.html)
  const THEME_KEY = "stoop.theme.v1";
  let themeMode = ["light", "dark"].includes(document.documentElement.dataset.theme) ? document.documentElement.dataset.theme : "auto";
  const theme = () => {
    const t = document.documentElement.dataset.theme;
    return t === "dark" || (t !== "light" && darkQuery.matches) ? "dark" : "light";
  };

  const PRESETS = {
    "My defaults": null,
    Balanced: Object.fromEntries(AVAILABLE.map((k) => [k, k === "space" ? 0 : 10])),
    Runner: { running: 30, run5k: 20, runhex: 10, green: 10, commute: 15, rent: 10, gym: 5 },
    "Budget first": { rent: 40, commute: 25, size: 10, safety: 10, errands: 10, running: 5 },
    Quiet: { quiet: 30, green: 20, safety: 20, space: 15, rent: 10, commute: 5 },
    Familiar: { familiarity: 30, commute: 25, rent: 20, running: 15, green: 10 },
  };

  // ---------- state ----------
  const defaults = () => ({
    weights: { ...META.weights },
    budget: META.budget,
    bedrooms: String(Math.min(META.bedrooms ?? 1, 3)),
    maxCommute: 60,
    showOver: false,
    boroughs: BOROUGHS.filter((b) => !(META.exclude_boroughs || []).includes(b)),
  });
  const AREA_DEFAULT = { on: false, km: 4.8, lon: null, lat: null };   // km internally; shown in miles
  const state = { ...defaults(), area: { ...AREA_DEFAULT }, colorBy: "total", sort: "match", fixedScale: false, selected: null, hover: null, query: "", tab: "matches", addingDest: false };
  const SORTS = ["match", "rent", "commute", "size"];
  state.boroughs = new Set(state.boroughs);
  let shortlist = [];
  // Commute destinations (draggable pins). Start from config.yaml; edits live in this browser.
  // Commute is scored to ONE place (config you.commute_to); the others stay on the map as gray pins to switch to.
  const DEST_KEY = "stoop.dests.v2";   // v1 had every destination ticked (an average); start fresh
  const DEST_SEEN_KEY = "stoop.dests.seen.v1";   // config destination names already offered in this browser
  const ACTIVE0 = Number.isInteger(META.commute_to) ? META.commute_to : 0;
  const configDests = () => (META.destinations || []).map((d, i) => ({
    name: d.label || d.name || `Destination ${i + 1}`, lat: +d.lat, lon: +d.lon, weight: d.weight ?? 1, on: i === ACTIVE0 }));
  const setActive = (i) => dests.forEach((d, j) => { d.on = j === i; });
  let dests = configDests();
  try {
    const s = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
    if (s) {
      for (const k of FACTORS) if (typeof s.weights?.[k] === "number") state.weights[k] = s.weights[k];
      if (s.budget > 0) state.budget = s.budget;
      if (["0", "1", "2", "3"].includes(s.bedrooms)) state.bedrooms = s.bedrooms;
      if (s.maxCommute > 0) state.maxCommute = s.maxCommute;
      if (typeof s.showOver === "boolean") state.showOver = s.showOver;
      // Saved borough picks win, except when config's exclude_boroughs changed since they were saved: then it applies
      const excl = JSON.stringify(META.exclude_boroughs || []);
      if (Array.isArray(s.boroughs) && (s.excludeSeen === undefined ? excl === "[]" : s.excludeSeen === excl))
        state.boroughs = new Set(s.boroughs.filter((b) => BOROUGHS.includes(b)));
      if (s.colorBy === "total" || AVAILABLE.includes(s.colorBy)) state.colorBy = s.colorBy;
      if (SORTS.includes(s.sort)) state.sort = s.sort;
      if (s.area && Number.isFinite(s.area.km)) state.area = { ...AREA_DEFAULT, ...s.area };
      if (typeof s.fixedScale === "boolean") state.fixedScale = s.fixedScale;
    }
    shortlist = (JSON.parse(localStorage.getItem(SHORT_KEY) || "[]") || []).filter((id) => BY_ID.has(id));
    const d = JSON.parse(localStorage.getItem(DEST_KEY) || "null");
    if (Array.isArray(d) && d.every((x) => Number.isFinite(x.lat) && Number.isFinite(x.lon))) {
      dests = d;
      if (dests.filter((x) => x.on).length !== 1 && dests.length) setActive(Math.max(0, dests.findIndex((x) => x.on)));
      // Destinations added to config.yaml since this list was saved join it (unselected). "Seen" remembers which
      // config destinations were already offered, so one you removed on purpose doesn't come back.
      let seen = null;
      try { seen = JSON.parse(localStorage.getItem(DEST_SEEN_KEY) || "null"); } catch (e) {}
      const at = (m) => dests.some((x) => x.lat === +m.lat && x.lon === +m.lon);
      for (const [i, m] of (META.destinations || []).entries())
        if (seen ? !seen.includes(m.name) : !at(m)) dests.push({ ...configDests()[i], on: false });
      // A saved pin still at a configured spot under its config name picks up the config's label (e.g. "Acme · Midtown")
      for (const x of dests) {
        const c = (META.destinations || []).find((m) => +m.lat === x.lat && +m.lon === x.lon);
        if (c && c.label && x.name === c.name) x.name = c.label;
      }
    }
  } catch (e) { /* storage unavailable: defaults are fine */ }

  function persist() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        weights: state.weights, budget: state.budget, bedrooms: state.bedrooms, maxCommute: state.maxCommute,
        showOver: state.showOver, boroughs: [...state.boroughs], colorBy: state.colorBy, sort: state.sort, fixedScale: state.fixedScale, area: state.area,
        excludeSeen: JSON.stringify(META.exclude_boroughs || []),
      }));
      localStorage.setItem(SHORT_KEY, JSON.stringify(shortlist));
      localStorage.setItem(DEST_KEY, JSON.stringify(dests));
      localStorage.setItem(DEST_SEEN_KEY, JSON.stringify((META.destinations || []).map((m) => m.name)));
    } catch (e) {}
  }

  // ---------- live commute (mirrors stoop/sources/commute.py estimate_minutes + scoring.commute_curve) ----------
  // Pipeline commute_min is used as-is while the destinations match config.yaml. Switching a configured pin
  // off re-averages its routed per-destination times (p.commutes), so that stays exact. A moved or new pin
  // is estimated: walk to the nearest subway, a wait, a straight-line ride at subway speed, then the walk at
  // the far end (or walking all the way when that's quicker), plus the neighborhood's routed-vs-estimate OFFSET.
  const CM = META.commute_model || { walk_m_per_min: 80, subway_m_per_min: 330, wait_min: 5, detour: 1.3, curve_good: 20, curve_bad: 75, weights: { commute_min: 0.85, station_dist_m: 0.15 } };
  const LAT0 = 40.7, KX = 111320 * Math.cos((LAT0 * Math.PI) / 180), KY = 110540;
  const toXY = ([lon, lat]) => [lon * KX, lat * KY];
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const STATIONS = (META.stations || []).map(toXY);
  const nearestStation = (xy) => {
    let best = null, bd = Infinity;
    for (const s of STATIONS) { const d = dist(xy, s); if (d < bd) { bd = d; best = s; } }
    return [best, bd];
  };
  const HOME = new Map(FEATS.map((f) => {
    const xy = toXY(f.properties.label || center(f));
    const [st, d] = STATIONS.length ? nearestStation(xy) : [null, null];
    return [f.properties.id, { xy, st, walk: f.properties.metrics.station_dist_m ?? d }];
  }));
  const sameAsConfig = () => JSON.stringify(dests.map(({ lat, lon, on }) => [lat, lon, on])) ===
    JSON.stringify(configDests().map(({ lat, lon, on }) => [lat, lon, on]));
  let liveCommute = null;   // Map id -> minutes, or null while using the pipeline's numbers
  let liveTargets = null;   // {targets, wsum} of the live destinations, or null
  let liveEstimated = false; // true when some active destination has no routed times (moved or new pin)
  // Rough estimate from a neighborhood to one destination target ({xy, st, w}).
  const estimateTo = (h, t) => Math.min(
    h.walk / CM.walk_m_per_min + CM.wait_min + dist(h.st, t.st) / CM.subway_m_per_min + t.w / CM.walk_m_per_min,
    (dist(h.xy, t.xy) * CM.detour) / CM.walk_m_per_min);
  const target = (d) => { const xy = toXY([d.lon, d.lat]); const [st, w] = nearestStation(xy); return { xy, st, w }; };
  const CONFIG_TARGETS = STATIONS.length ? configDests().map(target) : [];
  // Per neighborhood: routed minus estimated minutes, averaged over the configured destinations. It carries what
  // the straight-line estimate misses on the home side (a G-train transfer, a bus to the subway), so a moved pin's
  // estimate starts from the routed truth instead of the raw guess.
  const OFFSET = new Map(FEATS.map((f) => {
    const p = f.properties, h = HOME.get(p.id), routed = p.commutes || [];
    const d = CONFIG_TARGETS.map((t, i) => routed[i] == null || !h.st ? null : routed[i] - estimateTo(h, t)).filter((x) => x != null);
    return [p.id, d.length ? d.reduce((a, x) => a + x, 0) / d.length : 0];
  }));
  // Index of the configured destination at this exact spot, if any (its routed times still apply).
  const configIndex = (d) => configDests().findIndex((c) => c.lat === d.lat && c.lon === d.lon);
  function computeCommutes() {
    const active = dests.filter((d) => d.on);
    liveEstimated = false;
    liveTargets = null;
    if (sameAsConfig() || !active.length) { liveCommute = null; return; }
    const targets = active.map((d) => ({ cfg: configIndex(d), wt: d.weight || 1, t: STATIONS.length ? target(d) : null }));
    const wsum = targets.reduce((a, t) => a + t.wt, 0);
    liveTargets = { targets, wsum };   // the hex view reuses them
    liveCommute = new Map();
    for (const f of FEATS) {
      const p = f.properties, h = HOME.get(p.id);
      let total = 0, ok = true;
      for (const t of targets) {
        const routed = t.cfg >= 0 ? p.commutes?.[t.cfg] : null;
        let m = routed;
        if (m == null) {
          if (!t.t || !h.st) { ok = false; break; }
          liveEstimated = true;
          const est = estimateTo(h, t.t), walkOnly = (dist(h.xy, t.t.xy) * CM.detour) / CM.walk_m_per_min;
          m = Math.max(1, Math.min(est + (OFFSET.get(p.id) || 0), walkOnly));
        }
        total += m * t.wt;
      }
      if (ok) liveCommute.set(p.id, total / wsum);
    }
  }
  const commuteOf = (p) => (liveCommute ? liveCommute.get(p.id) : p.metrics.commute_min);
  const commuteCurve = (m) => Math.min(Math.max((CM.curve_bad - m) / (CM.curve_bad - CM.curve_good), 0), 1) * 100;
  // station-distance percentile among residential areas (lower distance = better), like scoring.percentile
  const STATION_PCT = (() => {
    const v = FEATS.filter((f) => f.properties.residential && f.properties.metrics.station_dist_m != null)
      .map((f) => [f.properties.id, f.properties.metrics.station_dist_m]).sort((a, b) => b[1] - a[1]);
    const out = new Map(), n = v.length;
    for (let i = 0; i < n;) {           // average rank for ties
      let j = i; while (j + 1 < n && v[j + 1][1] === v[i][1]) j++;
      const pct = n > 1 ? (((i + j) / 2) / (n - 1)) * 100 : 50;
      for (let k = i; k <= j; k++) out.set(v[k][0], pct);
      i = j + 1;
    }
    return out;
  })();
  function liveCommuteScore(p) {
    const parts = [[commuteOf(p) == null ? null : commuteCurve(commuteOf(p)), CM.weights.commute_min],
      [STATION_PCT.get(p.id) ?? null, CM.weights.station_dist_m]].filter(([s]) => s != null);
    const w = parts.reduce((a, [, x]) => a + x, 0);
    return w ? parts.reduce((a, [s, x]) => a + s * x, 0) / w : null;
  }

  // ---------- scoring (mirrors stoop/scoring.py) ----------
  function rentCurve(rent, budget) {
    if (rent == null) return null;
    const r = rent / budget;
    if (r <= 0.7) return 100;
    if (r <= 1.0) return 100 - ((r - 0.7) / 0.3) * 50;
    if (r <= 1.15) return 50 - ((r - 1.0) / 0.15) * 50;
    return 0;
  }
  const rentOf = (p) => (p.rents && p.rents[state.bedrooms] != null ? p.rents[state.bedrooms] : p.metrics.rent_est);
  const rentSource = (p) => (p.rent_sources && p.rent_sources[state.bedrooms]) || p.metrics.rent_source;
  const rentIsEstimate = (p) => rentSource(p) && rentSource(p) !== "listings";
  const commuteIsEstimate = (p) => (liveCommute ? liveEstimated : p.metrics.commute_method === "estimate");
  const bedLabel = (b) => ({ 0: "studio", 3: "3+ bed" }[b] || `${b}-bed`);

  function evaluate(p) {
    const s = { ...p.scores };
    const rent = rentOf(p), mins = commuteOf(p);
    if (rent != null) s.rent = rentCurve(rent, state.budget);
    if (liveCommute) s.commute = liveCommuteScore(p);
    let num = 0, den = 0;
    for (const k of FACTORS) {
      const w = state.weights[k] || 0;
      if (w > 0 && s[k] != null) { num += s[k] * w; den += w; }
    }
    const total = den ? num / den : null;
    // contribution = share of the weight actually used for this place x factor score
    const parts = FACTORS.filter((k) => (state.weights[k] || 0) > 0 && s[k] != null)
      .map((k) => ({ k, score: s[k], share: state.weights[k] / den, pts: (s[k] * state.weights[k]) / den }))
      .sort((a, b) => b.pts - a.pts);
    const fails = [];
    if (!state.showOver && rent != null && rent > state.budget) fails.push({ k: "rent", over: rent - state.budget,
      text: `Over your budget: ${fmtRent(rent)} for a ${bedLabel(state.bedrooms)}`,
      short: RENT_BAND ? `${fmtRent(rent)}, over budget` : `$${fmtInt(rent - state.budget)}/mo over budget` });
    if (mins != null && mins > state.maxCommute) fails.push({ k: "commute", over: mins - state.maxCommute,
      text: `Commute ${commuteIsEstimate(p) ? "~" : ""}${Math.round(mins)} min, over your ${state.maxCommute} min limit`,
      short: `${Math.max(1, Math.round(mins - state.maxCommute))} min over your commute limit` });
    let reason = null, near = null;
    if (!p.residential) reason = "Not a residential area (park, airport, etc.)";
    else if (!state.boroughs.has(p.borough)) reason = `${p.borough} is filtered out`;
    else if (areaDistKm(p) > state.area.km) reason = `Outside your area: ${fmtMi(areaDistKm(p))} from its center`;
    else if (fails.length) {
      reason = fails.map((f) => f.text).join("; ");
      // Near miss: every failed must-have is only just missed
      if (total != null && fails.every((f) => (f.k === "rent" ? f.over <= state.budget * NEAR_RENT : f.over <= NEAR_MIN)))
        near = fails.map((f) => f.short).join(" · ");
    }
    return { s, total, parts, visible: !reason, reason, near };
  }

  // Area filter: straight-line distance from the area center to the neighborhood's label point (inside it,
  // near where people live). Off or no center = everything is in.
  const KM_PER_MI = 1.609344;
  const fmtMi = (km) => `${(km / KM_PER_MI).toFixed(km / KM_PER_MI < 10 ? 1 : 0)} mi`;
  function areaDistKm(p) {
    const a = state.area;
    if (!a.on || a.lon == null) return 0;
    const h = HOME.get(p.id);
    return h ? dist(h.xy, toXY([a.lon, a.lat])) / 1000 : 0;
  }
  // Default center: your first liked neighborhood (config liked_neighborhoods), else the middle of the data
  function defaultAreaCenter() {
    for (const n of META.liked_neighborhoods || []) {
      const f = FEATS.find((x) => x.properties.name.toLowerCase() === String(n).toLowerCase())
        || FEATS.find((x) => x.properties.name.toLowerCase().includes(String(n).toLowerCase()));
      if (f) return { at: f.properties.label || center(f), name: f.properties.name };
    }
    const [[a, b], [c, d]] = bbox(FEATS);
    return { at: [(a + c) / 2, (b + d) / 2], name: null };
  }

  const NEAR_RENT = 0.15, NEAR_MIN = 10;   // "near miss": within 15% of the budget, 10 min of the commute limit

  // Bonus factors are zero almost everywhere by design (only near places you liked), so a low
  // score there isn't a weakness worth calling out.
  const BONUS = new Set(["familiarity"]);
  function strengths(r) {
    const pos = r.parts.filter((x) => x.score >= 70 && x.share >= 0.04).sort((a, b) => b.score - a.score).slice(0, 2);
    const neg = r.parts.filter((x) => x.score < 35 && x.share >= 0.06 && !BONUS.has(x.k)).sort((a, b) => a.score - b.score).slice(0, 1);
    return { pos, neg };
  }

  let results = [], byId = new Map(), thresholds = [20, 40, 60, 80];
  function recompute() {
    computeCommutes();
    results = FEATS.map((f) => ({ f, id: f.properties.id, ...evaluate(f.properties) }));
    results.sort((a, b) => (b.total ?? -1) - (a.total ?? -1));
    let rank = 0;
    for (const r of results) r.rank = r.visible && r.total != null ? ++rank : null;
    byId = new Map(results.map((r) => [r.id, r]));
    // Quintile classes among visible matches, so the five colors split the actual range
    const vals = results.filter((r) => r.visible).map(colorValue).filter((v) => v != null).sort((a, b) => a - b);
    if (state.fixedScale) thresholds = [20, 40, 60, 80];
    else if (vals.length >= 10) {
      thresholds = [1, 2, 3, 4].map((i) => vals[Math.floor((vals.length * i) / 5)]);
      for (let i = 1; i < 4; i++) if (thresholds[i] <= thresholds[i - 1]) thresholds[i] = thresholds[i - 1] + 0.01;
    } else thresholds = [20, 40, 60, 80];
  }
  const colorValue = (r) => (state.colorBy === "total" ? r.total : r.s[state.colorBy]);

  // ---------- formatting ----------
  const fmtInt = (v) => Math.round(v).toLocaleString("en-US");
  // The public site carries rent only as bands (META.rent_band dollars wide, value = the band's middle), never the
  // source's exact medians; locally it's the exact number.
  const RENT_BAND = META.rent_band || 0;
  const fmtRent = (v) => (RENT_BAND ? `$${fmtInt(v - RENT_BAND / 2)}–${fmtInt(v + RENT_BAND / 2)}` : "$" + fmtInt(v));
  function fmtMetric(v, fmt) {
    if (v == null) return "—";
    switch (fmt) {
      case "usd": return fmtRent(v);
      case "min": return Math.round(v) + " min";
      case "m": return v >= 1000 ? (v / 1000).toFixed(1) + " km" : Math.round(v) + " m";
      case "km": return (v / 1000).toFixed(1) + " km";
      case "ha": return Math.round(v) + " ha";
      case "sqft": return fmtInt(v) + " ft²";
      case "pct": return Math.round(v * 100) + "%";
      case "int": return fmtInt(v);
      case "text": return String(v).replace(/_/g, " ");
      default: return typeof v === "number" ? v.toFixed(1) : String(v);
    }
  }
  // Whole-number percentages that add up to exactly 100 (largest remainder).
  function pctShares(values) {
    const sum = values.reduce((a, v) => a + v, 0);
    if (!sum) return values.map(() => 0);
    const raw = values.map((v) => (v / sum) * 100), out = raw.map(Math.floor);
    let left = 100 - out.reduce((a, v) => a + v, 0);
    raw.map((v, i) => [v - out[i], i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (left > 0 && values[i] > 0) { out[i]++; left--; } });
    return out;
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path stroke-linejoin="round" d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/></svg>';
  const CLOSE = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  const ALERT = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/></svg>';

  // ---------- top bar ----------
  function buildFilters() {
    for (const input of document.querySelectorAll('input[name="bd"]')) {
      input.checked = input.value === state.bedrooms;
      input.onchange = () => { state.bedrooms = input.value; update(); };
    }
    const budget = $("budget"), commute = $("maxCommute");
    budget.value = state.budget; commute.value = state.maxCommute;
    budget.oninput = () => { state.budget = +budget.value; schedule(); };
    commute.oninput = () => { state.maxCommute = +commute.value; schedule(); };
    $("showOver").checked = state.showOver;
    $("showOver").onchange = (e) => { state.showOver = e.target.checked; update(); };

    $("boroughs").innerHTML = BOROUGHS.map((b) =>
      `<label><input type="checkbox" value="${esc(b)}" ${state.boroughs.has(b) ? "checked" : ""}> ${esc(b)}</label>`).join("") +
      `<p class="dd-hint" id="boroughMsg" role="status" hidden>Keep at least one borough.</p>`;
    $("boroughs").onchange = (e) => {
      const b = e.target.value;
      if (!e.target.checked && state.boroughs.size === 1) { e.target.checked = true; $("boroughMsg").hidden = false; return; }
      $("boroughMsg").hidden = true;
      e.target.checked ? state.boroughs.add(b) : state.boroughs.delete(b);
      update();
    };
    closeOnOutside("boroughBox");
    $("filtersToggle").onclick = () => {
      const open = !document.querySelector(".topbar").classList.contains("open");
      document.querySelector(".topbar").classList.toggle("open", open);
      $("filtersToggle").setAttribute("aria-expanded", String(open));
    };
  }
  function syncFilters() {
    $("budgetOut").textContent = "$" + fmtInt(state.budget);
    $("commuteOut").textContent = state.maxCommute + " min";
    const n = state.boroughs.size;
    $("boroughSummary").textContent = n === BOROUGHS.length ? "All" : n === 0 ? "None" :
      n <= 2 ? [...state.boroughs].join(", ") : `${n} of ${BOROUGHS.length}`;
    const shown = results.filter((r) => r.rank).length;
    $("count").innerHTML = `<b>${shown}</b> of ${RESIDENTIAL} <span class="cl">neighborhoods </span>match`;
    $("count").title = `${shown} of ${RESIDENTIAL} residential neighborhoods meet your must-haves`;
    $("filtersSummary").textContent = `${bedLabel(state.bedrooms)} · $${fmtInt(state.budget)} · ${state.maxCommute} min` +
      (n < BOROUGHS.length ? ` · ${n} borough${n === 1 ? "" : "s"}` : "") +
      (state.area.on ? ` · ${fmtMi(state.area.km)} radius` : "");
    syncArea();
  }
  // ---------- area filter (radius around a draggable center) ----------
  // Point-in-polygon over every neighborhood, and syncArea asks three times per slider tick: remember the last one
  let areaNameAt = null, areaName = "";
  function areaCenterName() {
    const a = state.area;
    if (a.lon == null) return "";
    const at = a.lon + "," + a.lat;
    if (at !== areaNameAt) {
      const f = FEATS.find((x) => x.properties.residential && inGeom([a.lon, a.lat], x.geometry));
      areaNameAt = at; areaName = f ? f.properties.name : "the pin";
    }
    return areaName;
  }
  function syncArea() {
    const a = state.area;
    $("areaOn").checked = a.on;
    $("areaKm").value = (a.km / KM_PER_MI).toFixed(2);
    $("areaOut").textContent = `${fmtMi(a.km)} (${a.km.toFixed(1)} km)`;
    $("areaSummary").innerHTML = a.on ? `${esc(fmtMi(a.km))}<span class="rc"> · ${esc(areaCenterName())}</span>` : "Off";
    $("areaSummary").title = a.on ? `Within ${fmtMi(a.km)} of ${areaCenterName()}` : "";
    $("areaSummary").classList.toggle("edited", a.on);
    $("areaCenter").textContent = a.lon == null ? "" : `Center: ${areaCenterName()}`;
    $("areaUseSel").disabled = !state.selected;
  }
  function ensureAreaCenter() {
    if (state.area.lon != null) return;
    const d = defaultAreaCenter();
    state.area.lon = +d.at[0].toFixed(5); state.area.lat = +d.at[1].toFixed(5);
  }
  function areaChanged() { renderAreaOnMap(); update(); }
  function buildArea() {
    $("areaOn").onchange = (e) => { state.area.on = e.target.checked; if (state.area.on) ensureAreaCenter(); areaChanged(); };
    $("areaKm").oninput = (e) => {
      state.area.km = +e.target.value * KM_PER_MI;
      if (!state.area.on) { state.area.on = true; ensureAreaCenter(); }
      renderAreaOnMap(); schedule();
    };
    $("areaPick").onclick = () => { $("areaBox").open = false; setAreaPickMode(true); };
    $("areaUseSel").onclick = () => {
      const f = BY_ID.get(state.selected);
      if (!f) return;
      const at = f.properties.label || center(f);
      Object.assign(state.area, { on: true, lon: +at[0].toFixed(5), lat: +at[1].toFixed(5) });
      areaChanged();
    };
    closeOnOutside("areaBox");
  }
  function setAreaPickMode(on) {
    state.pickingArea = on;
    if (on && state.addingDest) setAddMode(false);
    $("mapHint").textContent = on ? "Click the map to place the area's center · Esc to cancel" : "Click the map to drop a destination · Esc to cancel";
    $("mapHint").hidden = !on;
    if (map) map.getCanvas().style.cursor = on ? "crosshair" : "";
  }
  const TARGET = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="6.5"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/></svg>';
  let areaMarker = null;
  // A circle as a polygon ring (planar, fine at city scale)
  function circleRing(lon, lat, km, n = 96) {
    const [cx, cy] = toXY([lon, lat]), r = km * 1000, ring = [];
    for (let i = 0; i <= n; i++) {
      const t = (i / n) * Math.PI * 2;
      ring.push([(cx + r * Math.cos(t)) / KX, (cy + r * Math.sin(t)) / KY]);
    }
    return ring;
  }
  function areaGeo() {
    const a = state.area;
    if (!a.on || a.lon == null) return { type: "FeatureCollection", features: [] };
    const ring = circleRing(a.lon, a.lat, a.km);
    return { type: "FeatureCollection", features: [
      { type: "Feature", properties: { part: "mask" }, geometry: { type: "Polygon",
        coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], [...ring].reverse()] } },
      { type: "Feature", properties: { part: "edge" }, geometry: { type: "LineString", coordinates: ring } },
    ] };
  }
  function renderAreaOnMap() {
    if (!map) return;
    if (map.getSource("area")) map.getSource("area").setData(areaGeo());
    const a = state.area;
    if (!a.on || a.lon == null) { areaMarker?.remove(); areaMarker = null; return; }
    if (!areaMarker) {
      const el = document.createElement("div");
      el.className = "area-pin";
      el.innerHTML = TARGET;
      el.title = "Area center: drag to move";
      el.setAttribute("aria-label", "Area center");
      areaMarker = new maplibregl.Marker({ element: markerRoot(el), draggable: true }).setLngLat([a.lon, a.lat]).addTo(map);
      areaMarker.on("dragstart", () => el.classList.add("dragging"));
      areaMarker.on("drag", () => {   // live: the circle and the matches follow the pin
        const ll = areaMarker.getLngLat();
        state.area.lon = +ll.lng.toFixed(5); state.area.lat = +ll.lat.toFixed(5);
        map.getSource("area")?.setData(areaGeo()); schedule();
      });
      areaMarker.on("dragend", () => { el.classList.remove("dragging"); update(); });
    } else areaMarker.setLngLat([a.lon, a.lat]);
  }

  // Close a <details> menu on any click outside it. composedPath() still holds the original ancestors
  // when a click re-renders the menu (removing the clicked node), so the menu stays open in that case.
  function closeOnOutside(id) {
    document.addEventListener("click", (e) => { if (!e.composedPath().includes($(id))) $(id).open = false; });
  }

  // ---------- tabs ----------
  function setTab(name) {
    state.tab = name;
    for (const t of ["matches", "priorities", "shortlist"]) {
      $("tab-" + t).setAttribute("aria-selected", String(t === name));
      $("pane-" + t).hidden = t !== name;
    }
    if (name === "matches") renderRanking();
    if (name === "shortlist") renderShortlist();
  }
  function buildTabs() {
    const tabs = ["matches", "priorities", "shortlist"];
    for (const t of tabs) $("tab-" + t).onclick = () => setTab(t);
    document.querySelector(".tabs").onkeydown = (e) => {
      const i = tabs.indexOf(state.tab);
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        setTab(next); $("tab-" + next).focus();
      }
    };
  }

  // ---------- ranking ----------
  function rowHtml(r, { off = false, near = false } = {}) {
    const p = r.f.properties, rent = rentOf(p), mins = commuteOf(p);
    const facts = [esc(p.borough),
      rent != null ? `${fmtRent(rent)}${rentIsEstimate(p) ? '<span class="est" title="Census-based estimate, not listing data">est.</span>' : ""}` : null,
      mins != null ? `${commuteIsEstimate(p) ? "~" : ""}${Math.round(mins)} min` : null].filter(Boolean).join(" · ");
    const { pos, neg } = strengths(r);
    // data-keep: which tag survives when the row is too narrow for all of them (fitTags)
    const why = near ? `<span class="reason">${esc(r.near)}</span>` : off ? `<span class="reason">${esc(r.reason || "")}</span>` :
      pos.map((x, i) => tag(x.k).replace("<span ", `<span data-keep="${i ? 1 : 3}" `)).join("") +
      (neg.length ? tag(neg[0].k, { weak: true }).replace("<span ", '<span data-keep="2" ') : "");
    const starred = shortlist.includes(r.id);
    const total = r.total == null ? null : Math.round(r.total);
    // Rank, score, label and state classes change on nearly every slider tick (one row entering the list
    // renumbers all below it), so they stay out of the HTML that patchList caches on and are set in place.
    const html = `<li data-id="${esc(r.id)}">
      <button class="row" type="button" data-select="${esc(r.id)}">
        <span class="rank"></span>
        <span class="main"><span class="name">${esc(p.name)}</span><span class="facts">${facts}</span>${why ? `<span class="why">${why}</span>` : ""}</span>
        <span class="score"><b></b></span>
      </button>
      <button class="icon-btn star" type="button" data-star="${esc(r.id)}" aria-pressed="${starred}" aria-label="${starred ? "Remove from" : "Add to"} shortlist: ${esc(p.name)}">${STAR}</button>
    </li>`;
    const set = (li) => {
      li.classList.toggle("sel", r.id === state.selected);
      li.classList.toggle("off", off || near);
      li.classList.toggle("near", near);
      const btn = li.firstElementChild, rank = btn.firstElementChild, score = btn.lastElementChild.firstChild;
      const label = `${p.name}, match ${total ?? "no data"}${r.rank ? ", rank " + r.rank : ""}`;
      if (btn.getAttribute("aria-label") !== label) btn.setAttribute("aria-label", label);
      if (rank.textContent !== String(r.rank ?? "")) rank.textContent = r.rank ?? "";
      if (score.textContent !== String(total ?? "—")) score.textContent = total ?? "—";
    };
    return { html, set };
  }

  // Sort keys; missing values go last whichever way the list runs
  const SORT_KEY = {
    match: (r) => (r.total == null ? null : -r.total),
    rent: (r) => rentOf(r.f.properties),
    commute: (r) => commuteOf(r.f.properties),
    size: (r) => (r.f.properties.metrics.unit_sqft == null ? null : -r.f.properties.metrics.unit_sqft),
  };
  function sorted(rows) {
    const key = SORT_KEY[state.sort] || SORT_KEY.match;
    return rows.map((r) => [key(r), r]).sort((a, b) => (a[0] == null) - (b[0] == null) || a[0] - b[0] || (b[1].total ?? -1) - (a[1].total ?? -1))
      .map(([, r]) => r);
  }
  const noWeights = () => !AVAILABLE.some((k) => (state.weights[k] || 0) > 0);

  function renderRanking() {
    const q = state.query.trim().toLowerCase();
    const list = $("ranking");
    if (q) {
      const hits = results.filter((r) => r.f.properties.residential && r.f.properties.name.toLowerCase().includes(q));
      const on = sorted(hits.filter((r) => r.rank)), off = sorted(hits.filter((r) => !r.rank));
      patchList(list, !hits.length ? [`<li><span class="empty">No neighborhood called “${esc(state.query)}”.</span></li>`] : [
        ...on.map((r) => rowHtml(r)),
        ...(off.length ? [`<li><span class="divider">Outside your must-haves</span></li>`, ...off.map((r) => rowHtml(r, { off: true }))] : [])]);
      return;
    }
    if (noWeights()) {
      patchList(list, [`<li><span class="empty">Every priority is off, so nothing has a score. Turn one up under Priorities.</span></li>`]);
      return;
    }
    const shown = sorted(results.filter((r) => r.rank));
    // Near misses: the best few that only just miss the budget or commute limit, plus any you've shortlisted
    const nearAll = results.filter((r) => !r.rank && r.near).sort((a, b) => b.total - a.total);
    const near = sorted(nearAll.filter((r, i) => i < 8 || shortlist.includes(r.id)));
    const hidden = RESIDENTIAL - shown.length - near.length;
    patchList(list, [
      ...(shown.length ? shown.map((r) => rowHtml(r))
        : [`<li><span class="empty">Nothing matches. Raise the max rent or commute, or tick “Include over-budget areas”.</span></li>`]),
      ...(near.length ? [`<li><span class="divider">Near misses <small>· just over a must-have</small></span></li>`,
        ...near.map((r) => rowHtml(r, { near: true }))] : []),
      ...(hidden > 0 ? [`<li><span class="empty">${hidden} more neighborhoods don't meet your must-haves. Search to find one.</span></li>`] : [])]);
  }

  // Keyed list render. A row whose HTML is unchanged keeps its node (already fitted) and stays put, so a
  // slider tick only parses and measures the rows that changed. Rebuilding the whole list with innerHTML
  // and re-measuring every row cost ~11 ms per tick, most of a frame.
  // Items are HTML strings, or rowHtml's { html, set } where set(li) writes the per-tick fields in place.
  function patchList(list, items) {
    items = items.map((x) => (typeof x === "string" ? { html: x } : x));
    const htmls = items.map((x) => x.html);
    const pool = new Map();
    for (const li of list.children)
      if (li._html && li._fit) { const p = pool.get(li._html); p ? p.push(li) : pool.set(li._html, [li]); }
    const nodes = htmls.map((h) => pool.get(h)?.shift() || null);
    const missing = htmls.filter((h, i) => !nodes[i]);
    if (missing.length) {
      const tpl = document.createElement("template");
      tpl.innerHTML = missing.join("");
      const made = [...tpl.content.children];
      let k = 0;
      nodes.forEach((n, i) => { if (!n) { nodes[i] = made[k++]; nodes[i]._html = htmls[i]; } });
    }
    // Move only what's out of place, so unchanged rows (and a focused button in one) aren't detached
    let cur = list.firstChild;
    for (const n of nodes) { if (n === cur) cur = cur.nextSibling; else list.insertBefore(n, cur); }
    while (cur) { const next = cur.nextSibling; cur.remove(); cur = next; }
    items.forEach((x, i) => x.set?.(nodes[i]));
    fitTags(list, nodes.filter((n) => !n._fit));
  }

  // Drop whole tags that would be clipped, least important first (2nd strength, then the weakness).
  // Every row's tag strip is the same width, and a given tag is always the same width, so both are measured
  // once and cached: fitting new rows then costs no layout at all (reading sizes after the list changed
  // forced a full relayout of it on every slider tick).
  const TAG_W = new Map();
  const tagKey = (t) => t.className + "|" + t.textContent;
  function fitTags(list, lis) {
    const rows = lis.map((li) => [li, [...li.querySelectorAll(".why [data-keep]")]]);
    const unknown = rows.flatMap(([, tags]) => tags).filter((t) => !TAG_W.has(tagKey(t)));
    if (unknown.length || (!list._whyW && rows.some(([, tags]) => tags.length))) {
      list._whyW ||= rows.map(([li]) => li.querySelector(".why")).find(Boolean)?.clientWidth || 0;
      if (list._whyW) for (const t of unknown) TAG_W.set(tagKey(t), t.offsetWidth + 4);
    }
    for (const [li, tags] of rows) {
      if (!tags.length) { li._fit = true; continue; }
      const avail = list._whyW;
      if (!avail) continue;   // hidden tab: not marked fitted, so it's rebuilt and measured when shown (setTab)
      li._fit = true;
      const ws = tags.map((t) => [t, TAG_W.get(tagKey(t)), +t.dataset.keep]);
      let used = ws.reduce((a, [, w]) => a + w, 0);
      for (const [t, w] of ws.sort((a, b) => a[2] - b[2])) { if (used <= avail) break; t.remove(); used -= w; }
    }
  }
  // A new list width (window resize, mobile rotate) invalidates the fit: rows are rebuilt on the next render
  const listRO = new ResizeObserver((entries) => {
    for (const { target } of entries) {
      const first = target._listW === undefined;
      if (target._listW === target.clientWidth) continue;
      target._listW = target.clientWidth; target._whyW = 0;
      if (!first) for (const li of target.children) li._fit = false;
    }
  });

  function renderShortlist(list = true) {
    $("shortCount").textContent = shortlist.length;
    $("shortCount").classList.toggle("on", shortlist.length > 0);
    const rows = shortlist.map((id) => byId.get(id)).filter(Boolean);
    if (list) patchList($("shortlist"), rows.map((r) => rowHtml(r, { off: !r.rank })));
    $("shortHint").textContent = rows.length
      ? rows.length < 2 ? "Star one more to compare." : `Compare up to 4 side by side${rows.length > 4 ? " (the first 4 are used)" : ""}.`
      : "Star neighborhoods in Matches or on the map to compare them side by side.";
    $("compareBtn").disabled = rows.length < 2;
    $("quickCompare").hidden = rows.length < 2;
    $("quickCompare").textContent = `Compare ${Math.min(rows.length, 4)}`;
    $("quickCompare").setAttribute("aria-label", `Compare ${Math.min(rows.length, 4)} shortlisted neighborhoods`);
  }

  function toggleStar(id) {
    shortlist = shortlist.includes(id) ? shortlist.filter((x) => x !== id) : [...shortlist, id];
    update();   // the map also marks shortlisted areas
  }

  function bindLists() {
    for (const el of [$("ranking"), $("shortlist")]) {
      listRO.observe(el);
      el.addEventListener("click", (e) => {
        const star = e.target.closest("[data-star]");
        if (star) return toggleStar(star.dataset.star);
        const row = e.target.closest("[data-select]");
        if (row) select(row.dataset.select, true);
      });
      el.addEventListener("pointerover", (e) => { const li = e.target.closest("li[data-id]"); setHover(li ? li.dataset.id : null, false); });
      el.addEventListener("pointerleave", () => setHover(null, false));
    }
    $("search").oninput = (e) => { state.query = e.target.value; renderRanking(); };
    $("compareBtn").onclick = openCompare;
    $("quickCompare").onclick = openCompare;
    $("sort").value = state.sort;
    $("sort").onchange = (e) => { state.sort = e.target.value; renderRanking(); persist(); };
  }

  // ---------- priorities ----------
  function weightsEqual(a, b) { return FACTORS.every((k) => (a[k] || 0) === (b?.[k] || 0)); }
  function buildPriorities() {
    $("presets").innerHTML = Object.keys(PRESETS).map((n) => `<button type="button" data-p="${esc(n)}" aria-pressed="false">${esc(n)}</button>`).join("");
    $("presets").onclick = (e) => {
      const n = e.target.closest("[data-p]")?.dataset.p;
      if (!n) return;
      const preset = PRESETS[n] || META.weights;
      for (const k of FACTORS) state.weights[k] = AVAILABLE.includes(k) ? preset[k] || 0 : state.weights[k] || 0;
      syncWeights(); update();
    };
    const groups = [...GROUPS, { ...OTHER, keys: FACTORS.filter((k) => !GROUP_OF[k]) }];
    $("weights").innerHTML = groups.map((g) => {
      const ks = g.keys.filter((k) => FACTORS.includes(k));
      if (!ks.length) return "";
      return `<div class="wgroup" style="--tc:${g.color[theme()]}"><h3><i class="gdot"></i>${esc(g.title)}</h3>` + ks.map((k) => {
        const f = META.factors[k];
        return `<div class="weight${f.available ? "" : " off"}">
          <label class="wl" for="w-${k}"><span class="wic">${icon(k)}</span>${esc(f.label)}${f.available ? "" : '<span class="na">· no data yet</span>'}</label>
          <span class="share" id="ws-${k}"></span>
          <span class="wh" id="wh-${k}">${esc(f.help)}</span>
          <input type="range" id="w-${k}" min="0" max="50" step="1" aria-describedby="wh-${k}" ${f.available ? "" : "disabled"}>
        </div>`;
      }).join("") + "</div>";
    }).join("");
    $("weights").oninput = (e) => {
      const k = e.target.id.replace("w-", "");
      if (!FACTORS.includes(k)) return;
      state.weights[k] = +e.target.value;
      syncShares(); schedule();
    };
    $("reset").onclick = () => { state.weights = { ...META.weights }; syncWeights(); update(); };
    syncWeights();
  }
  function syncShares() {
    const ws = FACTORS.map((k) => (AVAILABLE.includes(k) ? state.weights[k] || 0 : 0));
    const pct = pctShares(ws);
    for (const [i, k] of FACTORS.entries()) {
      const w = ws[i];
      const el = $("ws-" + k);
      el.textContent = w ? pct[i] + "%" : "off";
      el.classList.toggle("zero", !w);
      $("w-" + k).setAttribute("aria-valuetext", el.textContent);
    }
    $("weightsMsg").hidden = !noWeights();
    for (const b of $("presets").children) {
      const p = PRESETS[b.dataset.p] || META.weights;
      b.setAttribute("aria-pressed", String(weightsEqual(Object.fromEntries(AVAILABLE.map((k) => [k, state.weights[k] || 0])),
        Object.fromEntries(AVAILABLE.map((k) => [k, p[k] || 0])))));
    }
  }
  function syncWeights() {
    for (const k of FACTORS) $("w-" + k).value = state.weights[k] || 0;
    syncShares();
  }

  // ---------- legend ----------
  function buildColorBy() {
    $("colorBy").innerHTML = `<option value="total">Overall match</option>` +
      AVAILABLE.map((k) => `<option value="${k}">${esc(META.factors[k].label)}</option>`).join("");
    $("colorBy").value = state.colorBy;
    $("colorBy").onchange = (e) => { state.colorBy = e.target.value; update(); };
  }
  function renderLegend() {
    const ramp = RAMP[theme()];
    const lo = state.fixedScale ? [0, ...thresholds]
      : [Math.min(...results.filter((r) => r.visible).map(colorValue).filter((v) => v != null)), ...thresholds];
    const ticks = lo.map((v) => (Number.isFinite(v) ? Math.round(v) : "–"));
    const html = `<div class="swatches">${ramp.map((c) => `<span style="background:${c}"></span>`).join("")}</div>
      <div class="ticks">${ticks.map((t) => `<span>${t}+</span>`).join("")}</div>
      <div class="legend-foot"><span>${state.fixedScale ? "20-point bands" : "Fifths of your matches"}</span>
        <label title="Keep each shade's meaning fixed while you filter"><input type="checkbox" id="fixedScale" ${state.fixedScale ? "checked" : ""}>Fixed scale</label></div>`;
    if ($("legend")._html !== html) { $("legend").innerHTML = html; $("legend")._html = html; }
  }
  function renderLayersMenu() {
    const avail = CONTEXT.filter((c) => c.has());
    $("layersMenu").innerHTML = (avail.length ? `<div class="lm-h">Show on map</div>` +
      avail.map((c) => `<label class="lm-row"><input type="checkbox" data-layer="${c.id}" ${layerOn[c.id] ? "checked" : ""}>
        <span class="sw sw-${c.id}"></span>${esc(c.label)}${c.note ? `<small>${esc(c.note)}</small>` : ""}</label>`).join("") +
      `<div class="lm-sep"></div>` : "") + `<div class="lm-h">Key</div>
      <div class="lm-row key"><span class="key-ic"><span class="pin">1</span></span>Top 10 matches, by rank</div>
      <div class="lm-row key"><span class="key-ic"><span class="pin short">${STAR}</span></span>On your shortlist</div>
      <div class="lm-row key"><span class="key-ic"><span class="sw sw-short"></span></span>Shortlisted, outside your must-haves</div>
      <div class="lm-row key"><span class="key-ic"><span class="sw sw-out"></span></span>Outline only: outside your must-haves</div>
      <div class="lm-row key"><span class="key-ic"><span class="dest-mini">${BRIEFCASE}</span></span>Commute destination: drag to move</div>`;
  }
  function bindLegend() {
    $("layersMenu").addEventListener("change", (e) => {
      const id = e.target.dataset.layer;
      if (!id) return;
      layerOn[id] = e.target.checked;
      try { localStorage.setItem(LAYER_KEY, JSON.stringify(layerOn)); } catch (err) {}
      applyLayerVisibility();
    });
    $("legend").addEventListener("change", (e) => {
      if (e.target.id !== "fixedScale") return;
      state.fixedScale = e.target.checked;
      update();
    });
    closeOnOutside("layersBox");
  }

  // ---------- detail ----------
  function renderDetail() {
    const box = $("detail");
    const r = byId.get(state.selected);
    if (!r) { box.hidden = true; return; }
    const p = r.f.properties, m = p.metrics;
    const total = r.total == null ? null : Math.round(r.total);
    const starred = shortlist.includes(r.id);
    const rent = rentOf(p), mins = commuteOf(p);
    const nd = dests.filter((d) => d.on).length;
    const facts = [
      [`${bedLabel(state.bedrooms)} rent`, rent != null ? fmtRent(rent) : "—",
        rentIsEstimate(p) ? "Estimate from Census data" : "Median asking (listings)"],
      ["Commute", mins != null ? `${commuteIsEstimate(p) ? "~" : ""}${Math.round(mins)} min` : "—",
        `${nd > 1 ? `Avg to ${nd} destinations` : nd === 1 ? `To ${dests.find((d) => d.on).name}` : "No destination set"}${commuteIsEstimate(p) ? (p.commutes ? " · estimate, adjusted to routed times" : " · rough estimate") : ""}`],
      ["Apartment size", m.unit_sqft != null ? fmtInt(m.unit_sqft) + " ft²" : "—", "Avg per unit, gross"],
      ["Paths within 1 km", m.run_path_m != null ? (m.run_path_m / 1000).toFixed(1) + " km" : "—", "Footpaths, greenways, tracks"],
    ];
    const { pos, neg } = strengths(r);
    const summary = r.parts.length && (pos.length || neg.length)
      ? `<div class="tags">${pos.map((x) => tag(x.k)).join("")}${neg.map((x) => tag(x.k, { weak: true })).join("")}</div>` : "";
    const unweighted = AVAILABLE.filter((k) => !(state.weights[k] > 0));
    const pct = pctShares(r.parts.map((x) => x.share));
    r.parts.forEach((x, i) => { x.pct = pct[i]; });
    // Score composition: each group's points (weight share x score) stacked; they sum to the match score
    const byGroup = [...GROUPS, OTHER].map((g) => ({ g, pts: r.parts.filter((x) => groupOf(x.k) === g).reduce((a, x) => a + x.pts, 0) }))
      .filter((x) => x.pts > 0.05);
    const composition = byGroup.length ? `<div class="comp" role="img" aria-label="${esc(byGroup.map((x) => `${x.g.title} ${Math.round(x.pts)} points`).join(", "))}">
        ${byGroup.map((x) => `<span style="width:${x.pts}%;background:${x.g.color[theme()]}"></span>`).join("")}</div>
      <div class="comp-key">${byGroup.map((x) => `<span><i style="background:${x.g.color[theme()]}"></i>${esc(x.g.title)} <b>${Math.round(x.pts)}</b></span>`).join("")}</div>` : "";
    const contribRow = (k, score, share, muted) => `<div class="contrib${muted ? " muted" : ""}" title="${esc(META.factors[k].help)}" style="--tc:${groupColor(k)}">
      <span class="cl"><span class="wic">${icon(k)}</span>${esc(META.factors[k].label)}</span>
      <span class="bar"><i style="width:${score == null ? 0 : Math.max(score, 1.5)}%"></i></span>
      <span class="cv">${score == null ? "—" : Math.round(score)}</span>
      <span class="cw">${share == null ? "" : share + "%"}</span></div>`;
    const shown = { ...m, rent_est: rent, rent_source: rentSource(p), commute_min: mins,
      commute_method: !liveCommute ? m.commute_method : liveEstimated
        ? "estimate for your pins, adjusted to routed times" : m.commute_method };
    const rows = Object.entries(META.metrics).filter(([k]) => shown[k] != null)
      .map(([k, d]) => `<tr><td>${esc(k === "rent_est" ? `Median ${bedLabel(state.bedrooms)} rent` : d.label)}</td><td>${esc(fmtMetric(shown[k], d.fmt))}</td></tr>`).join("");

    const html = `
      <div class="d-head">
        <div class="d-title"><h2>${esc(p.name)}</h2>
          <div class="d-sub">${esc(p.borough)}${r.rank ? ` · #${r.rank} of ${results.filter((x) => x.rank).length} matches` : ""}</div></div>
        <button class="icon-btn star" type="button" data-star="${esc(r.id)}" aria-pressed="${starred}" aria-label="${starred ? "Remove from" : "Add to"} shortlist">${STAR}</button>
        <button class="icon-btn" type="button" id="closeDetail" aria-label="Close details">${CLOSE}</button>
      </div>
      <div class="d-score"><b>${total ?? "—"}</b><span>/ 100 match</span></div>
      ${r.reason ? `<div class="status">${ALERT}<span>${esc(r.reason)}</span></div>` : ""}
      <div class="facts-grid">${facts.map(([k, v, n]) => `<div class="fact"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="n">${esc(n)}</div></div>`).join("")}</div>
      ${hexNoteHtml(r)}
      <div class="d-section"><h3>Why it scores ${total ?? "—"}</h3>
        ${summary}
        ${composition}
        <div class="contrib contrib-head"><span>Factor</span><span>Score</span><span></span><span>Weight</span></div>
        ${r.parts.map((x) => contribRow(x.k, x.score, x.pct, false)).join("")}
        ${unweighted.length ? `<details class="more"><summary>Not weighted (${unweighted.length})</summary>
          ${unweighted.map((k) => contribRow(k, r.s[k], null, true)).join("")}</details>` : ""}
      </div>
      ${nearbyHtml(p, m)}
      ${airportsHtml(p)}
      <div class="d-section"><details class="more"><summary>All numbers</summary><table>${rows}</table></details></div>`;
    // update() runs on every slider tick: skip an identical rebuild, and when it does change, keep the
    // sections you opened (a rebuild used to snap them shut each tick). The scroll offset survives
    // innerHTML on its own; reading or setting scrollTop here would force a layout of the whole page.
    if (box._html === html && !box.hidden) return;
    const same = box._id === r.id, open = same ? [...box.querySelectorAll("details")].map((d) => d.open) : [];
    const hadFocus = same && box.contains(document.activeElement) ? document.activeElement.id : null;
    box.innerHTML = html;
    box._html = html; box._id = r.id;
    if (same) {
      box.querySelectorAll("details").forEach((d, i) => { if (open[i]) d.open = true; });
      if (hadFocus) $(hadFocus)?.focus({ preventScroll: true });
    }
    box.hidden = false;
    $("closeDetail").onclick = () => select(null);
    box.querySelector("[data-star]").onclick = () => toggleStar(r.id);
    box.querySelectorAll("[data-air]").forEach((b) => { b.onclick = () => pinAirport(b.dataset.air); });
    const hexBtn = box.querySelector("[data-hexes]");
    if (hexBtn) hexBtn.onclick = () => {
      layerOn.hexes = !layerOn.hexes;
      try { localStorage.setItem(LAYER_KEY, JSON.stringify(layerOn)); } catch (err) {}
      applyLayerVisibility(); renderLayersMenu(); renderDetail();
    };
  }
  const listJoin = (xs) => (xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1]);
  // The spread inside the area (lived-in hexes only) and a switch for the hex map
  function hexNoteHtml(r) {
    const rows = HX?.by_nta[r.id];
    if (!rows?.length) return "";
    const vals = rows.map((row) => evalHex(row, r)).filter((h) => !h.few && h.total != null).map((h) => h.total);
    const on = layerOn.hexes;
    const wide = HX.inherited.filter((k) => AVAILABLE.includes(k)).map((k) => META.factors[k].label);
    const spread = vals.length > 1
      ? `Varies from <b>${Math.round(Math.min(...vals))}</b> to <b>${Math.round(Math.max(...vals))}</b> across ${vals.length} spots ~260 m wide`
      : "Too small to split into spots";
    return `<div class="hex-note"><div>${spread}.${on ? " Hover the hexes on the map." : ""}
      ${wide.length ? `<span class="n">${esc(listJoin(wide))} ${wide.length > 1 ? "are" : "is"} the same everywhere in the area.</span>` : ""}</div>
      <button class="btn sm" type="button" data-hexes aria-pressed="${on}">${on ? "Hide" : "Show"} on map</button></div>`;
  }

  // Points inside a neighborhood's boundary (even-odd rule, so holes count as outside)
  function inGeom(pt, geom) {
    const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
    return polys.some((rings) => {
      let inside = false;
      for (const ring of rings)
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
          const [xi, yi] = ring[i], [xj, yj] = ring[j];
          if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) inside = !inside;
        }
      return inside;
    });
  }
  const NEARBY = new Map();
  function nearbyOf(id) {
    if (NEARBY.has(id)) return NEARBY.get(id);
    const f = BY_ID.get(id), [[x0, y0], [x1, y1]] = bbox([f]);
    const inside = (rows) => (rows || []).filter((r) => r[0] >= x0 && r[0] <= x1 && r[1] >= y0 && r[1] <= y1 && inGeom(r, f.geometry));
    const seen = new Set();
    const stations = inside(L.subway?.stations).filter((r) => { const k = r[2] + "|" + r[3]; return !seen.has(k) && seen.add(k); });
    const out = { stations, grocery: inside(L.grocery), gyms: inside(L.gyms), places: inside(L.places) };
    NEARBY.set(id, out);
    return out;
  }
  // MTA route bullets in the line's own color (yellow lines take black text, as on the signs)
  let ROUTE_COLOR = null;   // built on first use (the layer data is read further down)
  const routeColor = (r) => (ROUTE_COLOR ||= Object.fromEntries((L.subway?.lines?.features || []).map((f) => [f.properties.route, f.properties.color])))[r];
  function bullets(routes) {
    const list = String(routes || "").split(/[\s,]+/).filter(Boolean);
    const shown = list.filter((r) => !(r.endsWith("X") && list.includes(r.slice(0, -1))));
    if (!shown.length) return "";
    return `<span class="rbs" role="img" aria-label="${esc(shown.length > 1 ? "Lines " + shown.join(", ") : "Line " + shown[0])}">${shown.map((r) => {
      const c = routeColor(r) || routeColor(r.replace(/X$/, "")) || "#7C858C";
      return `<span class="rb" style="background:${c};color:${c.toUpperCase() === "#F6BC26" ? "#0b0b0b" : "#fff"}">${esc(r.replace(/X$/, ""))}</span>`;
    }).join("")}</span>`;
  }
  function nearbyHtml(p, m) {
    if (!p.residential || !(L.subway || L.grocery)) return "";
    const nb = nearbyOf(p.id), st = nb.stations.slice(0, 6), extra = nb.stations.length - st.length;
    const stations = st.length
      ? `<ul class="nearby">${st.map((r) => `<li>${bullets(r[3])}<span>${esc(r[2])}</span></li>`).join("")}</ul>` +
        (extra > 0 ? `<p class="nearby-note">and ${extra} more station${extra > 1 ? "s" : ""}</p>` : "")
      : `<p class="nearby-note">No subway station inside the boundary${m.station_dist_m != null ? `; the nearest is about ${fmtMetric(m.station_dist_m, "m")} from where people live` : ""}.</p>`;
    const g = nb.grocery.map((r) => r[2]);
    const grocery = `<p class="nearby-note">${g.length ? `${g.length} full-size grocery store${g.length > 1 ? "s" : ""}: ${esc([...new Set(g)].slice(0, 4).join(", "))}${new Set(g).size > 4 ? "…" : ""}` : "No full-size grocery store inside the boundary"}.</p>`;
    const gy = [...new Set(nb.gyms.map((r) => r[3] || r[2]))];
    const gyms = `<p class="nearby-note">${nb.gyms.length ? `${nb.gyms.length} full-size gym${nb.gyms.length > 1 ? "s" : ""}: ${esc(gy.slice(0, 4).join(", "))}${gy.length > 4 ? "…" : ""}` : "No full-size gym inside the boundary"}.</p>`;
    const places = nb.places.length ? `<p class="nearby-note">${nb.places.length} of your places: ${esc(nb.places.slice(0, 4).map((r) => r[2]).join(", "))}${nb.places.length > 4 ? "…" : ""}.</p>` : "";
    return `<div class="d-section"><h3>In this neighborhood</h3>${stations}${grocery}${gyms}${places}</div>`;
  }

  // ---------- airports: routes from the selected neighborhood ----------
  const AIR = window.STOOP_AIRPORTS || {};
  const AIR_NAMES = { jfk: "JFK", lga: "LaGuardia", ewr: "Newark" };
  const AIR_PLANE = `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON_PATHS.airports}"/></svg>`;
  const fmtMin = (v) => `${Math.round(v)} min`;
  // One line of legs: "Walk 5 min › [G] Nassau Av → Court Sq › [E] → Sutphin Blvd › AirTrain JFK ~12 min"
  function legsHtml(legs) {
    return legs.map((l) => {
      if (l.fixed) return `<span class="leg">${esc(l.label)} ~${Math.round(l.min)} min</span>`;
      if (l.m === "walk") return `<span class="leg">Walk ${Math.max(1, Math.round(l.min))} min</span>`;
      const badge = l.m === "subway" ? bullets(l.r) : `<span class="bus-chip">${esc(l.r || l.m)}</span>`;
      return `<span class="leg">${badge}${esc(l.from && l.to ? `${l.from} → ${l.to}` : l.to || l.from || "")}</span>`;
    }).join('<span class="leg-sep" aria-hidden="true">›</span>');
  }
  function airportCardHtml(code, fullName) {
    const r = byId.get(state.selected), card = r && AIR[r.id]?.[code];
    const head = `<div class="tn">${esc(fullName || AIR_NAMES[code])}</div>`;
    if (!r) return head + `<div class="ts">Select a neighborhood to see how to get here.</div>`;
    if (!card) return head + `<div class="ts">No route data for ${esc(r.f.properties.name)} yet.</div>`;
    const m = r.f.properties.metrics, sc = r.s.airports;
    return `<div class="tn">${esc(r.f.properties.name)} → ${esc(AIR_NAMES[code])}</div>
      ${card.min != null ? `<div class="air-row"><b>${fmtMin(card.min)}</b> by transit${card.via ? ` · via ${esc(card.via)}` : ""}</div>
      <div class="legs">${legsHtml(card.legs || [])}</div>` : ""}
      ${card.car != null ? `<div class="air-row"><b>${fmtMin(card.car)}</b> by car, no traffic (rush hour is slower)</div>` : ""}
      ${sc != null ? `<div class="ts air-score">Airports score ${Math.round(sc)}${m.airport_min != null ? ` · ${fmtMin(m.airport_min)} average to all three` : ""}</div>` : ""}
      <div class="ts">${state.airRoute?.pinned && state.airRoute.code === code ? "Click again to clear the route" : "Click to keep the route on the map"}</div>`;
  }
  function airportsHtml(p) {
    const cards = AIR[p.id];
    if (!p.residential || !cards) return "";
    const pinned = state.airRoute?.pinned ? state.airRoute.code : null;
    return `<div class="d-section" id="airSection"><h3>Getting to the airports</h3>
      ${["jfk", "lga", "ewr"].filter((c) => cards[c]).map((c) => {
        const k = cards[c];
        return `<button type="button" class="air-item${pinned === c ? " on" : ""}" data-air="${c}" aria-pressed="${pinned === c}">
          <span class="air-top"><span class="wic" style="--tc:${groupColor("airports")}">${AIR_PLANE}</span><b>${AIR_NAMES[c]}</b>
            <span class="air-times">${k.min != null ? `${fmtMin(k.min)} transit` : ""}${k.car != null ? ` · ${fmtMin(k.car)} car` : ""}</span></span>
          ${k.legs?.length ? `<span class="legs">${legsHtml(k.legs)}</span>` : ""}</button>`;
      }).join("")}
      <p class="nearby-note">From the middle of ${esc(p.name)}, weekday morning. Car times are without traffic. Click one to draw it on the map.</p></div>`;
  }
  function airRouteGeo() {
    const a = state.airRoute, r = byId.get(state.selected), card = a && r && AIR[r.id]?.[a.code];
    const feats = [];
    for (const l of card?.legs || []) {
      if (!l.g || l.g.length < 2) continue;
      const kind = l.fixed ? "fixed" : l.m === "walk" ? "walk" : "ride";
      const c = l.m === "subway" ? (routeColor(l.r) || routeColor(String(l.r).replace(/X$/, "")) || "#7C858C") : (theme() === "dark" ? "#c3c2b7" : "#52514e");
      feats.push({ type: "Feature", properties: { kind, c }, geometry: { type: "LineString", coordinates: l.g } });
    }
    return { type: "FeatureCollection", features: feats };
  }
  function renderAirRoute() { if (map && map.getSource("air-route")) map.getSource("air-route").setData(airRouteGeo()); }
  function hoverAirport(code) {
    if (state.airRoute?.pinned) return;   // a pinned route stays until cleared
    const next = code && state.selected ? { code, pinned: false } : null;
    if (JSON.stringify(next) === JSON.stringify(state.airRoute || null)) return;
    state.airRoute = next;
    renderAirRoute();
  }
  function pinAirport(code) {
    if (!code || (state.airRoute?.pinned && state.airRoute.code === code) || !state.selected) state.airRoute = null;
    else state.airRoute = { code, pinned: true };
    renderAirRoute();
    renderDetail();
    if (state.airRoute) $("airSection")?.scrollIntoView({ block: "nearest", behavior: motionMs(1) ? "smooth" : "auto" });
  }

  // ---------- compare ----------
  function openCompare() {
    const rows = shortlist.map((id) => byId.get(id)).filter(Boolean).slice(0, 4);
    if (rows.length < 2) return;
    const col = (fn) => rows.map(fn);
    const line = (label, vals, fmt, better, k = null) => {
      const nums = vals.map((v) => (typeof v === "number" ? v : null));
      const valid = nums.filter((v) => v != null);
      const best = valid.length > 1 ? (better === "low" ? Math.min(...valid) : Math.max(...valid)) : null;
      return `<tr><td>${k ? `<span class="wic" style="--tc:${groupColor(k)}">${icon(k)}</span>` : ""}${esc(label)}</td>${vals.map((v, i) =>
        `<td class="${best != null && nums[i] === best && better ? "best" : ""}">${esc(v == null ? "—" : fmt(v))}</td>`).join("")}</tr>`;
    };
    const round = (v) => String(Math.round(v));
    const html = `<div class="cmp">
      <div class="cmp-head"><h2 id="compareTitle">Compare shortlist</h2>
        <button class="icon-btn" type="button" id="closeCompare" aria-label="Close comparison">${CLOSE}</button></div>
      <table>
        <thead><tr><th></th>${rows.map((r) => `<th>${esc(r.f.properties.name)}<span class="boro">${esc(r.f.properties.borough)}</span></th>`).join("")}</tr></thead>
        <tbody>
          ${line("Match score", col((r) => r.total), round, "high")}
          ${line("Rank", col((r) => r.rank), (v) => "#" + v, "low")}
          <tr><td>Fits must-haves</td>${rows.map((r) => `<td>${r.visible ? "Yes" : esc(r.reason.split(":")[0].replace(/,.*/, ""))}</td>`).join("")}</tr>
          ${line(`${bedLabel(state.bedrooms)} rent`, col((r) => rentOf(r.f.properties)), (v) => fmtRent(v), "low")}
          ${line("Commute", col((r) => commuteOf(r.f.properties)), (v) => Math.round(v) + " min", "low")}
          ${line("Apartment size", col((r) => r.f.properties.metrics.unit_sqft), (v) => fmtInt(v) + " ft²", "high")}
          <tr class="group"><td colspan="${rows.length + 1}">Factor scores (0–100)</td></tr>
          ${AVAILABLE.map((k) => line(META.factors[k].label, col((r) => r.s[k]), round, "high", k)).join("")}
        </tbody>
      </table>
      <p class="note">▲ marks the best value in each row. Rents marked est. in the list are Census-based estimates. ${
        liveCommute && liveEstimated ? "Commutes include estimates for pins you moved or added." : ROUTED ? "Commutes are routed transit times." : "Commutes are rough straight-line estimates."}</p>
    </div>`;
    const dlg = $("compare"), opener = document.activeElement;
    dlg.innerHTML = html;
    dlg.hidden = false;
    $("closeCompare").focus();
    const close = () => { dlg.hidden = true; dlg.innerHTML = ""; (opener && opener.isConnected ? opener : $("compareBtn")).focus(); };
    closeCompare = close;
    $("closeCompare").onclick = close;
    dlg.onclick = (e) => { if (e.target === dlg) close(); };
    dlg.onkeydown = (e) => {   // keep Tab inside the dialog
      if (e.key !== "Tab") return;
      const f = [...dlg.querySelectorAll("button, [href], input, select, [tabindex]:not([tabindex='-1'])")];
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
    };
  }

  let closeCompare = () => {};
  const ROUTED = FEATS.some((f) => f.properties.metrics.commute_method === "r5py");

  // ---------- map ----------
  // Sources behind the scores and layers (OpenStreetMap is credited by the basemap's own attribution)
  const CREDITS = ["NYC Open Data", "U.S. Census Bureau", "MTA", "NYC Health", "Citi Bike"].join(" · ");
  let map = null, styleReady = false, pins = new Map(), lastPins = "";
  function initMap() {
    if (!window.maplibregl) {
      $("map").innerHTML = `<p style="padding:160px 24px;color:var(--ink-3);text-align:center">The map couldn't load (offline?). The ranking still works.</p>`;
      return;
    }
    map = new maplibregl.Map({
      container: "map", style: BASEMAP[theme()], bounds: bbox(FEATS),
      fitBoundsOptions: { padding: 30 },
      attributionControl: { compact: true, customAttribution: CREDITS },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // The grid can settle after the map is created (fonts, mobile toolbar): keep the canvas in sync.
    new ResizeObserver(() => map.resize()).observe($("mapwrap"));
    map.on("style.load", addLayers);
    map.on("styleimagemissing", (e) => {
      if (e.id.startsWith("rbs:") && !map.hasImage(e.id)) map.addImage(e.id, bulletsImage(e.id.slice(4)));
    });
    // One hover handler: a point (station, bus stop, grocery, your place) wins over the neighborhood under it.
    // Mice can fire mousemove several times per frame; only the latest position each frame is worth querying.
    let moveEv = null;
    map.on("mousemove", (e) => { if (!moveEv) requestAnimationFrame(onMove); moveEv = e; });
    function onMove() {
      const e = moveEv;
      moveEv = null;
      if (!e || !styleReady) return;
      const pts = map.queryRenderedFeatures(e.point, { layers: POINT_LAYERS.filter((id) => map.getLayer(id)) });
      setPointHover(pts[0] || null);
      if (pts.length) {
        setHover(null, true);
        map.getCanvas().style.cursor = state.addingDest ? "crosshair" : "default";
        const p = pts[0].properties;
        setLineHover(p.kind === "station" ? p.routes : "", p.kind === "bus" ? p.routes : "");
        hoverAirport(p.kind === "airport" ? p.key.toLowerCase() : null);
        return overlayTooltip(pts[0], e.point);
      }
      const lineLayers = ["subway-lines", "bus-lines"].filter((id) => map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none");
      const lines = lineLayers.length ? map.queryRenderedFeatures([[e.point.x - 4, e.point.y - 4], [e.point.x + 4, e.point.y + 4]], { layers: lineLayers }) : [];
      if (lines.length) {
        setHover(null, true);
        map.getCanvas().style.cursor = state.addingDest ? "crosshair" : "default";
        const uniq = (src) => [...new Map(lines.filter((f) => f.source === src).map((f) => [f.properties.route, f.properties])).values()];
        const sub = uniq("subway-lines"), bus = uniq("bus-lines");
        setLineHover(sub.map((x) => x.route).join(" "), bus.map((x) => x.route).join(" "));
        return lineTooltip(sub, bus, e.point);
      }
      setLineHover("", "");
      hoverAirport(null);
      const hx = hexAt(e.point);
      setHexHover(hx ? hx.id : null);
      if (hx) {
        setHover(null, true);
        map.getCanvas().style.cursor = state.addingDest ? "crosshair" : "default";
        return hexTooltip(hx, e.point, parkAt(e.point)?.properties);
      }
      const f = map.queryRenderedFeatures(e.point, { layers: ["fill"] })[0];
      if (f) {
        map.getCanvas().style.cursor = state.addingDest ? "crosshair" : "pointer";
        setHover(f.id, true);
        return showTooltip(f.id, e.point, parkAt(e.point)?.properties);
      }
      map.getCanvas().style.cursor = state.addingDest ? "crosshair" : "";
      setHover(null, true); $("tooltip").hidden = true;
    }
    map.getCanvas().addEventListener("mouseleave", () => { moveEv = null; setHover(null, true); setPointHover(null); setLineHover("", ""); setHexHover(null); $("tooltip").hidden = true; });
    // One click handler: either drop a destination (add mode) or select the neighborhood under the pointer
    map.on("click", (e) => {
      if (state.pickingArea) {
        Object.assign(state.area, { on: true, lon: +e.lngLat.lng.toFixed(5), lat: +e.lngLat.lat.toFixed(5) });
        setAreaPickMode(false); areaChanged();
        return;
      }
      if (state.addingDest) {
        setActive(-1);
        dests.push({ name: `Place ${dests.length + 1}`, lat: +e.lngLat.lat.toFixed(5), lon: +e.lngLat.lng.toFixed(5), weight: 1, on: true });
        setAddMode(false); destsChanged();
        return;
      }
      const box = [[e.point.x - 3, e.point.y - 3], [e.point.x + 3, e.point.y + 3]];
      const pt = map.queryRenderedFeatures(box, { layers: [...POINT_LAYERS, ...SEL_LAYERS.map((id) => id + "-sel")].filter((id) => map.getLayer(id)) })[0];
      if (pt) return pt.layer.id.startsWith("airports") ? pinAirport(pt.properties.key.toLowerCase()) : selectMarker(pt);
      // A park under the pointer is selected too; the neighborhood under it still opens below
      const park = parkAt(e.point);
      if (park) selectPark(park);
      else if (state.marker) clearMarker();
      if (hexAt(e.point)) return;   // inside the open neighborhood's hexes: keep it open (hexes overhang its edge)
      const f = map.getLayer("fill") && map.queryRenderedFeatures(e.point, { layers: ["fill"] })[0];
      if (f) select(f.id, false);
    });
    renderDestPins();
    renderAreaOnMap();
  }

  // ---------- commute destinations ----------
  const BRIEFCASE = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 8h16v11H4zM9 8V5.5h6V8M4 13h16"/></svg>';
  let destMarkers = [];
  function renderDestPins() {
    if (!map) return;
    destMarkers.forEach((mk) => mk.remove());
    destMarkers = dests.map((d) => {
      const el = document.createElement("div");
      el.className = "dest" + (d.on ? "" : " off");
      el.innerHTML = `<span class="dest-pin">${BRIEFCASE}</span><span class="dest-label">${esc(d.name)}</span><span class="dest-shadow"></span>`;
      el.title = d.on ? `${d.name}: your commute destination (drag to move)` : `${d.name}: click to commute here instead`;
      el.setAttribute("aria-label", `${d.on ? "Commute destination" : "Other destination"} ${d.name}`);
      const mk = new maplibregl.Marker({ element: markerRoot(el), draggable: true, anchor: "bottom" }).setLngLat([d.lon, d.lat]).addTo(map);
      let dragged = false;
      el.addEventListener("click", (e) => {
        e.stopPropagation();   // don't also select the neighborhood under the pin
        if (dragged) { dragged = false; return; }
        if (!d.on) { setActive(dests.indexOf(d)); destsChanged(); }
      });
      mk.on("dragstart", () => { dragged = true; el.classList.add("dragging"); });
      mk.on("dragend", () => {
        el.classList.remove("dragging");
        const ll = mk.getLngLat();
        d.lat = +ll.lat.toFixed(5); d.lon = +ll.lng.toFixed(5);
        destsChanged();
      });
      return mk;
    });
  }
  function renderDestMenu() {
    const cur = dests.find((d) => d.on);
    $("destSummary").textContent = cur ? cur.name : "None";
    $("destSummary").classList.toggle("edited", !sameAsConfig());
    $("destMenu").innerHTML = `
      <p class="dd-hint">Commute is scored to the one place you pick. Drag its pin to move it, or click a gray pin on the map to switch.</p>
      <div role="radiogroup" aria-label="Commute to">${dests.map((d, i) => `<div class="dest-row">
        <input type="radio" name="destPick" data-on="${i}" ${d.on ? "checked" : ""} aria-label="Commute to ${esc(d.name)}">
        <input type="text" data-name="${i}" value="${esc(d.name)}" aria-label="Destination name" autocomplete="off" spellcheck="false">
        <button class="icon-btn" type="button" data-del="${i}" aria-label="Remove ${esc(d.name)}">${CLOSE}</button></div>`).join("")}</div>
      <form class="addr" id="addrForm">
        <input type="text" id="addrInput" placeholder="Add an address, e.g. 3 World Trade Center…" aria-label="Add a destination by address" autocomplete="off">
        <button class="btn" type="submit">Add</button>
      </form>
      <p class="addr-msg" id="addrMsg" role="status"></p>
      <div class="dd-actions">
        <button class="btn" type="button" id="addDest">Drop a pin on the map</button>
        <button class="btn ghost" type="button" id="resetDests" ${sameAsConfig() ? "disabled" : ""}>Reset</button>
      </div>
      <p class="dd-hint">${!ROUTED ? "Estimated: walk + straight-line subway ride." : sameAsConfig() || !liveEstimated
        ? "Routed transit times, weekday mornings." : "Moved or new pins are estimated (marked ~), adjusted to the routed times."}</p>`;
  }
  function bindDestMenu() {
    const menu = $("destMenu");
    menu.addEventListener("change", (e) => {
      if (e.target.dataset.on != null) { setActive(+e.target.dataset.on); destsChanged(); }
      if (e.target.dataset.name != null) { dests[+e.target.dataset.name].name = e.target.value.trim() || "Place"; destsChanged(); }
    });
    menu.addEventListener("click", (e) => {
      const del = e.target.closest("[data-del]");
      if (del) {
        const i = +del.dataset.del, [gone] = dests.splice(i, 1);
        lastRemoved = { i, d: gone };
        if (gone.on && dests.length) setActive(0);   // always commute somewhere
        destsChanged();
        $("addrMsg").innerHTML = `Removed ${esc(gone.name)}. <button class="btn ghost sm" type="button" id="undoDest">Undo</button>`;
        $("undoDest").focus();
        return;
      }
      if (e.target.closest("#undoDest") && lastRemoved) {
        const at = Math.min(lastRemoved.i, dests.length);
        dests.splice(at, 0, lastRemoved.d);
        if (lastRemoved.d.on) setActive(at);
        lastRemoved = null; destsChanged();
        return;
      }
      if (e.target.closest("#addDest")) { $("destBox").open = false; setAddMode(true); }
      if (e.target.closest("#resetDests")) { dests = configDests(); destsChanged(); }
    });
    // Keyboard-friendly alternative to dragging: look an address up with OpenStreetMap Nominatim
    // (free, sent only when you press Add; bounded to NYC).
    menu.addEventListener("submit", async (e) => {
      e.preventDefault();
      const q = $("addrInput").value.trim();
      if (!q) return;
      $("addrMsg").textContent = "Looking it up…";
      try {
        const url = "https://nominatim.openstreetmap.org/search?" + new URLSearchParams({
          q: `${q}, New York, NY`, format: "json", limit: "1", viewbox: "-74.26,40.92,-73.70,40.49", bounded: "1" });
        const hit = (await (await fetch(url, { headers: { Accept: "application/json" } })).json())[0];
        if (!hit) { $("addrMsg").textContent = "Couldn't find that in NYC. Try adding the borough or a cross street."; return; }
        setActive(-1);
        dests.push({ name: q.length > 28 ? q.slice(0, 27) + "…" : q, lat: +(+hit.lat).toFixed(5), lon: +(+hit.lon).toFixed(5), weight: 1, on: true });
        destsChanged();
        $("addrMsg").textContent = `Added ${q}.`;
        $("addrInput").focus();
        if (map) map.easeTo({ center: [dests.at(-1).lon, dests.at(-1).lat], duration: motionMs(600) });
      } catch (err) {
        $("addrMsg").textContent = "The address lookup isn't reachable right now. Drop a pin on the map instead.";
      }
    });
    closeOnOutside("destBox");
  }
  let lastRemoved = null;
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const motionMs = (ms) => (reduceMotion.matches ? 0 : ms);
  function setAddMode(on) {
    state.addingDest = on;
    if (on) $("mapHint").textContent = "Click the map to drop a destination · Esc to cancel";
    $("mapHint").hidden = !on;
    if (map) map.getCanvas().style.cursor = on ? "crosshair" : "";
  }
  function destsChanged() {
    update();            // recomputes commutes first, so the menu's hint knows whether any pin is estimated
    renderDestMenu();
    renderDestPins();
  }

  function addLayers() {
    // Our fills and lines go above every basemap road/building and below the trailing block of labels.
    // (The first symbol layer isn't enough: the dark style draws water labels before its roads.)
    const base = map.getStyle().layers;
    let lastShape = -1;
    base.forEach((l, i) => { if (l.type !== "symbol") lastShape = i; });
    const firstLabel = base.slice(lastShape + 1).find((l) => l.type === "symbol")?.id;
    if (!map.getSource("hoods")) map.addSource("hoods", { type: "geojson", data: GEO, promoteId: "id" });
    const dark = theme() === "dark";
    map.addLayer({ id: "fill", type: "fill", source: "hoods", paint: {
      "fill-color": "rgba(0,0,0,0)",
      "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.92, 0.78],
    } }, firstLabel);
    addContextUnder(firstLabel, dark);
    addHexLayers(firstLabel, dark);
    map.addLayer({ id: "line", type: "line", source: "hoods", paint: {
      "line-color": ["case", ["boolean", ["feature-state", "on"], false], dark ? "#1a1a19" : "#ffffff", dark ? "#55544f" : "#b4b2aa"],
      "line-width": ["case", ["boolean", ["feature-state", "on"], false], 0.9, 0.6],
    } }, firstLabel);
    map.addLayer({ id: "short-line", type: "line", source: "hoods", paint: {
      "line-color": dark ? "#f0efec" : "#0b0b0b", "line-dasharray": [2, 1.5],
      "line-width": ["case", ["all", ["boolean", ["feature-state", "short"], false], ["!", ["boolean", ["feature-state", "on"], false]]], 1.6, 0],
    } }, firstLabel);
    if (!map.getSource("area")) map.addSource("area", { type: "geojson", data: areaGeo() });
    map.addLayer({ id: "area-mask", type: "fill", source: "area", filter: ["==", ["get", "part"], "mask"],
      paint: { "fill-color": dark ? "#000000" : "#0b0b0b", "fill-opacity": dark ? 0.35 : 0.12 } }, firstLabel);
    map.addLayer({ id: "area-edge", type: "line", source: "area", filter: ["==", ["get", "part"], "edge"],
      paint: { "line-color": dark ? "#f0efec" : "#0b0b0b", "line-width": 2, "line-dasharray": [3, 2] } }, firstLabel);
    map.addLayer({ id: "focus", type: "line", source: "hoods", paint: {
      "line-color": dark ? "#f0efec" : "#0b0b0b",
      "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 2.6,
        ["boolean", ["feature-state", "hover"], false], 1.6, 0],
    } });
    // The clicked park: a green outline above the neighborhood lines, below the markers
    if (map.getSource("parks")) map.addLayer({ id: "parks-sel", type: "line", source: "parks", filter: PARK_NONE,
      layout: { "line-join": "round" }, paint: { "line-color": dark ? "#8fe0a8" : "#1f6b3a", "line-width": 3 } });
    addContextPoints(dark);
    styleReady = true;
    applyLayerVisibility();
    pushMap(true);
  }

  // ---------- context layers (parks, subway, bus, grocery, your places) ----------
  // All drawn by MapLibre in the same WebGL frame as the map, so nothing lags or jiggles while panning.
  const L = window.STOOP_LAYERS || {};
  const HX = window.STOOP_HEXES || null;   // hex view data (stoop/hexes.py), or null
  const LAYER_KEY = "stoop.layers.v1";
  const CONTEXT = [
    { id: "parks", label: "Parks", has: () => L.parks?.features?.length, layers: ["parks-fill", "parks-line"] },
    { id: "subway", label: "Subway", has: () => L.subway?.lines?.features?.length,
      layers: ["subway-lines", "subway-lines-hover", "subway-stations", "subway-stations-hover", "subway-routes", "subway-names",
        "subway-stations-sel"] },
    { id: "busroutes", label: "Bus routes", note: "zoom in", has: () => L.bus_routes?.features?.length,
      layers: ["bus-lines-casing", "bus-lines", "bus-lines-hover", "bus-line-labels"] },
    { id: "bus", label: "Bus stops", note: "zoom in", has: () => L.bus?.length, layers: ["bus-stops", "bus-stops-hover", "bus-routes", "bus-stops-sel"] },
    { id: "grocery", label: "Full-size grocery", has: () => L.grocery?.length, layers: ["grocery", "grocery-hover", "grocery-sel", "grocery-sel-ring"] },
    { id: "gyms", label: "Full-size gyms", has: () => L.gyms?.length, layers: ["gyms", "gyms-hover", "gyms-sel", "gyms-sel-ring"] },
    { id: "places", label: "Your bars & restaurants", has: () => L.places?.length, layers: ["places", "places-hover", "places-sel", "places-sel-ring"] },
    { id: "airports", label: "Airports", has: () => L.airports?.length, layers: ["airports", "airports-hover", "airport-codes"] },
    { id: "runhex", label: "Runner hexes", has: () => L.runhex?.features?.length, layers: ["runhex-fill", "runhex-line"] },
    { id: "hexes", label: "Detail inside the selected area", has: () => HX, layers: ["hex-fill", "hex-line"] },
  ];
  let layerOn = Object.fromEntries(CONTEXT.map((c) => [c.id, true]));
  try { Object.assign(layerOn, JSON.parse(localStorage.getItem(LAYER_KEY) || "{}")); } catch (e) {}
  // point rows are [lon, lat, name, extra, borough] (borough added by layers.tag_boroughs)
  const pointsFC = (rows, props) => ({ type: "FeatureCollection",
    features: (rows || []).map((r) => ({ type: "Feature", geometry: { type: "Point", coordinates: [r[0], r[1]] },
      properties: { ...props(r), boro: r[4] || "" } })) });
  // Borough filter on the map: context layers only show what's in the boroughs you've kept.
  // Data without a borough tag (an older layers.js) always shows.
  const boroF = () => ["any", ["!", ["has", "boro"]], ["==", ["get", "boro"], ""], ["in", ["get", "boro"], ["literal", [...state.boroughs]]]];
  const withBoro = (f) => (f ? ["all", f, boroF()] : boroF());
  const inBoros = (r) => !r[4] || state.boroughs.has(r[4]);
  const BORO_LAYERS = ["parks-fill", "parks-line", "subway-lines", "subway-lines-hover", "bus-lines-casing", "bus-lines",
    "bus-lines-hover", "bus-line-labels",
    "subway-stations", "subway-routes", "subway-names", "bus-stops", "bus-routes", "grocery", "gyms", "places"];
  let boroKey = "";
  function applyBoroughFilter(force) {
    if (!map || !styleReady) return;
    const k = [...state.boroughs].sort().join("|");
    if (!force && k === boroKey) return;
    boroKey = k;
    for (const id of BORO_LAYERS) if (map.getLayer(id)) map.setFilter(id, withBoro(null));
    applyMarkerSel();   // re-filters the selection twins and route highlights
  }
  const MARKER = {
    grocery: { light: "#008300", dark: "#008300" },
    gyms: { light: "#6250d6", dark: "#9085e9" },
    places: { light: "#d55181", dark: "#e87ba4" },
  };
  const markerColor = (id) => MARKER[id][theme()];
  const PARK = { light: { fill: "#7cc58f", line: "#4f9e66", op: 0.6 }, dark: { fill: "#2f7a4c", line: "#3f9a63", op: 0.55 } };

  function addContextUnder(beforeId, dark) {
    const pk = PARK[dark ? "dark" : "light"];
    if (L.parks?.features?.length) {
      L.parks.features.forEach((f, i) => { f.properties.pid = i; });   // what a park selection filters on
      map.addSource("parks", { type: "geojson", data: L.parks });
      map.addLayer({ id: "parks-fill", type: "fill", source: "parks", paint: { "fill-color": pk.fill, "fill-opacity": pk.op } }, beforeId);
      map.addLayer({ id: "parks-line", type: "line", source: "parks", minzoom: 12,
        paint: { "line-color": pk.line, "line-width": 0.7 } }, beforeId);
    }
    // Runner hexes from your runner-traffic data (inputs/runner_hexes.json): orange, stronger = busier
    if (L.runhex?.features?.length) {
      map.addSource("runhex", { type: "geojson", data: L.runhex });
      map.addLayer({ id: "runhex-fill", type: "fill", source: "runhex",
        paint: { "fill-color": "#eb6834", "fill-opacity": ["interpolate", ["linear"], ["get", "v"], 0, 0.07, 1, 0.2, 5, 0.7] } }, beforeId);
      map.addLayer({ id: "runhex-line", type: "line", source: "runhex",
        paint: { "line-color": "#eb6834", "line-width": 1, "line-opacity": 0.7 } }, beforeId);
    }
    const round = { "line-cap": "round", "line-join": "round" };
    // Route highlights use feature-state, never setFilter: a filter change re-tiles the whole source in the
    // worker, and on a fast mouse those reloads queue up and replay as a trail after the pointer stops.
    // promoteId "route" gives every segment of a route (they're split by borough) the same state.
    const hlOpacity = ["case", ["boolean", ["feature-state", "hl"], false], 1, 0];
    // Bus routes: one neutral ink with a surface casing, so they read as buses and never as a subway color
    // (the MTA's own bus route colors reuse the subway reds and greens). Select Bus Service a little wider.
    if (L.bus_routes?.features?.length) {
      const sbs = (a, b) => ["case", ["==", ["get", "kind"], "sbs"], a, b];
      map.addSource("bus-lines", { type: "geojson", data: L.bus_routes, promoteId: "route" });
      map.addLayer({ id: "bus-lines-casing", type: "line", source: "bus-lines", minzoom: 12.5, layout: round,
        paint: { "line-color": dark ? "#1a1a19" : "#ffffff", "line-opacity": 0.85,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12.5, sbs(3.2, 2.6), 15, sbs(4.8, 4), 17, sbs(6.5, 5.5)] } }, beforeId);
      map.addLayer({ id: "bus-lines", type: "line", source: "bus-lines", minzoom: 12.5, layout: round,
        paint: { "line-color": dark ? "#c3c2b7" : "#52514e", "line-opacity": 0.9,
          "line-width": ["interpolate", ["linear"], ["zoom"], 12.5, sbs(1.6, 0.9), 15, sbs(2.6, 1.6), 17, sbs(3.6, 2.4)] } }, beforeId);
    }
    if (L.subway?.lines?.features?.length) {
      map.addSource("subway-lines", { type: "geojson", data: L.subway.lines, promoteId: "route" });
      map.addLayer({ id: "subway-lines", type: "line", source: "subway-lines", layout: round,
        paint: { "line-color": ["get", "color"], "line-opacity": 0.9,
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.2, 13, 2.2, 16, 4] } }, beforeId);
      map.addLayer({ id: "subway-lines-hover", type: "line", source: "subway-lines", layout: round,
        paint: { "line-color": ["get", "color"], "line-opacity": hlOpacity,
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, 3.5, 13, 5.5, 16, 8] } }, beforeId);
    }
    if (L.bus_routes?.features?.length)
      map.addLayer({ id: "bus-lines-hover", type: "line", source: "bus-lines", layout: round,
        paint: { "line-color": dark ? "#f0efec" : "#0b0b0b", "line-opacity": hlOpacity,
          "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 15, 4.5, 17, 6] } }, beforeId);
  }

  // Icon badge: colored disc, white ring, white factor icon (same icon as the factor tag)
  function badgeImage(iconKey, color, px = 28) {
    const r = window.devicePixelRatio > 1 ? 2 : 1, s = px * r, c = document.createElement("canvas");
    c.width = c.height = s;
    const g = c.getContext("2d");
    g.beginPath(); g.arc(s / 2, s / 2, s / 2 - r, 0, Math.PI * 2);
    g.fillStyle = color; g.fill(); g.lineWidth = 2 * r; g.strokeStyle = "#ffffff"; g.stroke();
    g.save(); g.translate(s * 0.22, s * 0.22); g.scale((s * 0.56) / 24, (s * 0.56) / 24);
    g.strokeStyle = "#ffffff"; g.lineWidth = 2.4; g.lineCap = "round"; g.lineJoin = "round";
    g.stroke(new Path2D(ICON_PATHS[iconKey])); g.restore();
    return { width: s, height: s, data: g.getImageData(0, 0, s, s).data, pixelRatio: r };
  }

  // A row of MTA route bullets as one map image ("rbs:A C E"), drawn when the map first asks for it
  function bulletsImage(routes) {
    const list = routes.split(/\s+/).filter(Boolean).filter((r, _, a) => !(r.endsWith("X") && a.includes(r.slice(0, -1))));
    const r = window.devicePixelRatio > 1 ? 2 : 1, d = 16 * r, gap = 2 * r, pad = 1 * r;
    const c = document.createElement("canvas");
    c.width = Math.max(1, list.length * (d + gap) - gap + pad * 2); c.height = d + pad * 2;
    const g = c.getContext("2d");
    list.forEach((rt, i) => {
      const color = routeColor(rt) || routeColor(rt.replace(/X$/, "")) || "#7C858C";
      const x = pad + i * (d + gap) + d / 2, y = pad + d / 2;
      g.beginPath(); g.arc(x, y, d / 2, 0, Math.PI * 2); g.fillStyle = color; g.fill();
      g.lineWidth = 1.2 * r; g.strokeStyle = "#ffffff"; g.stroke();
      g.fillStyle = color.toUpperCase() === "#F6BC26" ? "#0b0b0b" : "#ffffff";
      g.font = `700 ${10 * r}px system-ui, "Segoe UI", sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(rt.replace(/X$/, "").slice(0, 3), x, y + 0.5 * r);
    });
    return { width: c.width, height: c.height, data: g.getImageData(0, 0, c.width, c.height).data, pixelRatio: r };
  }
  // A larger copy of a point layer where only the hovered feature is opaque. icon-size is a layout property,
  // so it can't follow feature-state, but opacity can. (A filter on the twin would also work, but every
  // filter change re-tiles the source in the worker: with 13k bus stops, hovering queued up a lagging trail.)
  function addHoverTwin(layer) {
    const twin = JSON.parse(JSON.stringify(layer));
    twin.id = layer.id + "-hover";
    twin.paint ||= {};
    const shown = ["case", ["boolean", ["feature-state", "hover"], false], 1, 0];
    if (layer.type === "circle") {
      twin.paint["circle-radius"] = ["interpolate", ["linear"], ["zoom"], 11, 4, 14, 7, 16, 9];
      twin.paint["circle-stroke-width"] = 2;
      twin.paint["circle-opacity"] = shown; twin.paint["circle-stroke-opacity"] = shown;
    } else {
      twin.layout["icon-size"] = ["interpolate", ["linear"], ["zoom"], 10, 0.8, 13, 1.1, 16, 1.35];
      twin.paint["icon-opacity"] = shown;
    }
    map.addLayer(twin);
  }
  const TEXT_FONT = ["Noto Sans Regular"];   // a font stack OpenFreeMap serves for both basemaps

  function addContextPoints(dark) {
    const ink = dark ? "#f0efec" : "#0b0b0b", surf = dark ? "#1a1a19" : "#ffffff", ink2 = dark ? "#c3c2b7" : "#52514e";
    const halo = dark ? "rgba(26,26,25,0.9)" : "rgba(255,255,255,0.9)";
    if (L.bus_routes?.features?.length)
      map.addLayer({ id: "bus-line-labels", type: "symbol", source: "bus-lines", minzoom: 14,
        layout: { "symbol-placement": "line", "symbol-spacing": 320, "text-field": ["get", "route"], "text-font": TEXT_FONT,
          "text-size": 11, "text-keep-upright": true, "text-optional": true },
        paint: { "text-color": ink2, "text-halo-color": halo, "text-halo-width": 1.6 } });
    if (L.bus?.length) {
      map.addSource("bus-stops", { type: "geojson", generateId: true, data: pointsFC(L.bus, (r) => ({ kind: "bus", name: r[2], routes: r[3], key: r[2] })) });
      if (!map.hasImage("badge-bus")) map.addImage("badge-bus", badgeImage("bus", dark ? "#6f6d68" : "#52514e"));
      const bus = { id: "bus-stops", type: "symbol", source: "bus-stops", minzoom: 14,
        layout: { "icon-image": "badge-bus", "icon-allow-overlap": true, "icon-ignore-placement": true,
          "icon-size": ["interpolate", ["linear"], ["zoom"], 14, 0.5, 17, 0.8] } };
      map.addLayer(bus);
      addHoverTwin(bus);
      // which buses stop here, next to the stop once you're zoomed in close
      map.addLayer({ id: "bus-routes", type: "symbol", source: "bus-stops", minzoom: 15.5,
        layout: { "text-field": ["get", "routes"], "text-font": TEXT_FONT, "text-size": 11, "text-anchor": "left",
          "text-offset": [0.9, 0], "text-max-width": 8, "text-optional": true },
        paint: { "text-color": ink2, "text-halo-color": halo, "text-halo-width": 1.4 } });
    }
    if (L.subway?.stations?.length) {
      map.addSource("subway-stations", { type: "geojson", generateId: true,
        data: pointsFC(L.subway.stations, (r) => ({ kind: "station", name: r[2], routes: r[3], key: r[2] + "|" + r[3] })) });
      const st = { id: "subway-stations", type: "circle", source: "subway-stations", minzoom: 11,
        paint: { "circle-color": surf, "circle-stroke-color": ink, "circle-stroke-width": 1.4,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 2.2, 14, 4.5, 16, 6] } };
      map.addLayer(st);
      // the lines that stop here as route bullets beside the station, and its name further in
      map.addLayer({ id: "subway-routes", type: "symbol", source: "subway-stations", minzoom: 12.5,
        layout: { "icon-image": ["concat", "rbs:", ["get", "routes"]], "icon-anchor": "left",
          "icon-offset": ["interpolate", ["linear"], ["zoom"], 12.5, ["literal", [5, 0]], 16, ["literal", [9, 0]]],
          "icon-size": ["interpolate", ["linear"], ["zoom"], 12.5, 0.8, 15, 1] } });
      map.addLayer({ id: "subway-names", type: "symbol", source: "subway-stations", minzoom: 14.5,
        layout: { "text-field": ["get", "name"], "text-font": TEXT_FONT, "text-size": 11.5, "text-anchor": "right",
          "text-offset": [-0.8, 0], "text-max-width": 9, "text-optional": true },
        paint: { "text-color": ink, "text-halo-color": halo, "text-halo-width": 1.4 } });
      addHoverTwin(st);
    }
    const badges = [
      ["grocery", L.grocery, "errands", "Full-size grocery store", 11],
      ["gyms", L.gyms, "gym", "Full-size gym", 11],
      ["places", L.places, "favorites", "On your list", 9],
    ];
    for (const [id, rows, iconKey, kind, minzoom] of badges) {
      if (!rows?.length) continue;
      if (!map.hasImage("badge-" + id)) map.addImage("badge-" + id, badgeImage(iconKey, markerColor(id)));
      // key: the brand for chains (every Whole Foods, every Equinox), otherwise the name (all branches of a place)
      map.addSource(id, { type: "geojson", generateId: true, data: pointsFC(rows, (r) => ({ kind, name: r[2], key: r[3] || r[2] })) });
      const lyr = { id, type: "symbol", source: id, minzoom,
        layout: { "icon-image": "badge-" + id, "icon-allow-overlap": true, "icon-ignore-placement": true,
          "icon-size": ["interpolate", ["linear"], ["zoom"], 10, 0.55, 13, 0.8, 16, 1] } };
      map.addLayer(lyr);
      addHoverTwin(lyr);
    }
    // Route from the selected neighborhood to an airport: casing, transit legs in their line color,
    // walking dotted, the fixed AirTrain / NJ Transit leg dashed
    map.addSource("air-route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "air-route-casing", type: "line", source: "air-route", layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": surf, "line-width": 8, "line-opacity": 0.9 } });
    map.addLayer({ id: "air-route-ride", type: "line", source: "air-route", filter: ["==", ["get", "kind"], "ride"],
      layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["get", "c"], "line-width": 5 } });
    map.addLayer({ id: "air-route-walk", type: "line", source: "air-route", filter: ["==", ["get", "kind"], "walk"],
      layout: { "line-cap": "round" }, paint: { "line-color": ink, "line-width": 3, "line-dasharray": [0.1, 2] } });
    map.addLayer({ id: "air-route-fixed", type: "line", source: "air-route", filter: ["==", ["get", "kind"], "fixed"],
      paint: { "line-color": ink, "line-width": 3, "line-dasharray": [2, 1.5] } });
    renderAirRoute();
    // Airports: a larger neutral badge (plane icon) with its code, visible at every zoom
    if (L.airports?.length) {
      if (!map.hasImage("badge-airports")) map.addImage("badge-airports", badgeImage("airports", dark ? "#6f6d68" : "#3d3c39", 34));
      map.addSource("airports", { type: "geojson", generateId: true,
        data: pointsFC(L.airports, (r) => ({ kind: "airport", name: r[2], key: r[3] })) });
      const ap = { id: "airports", type: "symbol", source: "airports",
        layout: { "icon-image": "badge-airports", "icon-allow-overlap": true, "icon-ignore-placement": true,
          "icon-size": ["interpolate", ["linear"], ["zoom"], 9, 0.8, 13, 1] } };
      map.addLayer(ap);
      addHoverTwin(ap);
      map.addLayer({ id: "airport-codes", type: "symbol", source: "airports",
        layout: { "text-field": ["get", "key"], "text-font": ["Noto Sans Bold"], "text-size": 12, "text-anchor": "top",
          "text-offset": [0, 1.3], "text-allow-overlap": true },
        paint: { "text-color": ink, "text-halo-color": halo, "text-halo-width": 1.6 } });
    }
    // Selected markers (everything of the clicked kind) sit above all other points, at every zoom
    for (const id of ["grocery", "gyms", "places", "bus-stops"]) {
      if (!map.getLayer(id)) continue;
      map.addLayer({ id: id + "-sel-ring", type: "circle", source: id, filter: SEL_NONE,
        paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 9, 13, 13, 16, 17], "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": ink, "circle-stroke-width": 2.5 } });
      const twin = JSON.parse(JSON.stringify(map.getStyle().layers.find((l) => l.id === id)));
      Object.assign(twin, { id: id + "-sel", filter: SEL_NONE });
      delete twin.minzoom;
      twin.layout["icon-size"] = ["interpolate", ["linear"], ["zoom"], 9, 0.7, 13, 0.95, 16, 1.15];
      map.addLayer(twin);
    }
    if (map.getLayer("subway-stations"))
      map.addLayer({ id: "subway-stations-sel", type: "circle", source: "subway-stations", filter: SEL_NONE,
        paint: { "circle-color": surf, "circle-stroke-color": ink, "circle-stroke-width": 3,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 4, 13, 7, 16, 10] } });
    pointHover = null; lineHoverKey = ""; lineHl = { "subway-lines": new Set(), "bus-lines": new Set() };   // new sources, no state
    applyMarkerSel();
  }

  // Hovered map point: feature-state makes its twin layer's enlarged copy opaque
  let pointHover = null;
  function setPointHover(f) {
    const next = f && f.id != null ? { source: f.source, id: f.id } : null;
    if (next?.source === pointHover?.source && next?.id === pointHover?.id) return;
    if (pointHover && map.getSource(pointHover.source)) map.setFeatureState(pointHover, { hover: false });
    pointHover = next;
    if (next) map.setFeatureState(next, { hover: true });
  }

  function applyLayerVisibility() {
    if (!map) return;
    for (const c of CONTEXT) for (const id of c.layers)
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", layerOn[c.id] ? "visible" : "none");
  }
  const POINT_LAYERS = ["airports", "places", "gyms", "grocery", "subway-stations", "bus-stops"];
  function overlayTooltip(f, pt) {
    const p = f.properties, tip = $("tooltip");
    tip.classList.toggle("wide", p.kind === "airport");
    if (p.kind === "airport") { tip.innerHTML = airportCardHtml(p.key.toLowerCase(), p.name); return placeTooltip(pt); }
    const sub = p.kind === "station" ? "Subway station" : p.kind === "bus" ? `Bus stop${p.routes ? " · " + p.routes : ""}`
      : p.kind === "airport" ? `Airport (${p.key}) · counted in the Airports score` : p.kind;
    tip.innerHTML = `<div class="tn">${esc(p.name)}</div><div class="ts">${esc(sub)}</div>${p.kind === "station" ? bullets(p.routes) : ""}`;
    placeTooltip(pt);
  }
  // Highlight whole routes: the lines under the pointer, or every line serving the hovered stop/station
  // Only the routes whose state changed are touched (feature-state is main-thread only, no re-tiling).
  let lineHoverKey = "", lineHl = { "subway-lines": new Set(), "bus-lines": new Set() };
  function setLineHover(subwayRoutes, busRoutes) {
    subwayRoutes = [subwayRoutes, selLines.sub].join(" ").trim(); busRoutes = [busRoutes, selLines.bus].join(" ").trim();
    const key = subwayRoutes + "|" + busRoutes;
    if (key === lineHoverKey || !map) return;
    lineHoverKey = key;
    const sub = String(subwayRoutes).split(/\s+/).filter(Boolean);
    const next = { "subway-lines": new Set([...sub, ...sub.map((r) => r + "X")]),
      "bus-lines": new Set(String(busRoutes).split(/\s+/).filter(Boolean)) };
    for (const source of Object.keys(next)) {
      if (!map.getSource(source)) continue;
      for (const id of lineHl[source]) if (!next[source].has(id)) map.setFeatureState({ source, id }, { hl: false });
      for (const id of next[source]) if (!lineHl[source].has(id)) map.setFeatureState({ source, id }, { hl: true });
    }
    lineHl = next;
  }
  // ---------- hex view: how scores vary inside the selected neighborhood ----------
  // Each hex row is [q, r, pop, ...factor scores, commute_min, ...minutes per configured destination, station_pct].
  // Factors in HX.inherited are neighborhood-wide: a hex shows its neighborhood's (live) score for them.
  const HXI = HX ? { nf: HX.factors.length, cm: 3 + HX.factors.length, d0: 4 + HX.factors.length,
    sp: 4 + HX.factors.length + HX.dests.length } : null;
  const hexCenter = (q, r) => [HX.size_m * Math.sqrt(3) * (q + r / 2), HX.size_m * 1.5 * r];
  function hexRing(q, r) {
    const [cx, cy] = hexCenter(q, r), ring = [];
    for (let i = 0; i <= 6; i++) {
      const a = ((60 * (i % 6) - 30) * Math.PI) / 180;
      ring.push([(cx + HX.size_m * Math.cos(a)) / HX.kx, (cy + HX.size_m * Math.sin(a)) / HX.ky]);
    }
    return ring;
  }
  // Commute minutes from one hex: routed for configured destinations, else the neighborhood's estimate approach
  // from the hex center (nearest station + the neighborhood's routed-vs-estimate offset).
  function hexCommute(row, nta) {
    if (!liveTargets) return row[HXI.cm];
    let total = 0;
    for (const t of liveTargets.targets) {
      let m = t.cfg >= 0 ? row[HXI.d0 + t.cfg] : null;
      if (m == null) {
        if (!t.t || !STATIONS.length) return null;
        const [cx, cy] = hexCenter(row[0], row[1]), xy = [cx, cy], [st, w] = nearestStation(xy);
        const est = estimateTo({ xy, st, walk: w }, t.t), walkOnly = (dist(xy, t.t.xy) * CM.detour) / CM.walk_m_per_min;
        m = Math.max(1, Math.min(est + (OFFSET.get(nta) || 0), walkOnly));
      }
      total += m * t.wt;
    }
    return total / liveTargets.wsum;
  }
  function evalHex(row, r) {
    const s = { ...r.s };   // neighborhood-wide factors (live rent included) come from the neighborhood
    HX.factors.forEach((k, i) => { s[k] = row[3 + i]; });
    const mins = hexCommute(row, r.id);
    if (liveTargets) {
      const parts = [[mins == null ? null : commuteCurve(mins), CM.weights.commute_min], [row[HXI.sp], CM.weights.station_dist_m]]
        .filter(([v]) => v != null);
      const w = parts.reduce((a, [, x]) => a + x, 0);
      s.commute = w ? parts.reduce((a, [v, x]) => a + v * x, 0) / w : null;
    }
    let num = 0, den = 0;
    for (const k of FACTORS) {
      const w = state.weights[k] || 0;
      if (w > 0 && s[k] != null) { num += s[k] * w; den += w; }
    }
    return { s, total: den ? num / den : null, mins, pop: row[2], few: row[2] < HX.few_people };
  }
  let hexShown = null;
  function hexData() {
    const r = state.selected && byId.get(state.selected);
    const rows = r && HX ? HX.by_nta[r.id] || [] : [];
    return { type: "FeatureCollection", features: rows.map((row, i) => {
      const h = evalHex(row, r), v = state.colorBy === "total" ? h.total : h.s[state.colorBy];
      return { type: "Feature", id: i, geometry: { type: "Polygon", coordinates: [hexRing(row[0], row[1])] },
        properties: { i, v: v == null ? -1 : v, few: h.few } };
    }) };
  }
  function renderHexes() {
    if (!map || !styleReady || !map.getSource("hexes")) return;
    map.getSource("hexes").setData(hexData());
    hexShown = state.selected;
    map.setPaintProperty("hex-fill", "fill-color", hexFillColor());
  }
  function hexFillColor() {
    const ramp = RAMP[theme()], v = ["get", "v"];
    return ["case", [">=", v, 0],
      ["step", v, ramp[0], thresholds[0], ramp[1], thresholds[1], ramp[2], thresholds[2], ramp[3], thresholds[3], ramp[4]],
      theme() === "dark" ? "rgba(240,239,236,0.10)" : "rgba(11,11,11,0.06)"];
  }
  function addHexLayers(beforeId, dark) {
    if (!HX) return;
    if (!map.getSource("hexes")) map.addSource("hexes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "hex-fill", type: "fill", source: "hexes", paint: { "fill-color": "rgba(0,0,0,0)",
      "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 1, ["get", "few"], 0.3, 0.74] } }, beforeId);
    map.addLayer({ id: "hex-line", type: "line", source: "hexes", paint: {
      "line-color": ["case", ["boolean", ["feature-state", "hover"], false], dark ? "#f0efec" : "#0b0b0b", dark ? "#1a1a19" : "#ffffff"],
      "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2, 0.6],
      "line-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 1, 0.7] } }, beforeId);
  }
  let hexHover = null;
  function setHexHover(id) {
    if (id === hexHover || !map.getSource("hexes")) return;
    if (hexHover != null) map.setFeatureState({ source: "hexes", id: hexHover }, { hover: false });
    hexHover = id;
    if (id != null) map.setFeatureState({ source: "hexes", id }, { hover: true });
  }
  const hexAt = (point) => (map.getLayer("hex-fill") && map.getLayoutProperty("hex-fill", "visibility") !== "none"
    ? map.queryRenderedFeatures(point, { layers: ["hex-fill"] })[0] || null : null);
  function hexTooltip(f, pt, park) {
    const r = byId.get(hexShown), row = r && HX.by_nta[r.id]?.[f.properties.i];
    if (!row) return;
    const h = evalHex(row, r), tip = $("tooltip");
    tip.classList.remove("wide");
    const label = state.colorBy === "total" ? "match here" : META.factors[state.colorBy].label;
    const v = state.colorBy === "total" ? h.total : h.s[state.colorBy];
    const nv = state.colorBy === "total" ? r.total : r.s[state.colorBy];
    // the factors you weight that differ most from the neighborhood as a whole
    const diffs = FACTORS.filter((k) => (state.weights[k] || 0) > 0 && h.s[k] != null && r.s[k] != null && !HX.inherited.includes(k))
      .map((k) => ({ k, d: h.s[k] - r.s[k] })).filter((x) => Math.abs(x.d) >= 5)
      .sort((a, b) => Math.abs(b.d) * (state.weights[b.k] || 0) - Math.abs(a.d) * (state.weights[a.k] || 0)).slice(0, 4);
    const rows = diffs.map((x) => `<div class="hx-row"><span>${esc(META.factors[x.k].label)}</span><b>${Math.round(h.s[x.k])}</b>
      <span class="hx-d ${x.d > 0 ? "up" : "down"}">${x.d > 0 ? "+" : "−"}${Math.round(Math.abs(x.d))}</span></div>`).join("");
    tip.innerHTML = `<div class="tn">${esc(r.f.properties.name)} · this spot</div>
      <div><span class="tv">${v == null ? "—" : Math.round(v)}</span> <span class="ts">${esc(label)}${nv != null ? ` · area ${Math.round(nv)}` : ""}</span></div>
      ${h.mins != null ? `<div class="tr">${liveEstimated ? "~" : ""}${Math.round(h.mins)} min commute</div>` : ""}
      ${rows ? `<div class="hx-rows"><div class="ts">vs the area as a whole</div>${rows}</div>` : ""}
      ${h.few ? `<div class="ts">Few residents here (park, industry or rail)</div>` : ""}
      ${park ? `<div class="tpark">${esc(parkText(park))}</div>` : ""}`;
    placeTooltip(pt);
  }

  // ---------- marker selection: click a marker to light up every marker of the same kind ----------
  const SEL_NONE = ["==", ["get", "key"], "\u0000none"];
  const SEL_LAYERS = ["grocery", "gyms", "places", "bus-stops", "subway-stations"];
  let selLines = { sub: "", bus: "" };
  function selectMarker(f) {
    const p = f.properties, layer = f.layer.id.replace(/-(hover|sel|sel-ring)$/, "");
    if (state.marker && state.marker.layer === layer && state.marker.key === p.key) return clearMarker();
    const src = { grocery: L.grocery, gyms: L.gyms, places: L.places, "bus-stops": L.bus, "subway-stations": L.subway?.stations }[layer] || [];
    const keyOf = layer === "subway-stations" ? (r) => r[2] + "|" + r[3] : layer === "bus-stops" ? (r) => r[2] : (r) => r[3] || r[2];
    const label = layer === "subway-stations" ? p.name : layer === "bus-stops" ? p.name : p.key;
    state.marker = { layer, key: p.key, label, routes: p.routes || "",
      count: () => src.filter((r) => keyOf(r) === p.key && inBoros(r)).length };   // counted in the boroughs you kept
    applyMarkerSel();
  }
  function clearMarker() { state.marker = null; applyMarkerSel(); }
  // ---------- park selection: click a park to outline it and see its size and 5K route ----------
  const PARK_NONE = ["==", ["get", "pid"], -1];
  function parkAt(point) {
    if (!map || !map.getLayer("parks-fill") || map.getLayoutProperty("parks-fill", "visibility") === "none") return null;
    return map.queryRenderedFeatures(point, { layers: ["parks-fill"] })[0] || null;
  }
  function parkText(p) {
    const acres = p.acres >= 10 ? Math.round(p.acres) : p.acres;
    return [p.name, `${acres} acre${acres === 1 ? "" : "s"}`, p.run5k ? `5K ${p.run5k}` : null].filter(Boolean).join(" · ");
  }
  function selectPark(f) {
    const p = f.properties;
    if (state.marker?.layer === "parks" && state.marker.key === p.pid) return clearMarker();
    state.marker = { layer: "parks", key: p.pid, label: parkText(p) };
    applyMarkerSel();
  }
  function applyMarkerSel() {
    const m = state.marker;
    if (map) for (const id of SEL_LAYERS) for (const lid of [id + "-sel", id + "-sel-ring"])
      if (map.getLayer(lid)) map.setFilter(lid, m && m.layer === id ? withBoro(["==", ["get", "key"], m.key]) : SEL_NONE);
    if (map?.getLayer("parks-sel")) map.setFilter("parks-sel", m?.layer === "parks" ? ["==", ["get", "pid"], m.key] : PARK_NONE);
    selLines = { sub: m?.layer === "subway-stations" ? m.routes : "", bus: m?.layer === "bus-stops" ? m.routes : "" };
    lineHoverKey = "\u0000"; setLineHover("", "");
    const chip = $("selChip");
    if (!m) { chip.hidden = true; return; }
    const what = m.layer === "subway-stations" ? `${m.label} · its lines highlighted`
      : m.layer === "bus-stops" ? `${m.label} · its routes highlighted`
      : m.layer === "parks" ? m.label
      : `${m.count()} × ${m.label}`;
    chip.innerHTML = `<span>${esc(what)}</span><button class="icon-btn" type="button" id="clearSel" aria-label="Clear highlighted markers">${CLOSE}</button>`;
    chip.hidden = false;
    $("clearSel").onclick = clearMarker;
  }

  function lineTooltip(sub, bus, pt) {
    const tip = $("tooltip");
    const busRows = bus.slice(0, 4).map((b) => `<div class="tr"><b>${esc(b.route)}</b>${b.kind === "sbs" ? " · Select Bus" : b.kind === "express" ? " · Express" : ""}
      <div class="ts">${esc([b.name, b.via].filter(Boolean).join(" · "))}</div></div>`).join("");
    tip.innerHTML = (sub.length ? `<div class="tn">Subway</div>${bullets(sub.map((x) => x.route).join(" "))}` : "") +
      (bus.length ? `<div class="tn"${sub.length ? ' style="margin-top:6px"' : ""}>Bus route${bus.length > 1 ? "s" : ""}</div>${busRows}` +
        (bus.length > 4 ? `<div class="ts">and ${bus.length - 4} more</div>` : "") : "");
    placeTooltip(pt);
  }
  function placeTooltip(pt) {
    const tip = $("tooltip");
    tip.hidden = false;
    const W = $("mapwrap").clientWidth, H = $("mapwrap").clientHeight;
    const x = Math.min(pt.x + 14, W - tip.offsetWidth - 8), y = Math.min(pt.y + 14, H - tip.offsetHeight - 8);
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  }

  function fillExpression() {
    const ramp = RAMP[theme()];
    const v = ["coalesce", ["feature-state", "v"], -1];
    return ["case",
      ["all", ["boolean", ["feature-state", "on"], false], [">=", v, 0]],
      ["step", v, ramp[0], thresholds[0], ramp[1], thresholds[1], ramp[2], thresholds[2], ramp[3], thresholds[3], ramp[4]],
      ["boolean", ["feature-state", "short"], false], theme() === "dark" ? "rgba(240,239,236,0.16)" : "rgba(11,11,11,0.10)",
      "rgba(0,0,0,0)"];
  }

  function pushMap(all = false) {
    if (!map || !styleReady) return;
    for (const r of results) {
      const v = colorValue(r);
      map.setFeatureState({ source: "hoods", id: r.id }, { v: v == null ? -1 : v, on: r.visible, sel: r.id === state.selected,
        short: shortlist.includes(r.id) });
    }
    map.setPaintProperty("fill", "fill-color", fillExpression());
    renderHexes();
    applyBoroughFilter(all);
    renderPins(all);
  }

  // MapLibre owns the marker root: it sets position:absolute and moves it with an inline transform.
  // Our styles (hover scale, transitions, relative positioning) go on a child, never on the root,
  // otherwise markers drift from their coordinates when you zoom.
  function markerRoot(child) {
    const root = document.createElement("div");
    root.className = "mk";
    root.appendChild(child);
    return root;
  }

  function renderPins(force) {
    // Top 10 matches, plus every shortlisted area (starred), whether or not it matches
    const top = results.filter((r) => (r.rank && r.rank <= 10) || shortlist.includes(r.id));
    // Selection isn't in the key: selecting just toggles a class instead of rebuilding every marker
    const key = top.map((r) => r.id + (shortlist.includes(r.id) ? "*" : "") + r.rank).join(",");
    for (const [id, mk] of pins) mk.getElement().firstChild.classList.toggle("sel", id === state.selected);
    if (!force && key === lastPins) return;
    lastPins = key;
    for (const mk of pins.values()) mk.remove();
    pins.clear();
    for (const r of top) {
      const at = r.f.properties.label || center(r.f);
      const el = document.createElement("button");
      el.type = "button";
      const starred = shortlist.includes(r.id);
      el.className = "pin" + (starred ? " short" : "") + (r.id === state.selected ? " sel" : "");
      el.innerHTML = (starred ? STAR : "") + (r.rank && r.rank <= 10 ? r.rank : "");
      el.setAttribute("aria-label", `${r.rank ? "#" + r.rank + " " : ""}${r.f.properties.name}${starred ? ", shortlisted" : ""}`);
      el.onclick = (e) => { e.stopPropagation(); select(r.id, false); };
      el.onmouseenter = () => setHover(r.id, true);
      el.onmouseleave = () => setHover(null, true);
      pins.set(r.id, new maplibregl.Marker({ element: markerRoot(el) }).setLngLat(at).addTo(map));
    }
  }

  function setHover(id, fromMap) {
    if (state.hover === id) return;
    if (map && styleReady && state.hover) map.setFeatureState({ source: "hoods", id: state.hover }, { hover: false });
    document.querySelectorAll(".ranking li.hl").forEach((li) => li.classList.remove("hl"));
    state.hover = id;
    if (!id) return;
    if (map && styleReady) map.setFeatureState({ source: "hoods", id }, { hover: true });
    if (fromMap) document.querySelectorAll(`.ranking li[data-id="${CSS.escape(id)}"]`).forEach((li) => li.classList.add("hl"));
  }

  function showTooltip(id, pt, park) {
    const r = byId.get(id), tip = $("tooltip");
    tip.classList.remove("wide");
    if (!r) return;
    const parkLine = park ? `<div class="tpark">${esc(parkText(park))}</div>` : "";
    const p = r.f.properties, rent = rentOf(p), mins = commuteOf(p);
    const v = colorValue(r);
    const label = state.colorBy === "total" ? "match" : META.factors[state.colorBy].label;
    tip.innerHTML = `<div class="tn">${esc(p.name)}</div>
      ${p.residential ? `<div><span class="tv">${v == null ? "—" : Math.round(v)}</span> <span class="ts">${esc(label)}${r.rank ? ` · #${r.rank}` : ""}</span></div>
      <div class="tr">${[rent != null ? fmtRent(rent) + (rentIsEstimate(p) ? " est." : "") : null, mins != null ? `${commuteIsEstimate(p) ? "~" : ""}${Math.round(mins)} min` : null].filter(Boolean).join(" · ")}</div>` : ""}
      ${r.reason ? `<div class="ts">${esc(r.reason)}</div>` : ""}${parkLine}`;
    placeTooltip(pt);
  }

  function select(id, fly) {
    const prev = state.selected;
    state.selected = id;
    renderDetail();   // the docked panel changes the map's width; the ResizeObserver on #mapwrap resizes the map
    if (id && fly && map) {
      const f = BY_ID.get(id);
      const floating = !MOBILE() && matchMedia("(max-width: 1180px)").matches;
      const pad = MOBILE() ? { top: 40, bottom: 40, left: 40, right: 40 } : { top: 80, bottom: 80, left: 80, right: floating ? 400 : 80 };
      map.fitBounds(bbox([f]), { padding: pad, maxZoom: 14, duration: motionMs(600) });
    }
    if (id && !fly && state.tab === "matches") {
      const li = document.querySelector(`#ranking li[data-id="${CSS.escape(id)}"]`);
      li?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    document.querySelectorAll(".ranking li").forEach((li) => li.classList.toggle("sel", li.dataset.id === id));
    syncArea();   // "Use selected area" needs a selection
    if (!id && state.airRoute) state.airRoute = null;
    renderAirRoute();
    if (map && styleReady) {
      if (prev && prev !== id) map.setFeatureState({ source: "hoods", id: prev }, { sel: false });
      if (id) map.setFeatureState({ source: "hoods", id }, { sel: true });
      setHexHover(null);
      renderHexes();
      renderPins();
    }
  }

  function bbox(features) {
    let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
    const walk = (c) => {
      if (typeof c[0] === "number") { x0 = Math.min(x0, c[0]); x1 = Math.max(x1, c[0]); y0 = Math.min(y0, c[1]); y1 = Math.max(y1, c[1]); }
      else c.forEach(walk);
    };
    features.forEach((f) => walk(f.geometry.coordinates));
    return [[x0, y0], [x1, y1]];
  }
  function center(f) { const [[a, b], [c, d]] = bbox([f]); return [(a + c) / 2, (b + d) / 2]; }

  $("fitBtn").onclick = () => {
    const vis = results.filter((r) => r.rank).map((r) => r.f);
    if (map && vis.length) map.fitBounds(bbox(vis), { padding: 50, duration: motionMs(600) });
  };

  // ---------- update loop ----------
  let pending = false;
  function schedule() {
    syncFilters();
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; update(); });
  }
  function update() {
    recompute();
    // A hidden list isn't rendered (it can't be measured anyway); setTab renders it when its tab opens
    syncFilters();
    if (state.tab === "matches") renderRanking();
    renderShortlist(state.tab === "shortlist");
    renderLegend(); renderDetail(); pushMap(); persist();
    $("weightsMsg").hidden = !noWeights();
  }

  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest?.("input, textarea, select, [contenteditable]");
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && $("compare").hidden) {
      e.preventDefault(); setTab("matches"); $("search").focus(); return;
    }
    if (e.key !== "Escape") return;
    if (state.pickingArea) setAreaPickMode(false);
    else if (state.addingDest) setAddMode(false);
    else if (!$("compare").hidden) closeCompare();
    else if (state.marker) clearMarker();
    else if (state.airRoute?.pinned) pinAirport(null);
    else if (state.selected) select(null);
  });

  const built = new Date(String(META.generated_at).replace(" UTC", "Z").replace(" ", "T"));
  function themeChanged() {
    if (map) {
      styleReady = false;   // diff: false, because a diffed swap skips "style.load", which is what re-adds our layers
      map.setStyle(BASEMAP[theme()], { diff: false });
    }
    renderLegend(); buildPriorities(); renderRanking(); renderShortlist(); renderDetail(); renderLayersMenu();
  }
  function setThemeMode(mode) {
    const before = theme();
    themeMode = mode;
    if (mode === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = mode;
    try { localStorage.setItem(THEME_KEY, mode); } catch (e) {}
    if (theme() !== before) themeChanged();
  }
  for (const input of document.querySelectorAll('input[name="theme"]')) {
    input.checked = input.value === themeMode;
    input.onchange = () => setThemeMode(input.value);
  }
  darkQuery.addEventListener("change", () => { if (themeMode === "auto") themeChanged(); });

  $("meta").textContent = `Data built ${isNaN(built) ? META.generated_at : built.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}. ` +
    (META.rent_basis === "census" ? "Rents are Census-based estimates" : "Rents from listing data where available, else Census-based estimates") +
    `${RENT_BAND ? `, shown in $${fmtInt(RENT_BAND)} bands` : ""}.` +
    `${ROUTED ? " Commutes routed on MTA schedules." : ""}`;
  buildFilters(); buildTabs(); bindLists(); buildPriorities(); buildColorBy(); bindDestMenu(); renderDestMenu(); renderLayersMenu(); bindLegend(); buildArea();
  update();
  initMap();
  window.__stoop = { state, results: () => results, update, map: () => map };   // for debugging in the console
})();
