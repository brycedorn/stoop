"""Map context layers: parks, your places, full-size grocery stores, subway and bus.

None of these change a score; they're there to help you read a neighborhood. Written to
web/data/layers.js (window.STOOP_LAYERS) next to the scoring payload. Each layer is built
on its own, so one failing source doesn't block the rest.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import fetch, osm
from .context import CRS_LL

log = logging.getLogger("stoop.layers")

# Chains whose NYC stores are full-size supermarkets. Mixed-format chains (Key Food, C-Town,
# Associated...) qualify only through their building footprint.
LARGE_CHAINS = ["whole foods", "trader joe", "wegmans", "aldi", "lidl", "shoprite", "stop & shop", "stop and shop",
                "food bazaar", "h mart", "fairway", "western beef", "netcost", "costco", "bj's", "target",
                "uncle giuseppe", "jetro", "restaurant depot"]
CHAIN_NAMES = {"trader joe": "Trader Joe's", "bj's": "BJ's", "h mart": "H Mart", "stop and shop": "Stop & Shop",
               "shoprite": "ShopRite", "netcost": "NetCost", "stop & shop": "Stop & Shop"}
LARGE_FOOTPRINT_M2 = 900          # ~10k sq ft: a full supermarket floor
SUBWAY_GTFS = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"
BUS_STOPS = ("https://data.ny.gov", "2ucp-7wg5")


def _ll(gdf):
    return gdf.to_crs(CRS_LL)


def _r(x: float) -> float:
    return round(float(x), 5)


def parks(ctx) -> dict:
    """Park polygons, simplified for the web (outlines within ~6 m)."""
    import shapely
    from shapely.geometry import mapping
    from .sources.green import load_parks
    p = load_parks(ctx)
    p = p[p["acres_calc"] >= 0.1].copy()
    # NYC Parks outlines include water (Hudson River Park, Brooklyn Bridge Park run out to the pier line);
    # the neighborhood shapes stop at the shoreline, so clip to them.
    land = ctx.ntas.to_crs(p.crs).union_all().buffer(5)
    p["geometry"] = p.geometry.intersection(land)
    p = p[~p.geometry.is_empty & p.geometry.notna()]
    p = p[p.geometry.area >= 0.1 * 4046.86]
    p["geometry"] = p.geometry.simplify(6, preserve_topology=True)
    p = _ll(p)
    p["geometry"] = shapely.set_precision(p.geometry.values, 1e-5)
    feats = [{"type": "Feature", "geometry": mapping(g),
              "properties": {"name": str(n) if isinstance(n, str) else "Park", "acres": round(float(a), 1)}}
             for g, n, a in zip(p.geometry, p.get("signname", pd.Series([None] * len(p))), p["acres_calc"])
             if g is not None and not g.is_empty]
    # Parks a 5K route is named after (run_routes names routes by the park they're in)
    kinds = {"park loop": "loop", "paths": "paths", "track": "track"}
    route_file = ctx.interim / "run5k_routes.json"
    if route_file.exists():
        by_name: dict[str, str] = {}
        for r in json.loads(route_file.read_text(encoding="utf-8")):
            by_name.setdefault(r.get("name") or "", kinds.get(r.get("kind"), "paths"))
        for f in feats:
            if f["properties"]["name"] in by_name:
                f["properties"]["run5k"] = by_name[f["properties"]["name"]]
    return {"type": "FeatureCollection", "features": feats}


def places(ctx) -> list:
    """Your geocoded bars and restaurants: [lon, lat, name]."""
    path = ctx.interim / "places_geocoded.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path).dropna(subset=["lat", "lon"])
    df = df[osm.in_nyc_ll(ctx, df["lon"], df["lat"])]
    return [[_r(r.lon), _r(r.lat), str(r["name"])] for _, r in df.iterrows()]


def grocery_brand(name) -> str:
    """Chain name for a supermarket ('Whole Foods'), else its own name: what 'select all like this' matches on."""
    n = str(name or "").lower()
    chain = next((c for c in LARGE_CHAINS if c in n), None)
    if not chain:
        return str(name) if name else "Supermarket"
    return CHAIN_NAMES.get(chain, chain.title())


def is_large_grocery(name, footprint_m2) -> str | None:
    """Why a supermarket counts as full-size ('chain' / 'footprint'), or None."""
    n = "" if name is None or (not isinstance(name, str) and pd.isna(name)) else str(name).lower()
    if any(c in n for c in LARGE_CHAINS):
        return "chain"
    if footprint_m2 is not None and footprint_m2 >= LARGE_FOOTPRINT_M2:
        return "footprint"
    return None


def grocery(ctx) -> list:
    """Full-size supermarkets: [lon, lat, name]."""
    from .sources.convenience import ERRAND_TAGS
    g = osm.features(ctx, ERRAND_TAGS, "errands")
    g = g[osm.in_nyc(ctx, g)]
    is_super = g["shop"].eq("supermarket").fillna(False).astype(bool)
    s = g[is_super].copy()
    area = s.geometry.area.where(s.geometry.geom_type.isin(["Polygon", "MultiPolygon"]))
    s["why"] = [is_large_grocery(n, a if pd.notna(a) else None) for n, a in zip(s["name"], area)]
    s = s[s["why"].notna()]
    pts = _ll(s.set_geometry(s.geometry.representative_point()))
    out = [[_r(p.x), _r(p.y), str(n) if isinstance(n, str) else "Supermarket", grocery_brand(n if isinstance(n, str) else None)]
           for p, n in zip(pts.geometry, pts["name"])]
    log.info("layers: %d of %d supermarkets are full-size", len(out), int(is_super.sum()))
    return out


def gyms(ctx) -> list:
    """Full-size gyms: [lon, lat, name, brand]."""
    import geopandas as gpd
    from .sources.convenience import big_gyms
    g = big_gyms(ctx)
    if g.empty:
        return []
    pts = gpd.GeoSeries(gpd.points_from_xy(g.x, g.y), crs=ctx.grid.crs).to_crs(CRS_LL)
    out = [[_r(p.x), _r(p.y), n, b] for p, n, b in zip(pts, g["name"], g["brand"])]
    log.info("layers: %d full-size gyms", len(out))
    return out


def subway(ctx) -> dict:
    """Subway lines from the MTA GTFS (official route colors) + stations with their routes."""
    from shapely.geometry import LineString, mapping
    z = zipfile.ZipFile(fetch.download(SUBWAY_GTFS, ctx.raw / "transit" / "gtfs_subway_layers.zip",
                                       ctx.wants_refresh("layers")))
    read = lambda name: pd.read_csv(io.BytesIO(z.read(name)), dtype=str)
    routes = read("routes.txt").set_index("route_id")
    trips = read("trips.txt")[["route_id", "shape_id"]].dropna().drop_duplicates()
    shapes = read("shapes.txt")
    shapes["seq"] = shapes["shape_pt_sequence"].astype(int)
    shapes = shapes.sort_values(["shape_id", "seq"])
    lines, seen = [], set()
    for shape_id, pts in shapes.groupby("shape_id"):
        rid = trips.loc[trips.shape_id == shape_id, "route_id"]
        if rid.empty:
            continue
        rid = rid.iloc[0]
        line = LineString(list(zip(pts.shape_pt_lon.astype(float), pts.shape_pt_lat.astype(float)))).simplify(0.00008)
        key = (rid, tuple(np.round(line.coords[0], 3)), tuple(np.round(line.coords[-1], 3)))
        if key in seen or (rid, key[2], key[1]) in seen:     # same route, same ends (often the reverse direction)
            continue
        seen.add(key)
        r = routes.loc[rid] if rid in routes.index else {}
        color = "#" + str(r.get("route_color") or "808183").lstrip("#")
        lines.append({"type": "Feature", "geometry": mapping(line),
                      "properties": {"route": str(r.get("route_short_name") or rid), "color": color}})
    for f in lines:
        f["geometry"]["coordinates"] = [[_r(x), _r(y)] for x, y in f["geometry"]["coordinates"]]

    st = fetch.socrata_rows(ctx.src["ny_state_open_data"], ctx.src["subway_stations"], ctx.raw)
    cols = {c.lower(): c for c in st.columns}
    lat = next(cols[c] for c in cols if "latitude" in c)
    lon = next(cols[c] for c in cols if "longitude" in c)
    name = next((cols[c] for c in cols if c in ("stop_name", "station_name", "name")), None)
    rts = next((cols[c] for c in cols if "daytime_routes" in c or c == "routes"), None)
    stations = []
    for _, r in st.iterrows():
        try:
            stations.append([_r(r[lon]), _r(r[lat]), str(r[name]) if name else "Station", str(r[rts]) if rts else ""])
        except (TypeError, ValueError):
            continue
    stations = [list(x) for x in {(a, b, c, d) for a, b, c, d in stations}]
    log.info("layers: %d subway line shapes, %d stations", len(lines), len(stations))
    return {"lines": {"type": "FeatureCollection", "features": lines}, "stations": stations}


def bus_stops(ctx) -> list:
    """Current MTA bus stops: [lon, lat, name, "B38 B54 ..."]. Grouped server-side (the table has every past schedule)."""
    df = fetch.socrata_rows(*BUS_STOPS, ctx.raw,
                            select="stop_id, stop_name, latitude, longitude, route_short_name",
                            where="in_effect = 'true'", group="stop_id, stop_name, latitude, longitude, route_short_name",
                            order="stop_id, route_short_name", refresh=ctx.wants_refresh("layers"))
    if df.empty:
        return []
    df["route_short_name"] = df["route_short_name"].fillna("")
    g = df.groupby(["stop_id", "stop_name", "latitude", "longitude"])["route_short_name"] \
        .apply(lambda s: " ".join(sorted(set(x for x in s if x), key=_route_key))).reset_index()
    g = g[osm.in_nyc_ll(ctx, pd.to_numeric(g.longitude), pd.to_numeric(g.latitude))]
    out = [[_r(r.longitude), _r(r.latitude), str(r.stop_name).title(), r.route_short_name] for r in g.itertuples()]
    log.info("layers: %d bus stops", len(out))
    return out


def bus_kind(route_id: str, short_name: str) -> str:
    """'sbs' (Select Bus Service), 'express' (BM/QM/BxM/SIM/X), or 'local'."""
    name = str(short_name or route_id).upper()
    if name.endswith("-SBS") or str(route_id).endswith("+"):
        return "sbs"
    if re.match(r"^(BM|QM|BXM|SIM|X)\d", name):
        return "express"
    return "local"


def bus_routes(ctx) -> dict:
    """Bus route lines from the MTA bus GTFS feeds (the ones the commute step downloads):
    the longest shape per route and direction, simplified to ~10 m."""
    from shapely.geometry import LineString
    feeds = [(i, u) for i, u in enumerate(ctx.src.get("gtfs") or []) if "subway" not in u]
    best, info = {}, {}
    for i, url in feeds:
        z = zipfile.ZipFile(fetch.download(url, ctx.raw / "transit" / f"gtfs_{i}.zip"))
        read = lambda name: pd.read_csv(io.BytesIO(z.read(name)), dtype=str)
        for r in read("routes.txt").fillna("").itertuples():
            info.setdefault(r.route_id, (r.route_short_name or r.route_id, r.route_long_name, r.route_desc))
        trips = read("trips.txt")[["route_id", "direction_id", "shape_id"]].dropna().drop_duplicates()
        shapes = read("shapes.txt")
        shapes["seq"] = shapes["shape_pt_sequence"].astype(int)
        n = shapes.groupby("shape_id").size()
        trips["n"] = trips.shape_id.map(n).fillna(0)
        top = trips.sort_values("n").groupby(["route_id", "direction_id"]).tail(1)
        want = {sid: (rid, d, k) for rid, d, sid, k in top[["route_id", "direction_id", "shape_id", "n"]].itertuples(index=False)}
        for sid, pts in shapes[shapes.shape_id.isin(want)].sort_values(["shape_id", "seq"]).groupby("shape_id"):
            rid, d, k = want[sid]
            if k > best.get((rid, d), (0, None))[0]:
                best[(rid, d)] = (k, list(zip(pts.shape_pt_lon.astype(float), pts.shape_pt_lat.astype(float))))
    feats, nyc = [], osm.nyc_area(ctx, crs=4326)
    for (rid, _), (_, coords) in sorted(best.items()):
        if len(coords) < 2:
            continue
        line = LineString(coords).simplify(0.0001).intersection(nyc)   # only the part inside NYC
        if line.is_empty:
            continue
        parts = [line] if line.geom_type == "LineString" else [g for g in getattr(line, "geoms", []) if g.geom_type == "LineString"]
        if not parts:
            continue
        short, long_name, desc = info.get(rid, (rid, "", ""))
        coords_out = [[[_r(x), _r(y)] for x, y in pt.coords] for pt in parts]
        feats.append({"type": "Feature",
                      "geometry": ({"type": "LineString", "coordinates": coords_out[0]} if len(coords_out) == 1
                                   else {"type": "MultiLineString", "coordinates": coords_out}),
                      "properties": {"route": short, "name": long_name, "via": desc, "kind": bus_kind(rid, short)}})
    log.info("layers: %d bus route shapes (%d routes)", len(feats), len({f["properties"]["route"] for f in feats}))
    return {"type": "FeatureCollection", "features": feats}


def runner_hex_layer(ctx) -> dict:
    """The runner hexes from your runner-traffic file as polygons with their value, for the map (read-only)."""
    from .sources import runner_hexes as rh
    got = rh.load(ctx)
    if not got:
        return {"type": "FeatureCollection", "features": []}
    hexes, size = got
    feats = [{"type": "Feature", "properties": {"v": v},
              "geometry": {"type": "Polygon", "coordinates": [rh.hex_ring(*map(int, k.split(",")), size)]}}
             for k, v in hexes.items()]
    log.info("layers: %d runner hexes", len(feats))
    return {"type": "FeatureCollection", "features": feats}


# Airport markers (terminal areas). Not borough-tagged on purpose: they stay on the map whatever you filter.
AIRPORT_MARKERS = [
    (-73.7781, 40.6413, "John F. Kennedy International", "JFK"),
    (-73.8740, 40.7769, "LaGuardia", "LGA"),
    (-74.1745, 40.6895, "Newark Liberty International", "EWR"),
]


def airports(ctx) -> list:
    """[lon, lat, name, code] for JFK, LaGuardia and Newark."""
    return [list(a) for a in AIRPORT_MARKERS]


def _route_key(r: str):
    m = re.match(r"([A-Za-z]+)(\d*)(.*)", r)
    return (m.group(1), int(m.group(2) or 0), m.group(3)) if m else (r, 0, "")


BUILDERS = {"parks": parks, "places": places, "grocery": grocery, "gyms": gyms, "airports": airports, "runhex": runner_hex_layer,
            "subway": subway, "bus": bus_stops,
            "bus_routes": bus_routes}


def boro_lookup(ctx):
    """f(lon[], lat[]) -> borough names, by the nearest borough (so a point on a pier or bridge still gets one)."""
    import geopandas as gpd
    boros = ctx.ntas[["borough", "geometry"]].dissolve("borough").reset_index()

    def of(lon, lat) -> list:
        if len(lon) == 0:
            return []
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs=CRS_LL).to_crs(boros.crs)
        j = gpd.sjoin_nearest(pts, boros, how="left")
        j = j[~j.index.duplicated(keep="first")]
        return j["borough"].reindex(pts.index).fillna("").astype(str).tolist()
    return of


def split_lines_by_boro(features: list, of) -> list:
    """Cut each line where it changes borough (each segment goes by its midpoint, so tunnels and bridges land in
    the nearest borough). One feature per (line, borough), with a "boro" property."""
    runs_in = []   # (feature index, coordinate list)
    for i, f in enumerate(features):
        g = f["geometry"]
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        runs_in += [(i, c) for c in parts if len(c) >= 2]
    mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for _, c in runs_in for a, b in zip(c, c[1:])]
    boro = iter(of([m[0] for m in mids], [m[1] for m in mids]))
    pieces = {}   # (feature index, borough) -> list of coordinate runs
    for i, c in runs_in:
        seg_b = [next(boro) for _ in range(len(c) - 1)]
        start = 0
        for k in range(1, len(seg_b) + 1):
            if k == len(seg_b) or seg_b[k] != seg_b[start]:
                pieces.setdefault((i, seg_b[start]), []).append(c[start:k + 1])
                start = k
    out = []
    for (i, b), runs in pieces.items():
        geom = {"type": "LineString", "coordinates": runs[0]} if len(runs) == 1 else {"type": "MultiLineString", "coordinates": runs}
        out.append({"type": "Feature", "geometry": geom, "properties": {**features[i]["properties"], "boro": b}})
    return out


def tag_boroughs(ctx, out: dict) -> dict:
    """Give everything on the map a borough, so the map can hide what's in a borough you filtered out.
    Point rows become [lon, lat, name, extra, borough] (extra = brand or routes, "" for your places)."""
    import shapely
    from shapely.geometry import shape
    of = boro_lookup(ctx)

    def rows(lst):
        b = of([r[0] for r in lst], [r[1] for r in lst])
        return [(list(r) + [""] * (4 - len(r)))[:4] + [x] for r, x in zip(lst, b)]
    for key in ["grocery", "gyms", "places", "bus"]:
        if out.get(key):
            out[key] = rows(out[key])
    if (out.get("subway") or {}).get("stations"):
        out["subway"]["stations"] = rows(out["subway"]["stations"])
    if (out.get("parks") or {}).get("features"):
        reps = [shapely.get_coordinates(shape(f["geometry"]).representative_point())[0] for f in out["parks"]["features"]]
        for f, b in zip(out["parks"]["features"], of([p[0] for p in reps], [p[1] for p in reps])):
            f["properties"]["boro"] = b
    if (out.get("subway") or {}).get("lines"):
        out["subway"]["lines"]["features"] = split_lines_by_boro(out["subway"]["lines"]["features"], of)
    if out.get("bus_routes"):
        out["bus_routes"]["features"] = split_lines_by_boro(out["bus_routes"]["features"], of)
    return out


def write_layers(ctx, web_dir: Path, skip: tuple = ()) -> Path:
    """web_dir/data/layers.js with every context layer except `skip` (the public build skips personal ones)."""
    out = {}
    for name, fn in BUILDERS.items():
        if name in skip:
            continue
        try:
            out[name] = fn(ctx)
        except Exception as e:      # one missing source shouldn't block the others
            log.warning("layer %s skipped: %s", name, e)
    try:
        out = tag_boroughs(ctx, out)
    except Exception as e:
        log.warning("borough tags skipped (borough filter won't hide map layers): %s", e)
    path = Path(web_dir) / "data" / "layers.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("window.STOOP_LAYERS=" + json.dumps(out, separators=(",", ":")) + ";\n", encoding="utf-8")
    log.info("wrote %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    return path
