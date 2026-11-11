"""Car-free 5K routes nearby, from OpenStreetMap.

Paths (footways, paths, cycleways, pedestrian ways, tracks, car-free park drives) are downloaded for New York
City from the Overpass API in 16 tiles, each cached under data/raw/osm_run_networks/ so an interrupted download
resumes. Ways that share an OSM node are joined into networks. A network is a 5K route when its paths add up to
MIN_5K_KM (out and back, or a loop run twice) and it spans at least MIN_SPAN_M end to end, so a small park with
a tangle of short paths doesn't count.

Per neighborhood, from its label point: walking minutes to the nearest point of such a route (points every
ACCESS_SPACING_M along it). Routed on foot with r5py when available (rivers, bridges), else straight line x
WALK_DETOUR.
    run5k_min    = minutes to the nearest 5K route
    run5k_score  = run5k_curve(run5k_min): 5 min or less = 100, 30+ min = 0
    run5k_route  = that route's name

OSM data (c) OpenStreetMap contributors, ODbL.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ..scoring import run5k_curve
from .runner_hexes import KX, KY, to_xy

log = logging.getLogger("stoop.run_routes")
NAME = "run_routes"

WALK_M_PER_MIN = 80
WALK_DETOUR = 1.3        # straight line -> street distance (Manhattan grid ~1.27)
MAX_WALK_MIN = 60        # routes farther than this don't count

MIN_NETWORK_KM = 1.0     # smaller networks are ignored
MIN_5K_KM = 2.5          # paths enough for a 5K out and back, or a loop run twice
MIN_SPAN_M = 500         # must stretch this far end to end (rules out tangles in small parks)
ACCESS_SPACING_M = 250   # spacing of the points distance is measured to
SAMPLE_M = 20
JOIN_GAP_M = 8           # paths that stop this close to another path are joined (mapping gaps, not streets)
# Waterfront greenways often run outside park polygons; a network mostly made of these counts like a park one.
GREENWAY_NAME = re.compile(r"greenway|esplanade|promenade|boardwalk|river ?walk|waterfront", re.I)

OVERPASS_MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter"]
NYC_WIKIDATA = "Q60"
NYC_BBOX = (40.476, -74.260, 40.918, -73.699)   # south, west, north, east
TILES = 4                                       # 4 x 4: one city-wide query times out on public servers
RUN_HIGHWAYS = "footway|path|pedestrian|cycleway|track|bridleway"
PARK_DRIVE_HIGHWAYS = "service|residential|unclassified|tertiary|secondary"
EXCLUDE_FOOTWAY = {"sidewalk", "crossing", "traffic_island", "access_aisle"}
NO_ACCESS = {"private", "no", "customers", "permit"}
# Paths inside these aren't public running routes (Green-Wood, Brooklyn Botanic Garden, the Bronx Zoo...)
NO_RUN_AREAS = {"landuse": ["cemetery"], "amenity": ["grave_yard"], "tourism": ["zoo"],
                "leisure": ["golf_course", "garden"]}
LOOP_MIN_KM = 1.2        # a park whose edge is this long is a 5K loop (~4 laps): McCarren, Fort Greene...
STREET_BRIDGE_M = 15     # join park pieces split by a street before measuring the edge
IN_PARK_SHARE = 0.5      # a path network counts only if this share of it is inside parks (not campuses, NYCHA)
PARK_TAGS = {"leisure": ["park", "nature_reserve", "recreation_ground"]}   # OSM parks (incl. non-NYC-Parks)
LOOP_MIN_ROUNDNESS = 0.2 # 4*pi*area/perimeter^2: drops long strips (malls, greenway slivers) that aren't loops
TRACK_MIN_M = 300        # public running tracks inside NYC parks count too (12.5 laps of 400 m)
HEADERS = {"User-Agent": "stoop (personal NYC neighborhood finder)"}


# ---------------------------------------------------------------- download

def tile_query(bbox) -> str:
    s, w, n, e = bbox
    b = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    return f"""
[out:json][timeout:300];
area["wikidata"="{NYC_WIKIDATA}"]->.nyc;
(
  way(area.nyc){b}["highway"~"^({RUN_HIGHWAYS})$"];
  way(area.nyc){b}["highway"~"^({PARK_DRIVE_HIGHWAYS})$"]["motor_vehicle"="no"];
  way(area.nyc){b}["leisure"="track"];
);
out body geom;
"""


def tiles(bbox=NYC_BBOX, n=TILES) -> list[tuple]:
    s, w, no, e = bbox
    dl, dw = (no - s) / n, (e - w) / n
    return [(s + i * dl, w + j * dw, s + (i + 1) * dl, w + (j + 1) * dw) for i in range(n) for j in range(n)]


def _post(session, query: str) -> list[dict]:
    """One Overpass query, trying the mirrors in turn on busy/timeout errors."""
    last = None
    for attempt in range(2):
        for url in OVERPASS_MIRRORS:
            try:
                r = session.post(url, data={"data": query}, timeout=400, headers=HEADERS)
            except requests.RequestException as e:
                last = e
                continue
            if r.status_code in (429, 502, 503, 504):
                last = RuntimeError(f"{url}: {r.status_code}")
                continue
            r.raise_for_status()
            return [e for e in r.json().get("elements", []) if e.get("type") == "way" and e.get("geometry")]
        time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"OpenStreetMap servers are busy ({last}); run the step again in a few minutes")


def fetch_ways(cache_dir: Path, refresh: bool = False, session=None) -> list[dict]:
    """Raw Overpass ways for NYC, tile by tile (cached; a rerun resumes)."""
    tdir = Path(cache_dir) / "tiles"
    tdir.mkdir(parents=True, exist_ok=True)
    s = session or requests.Session()
    by_id: dict[int, dict] = {}
    for k, box in enumerate(tiles()):
        tp = tdir / f"tile_{k:02d}.json"
        if tp.exists() and not refresh:
            got = json.loads(tp.read_text(encoding="utf-8"))
        else:
            log.info("OpenStreetMap paths: tile %d/%d...", k + 1, TILES * TILES)
            got = _post(s, tile_query(box))
            tp.write_text(json.dumps(got), encoding="utf-8")
        for w in got:
            by_id[w["id"]] = w
    return list(by_id.values())


# ---------------------------------------------------------------- networks

def runnable(way: dict) -> bool:
    t = way.get("tags", {})
    if t.get("footway") in EXCLUDE_FOOTWAY or t.get("area") == "yes" or t.get("foot") == "no":
        return False
    if t.get("access") in NO_ACCESS and t.get("foot") not in ("yes", "designated", "permissive"):
        return False
    return len(way.get("geometry") or []) >= 2


def way_xy(way: dict) -> list[tuple[float, float]]:
    return [to_xy(p["lon"], p["lat"]) for p in way["geometry"]]


def length_m(xy) -> float:
    return sum(math.dist(a, b) for a, b in zip(xy, xy[1:]))


def resample(xy, step: float) -> list[tuple[float, float]]:
    """Points every `step` meters along a line, first and last vertex included."""
    if not xy:
        return []
    out, carry = [xy[0]], 0.0
    for a, b in zip(xy, xy[1:]):
        seg = math.dist(a, b)
        t = step - carry
        while t <= seg:
            out.append((a[0] + (b[0] - a[0]) * t / seg, a[1] + (b[1] - a[1]) * t / seg))
            t += step
        carry = (carry + seg) % step
    if math.dist(out[-1], xy[-1]) > 1e-6:
        out.append(xy[-1])
    return out


def thin(points, spacing: float) -> list[tuple[float, float]]:
    """Points at least `spacing` apart (greedy, in order)."""
    grid: dict[tuple[int, int], list] = defaultdict(list)
    out = []
    for x, y in points:
        kx, ky = int(math.floor(x / spacing)), int(math.floor(y / spacing))
        if any((px - x) ** 2 + (py - y) ** 2 < spacing * spacing
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for px, py in grid.get((kx + dx, ky + dy), ())):
            continue
        grid[(kx, ky)].append((x, y))
        out.append((x, y))
    return out


def networks(ways: list[dict], gap_m: float = 0.0) -> list[list[int]]:
    """Groups of way indexes connected through shared OSM nodes.

    With gap_m, a dead end within gap_m of another way also connects: OSM often maps one greenway as pieces
    that stop just short of each other (the East River Esplanade is 6 pieces)."""
    parent = list(range(len(ways)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_way_at: dict[int, int] = {}
    for i, w in enumerate(ways):
        for n in w.get("nodes", []):
            j = first_way_at.setdefault(n, i)
            if j != i:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    if gap_m > 0:
        uses = Counter(n for w in ways for n in w.get("nodes", []))
        lines = [way_xy(w) for w in ways]
        grid: dict[tuple[int, int], list] = defaultdict(list)
        for i, xy in enumerate(lines):
            for x, y in resample(xy, gap_m):
                grid[(int(x // gap_m), int(y // gap_m))].append((x, y, i))
        for i, (w, xy) in enumerate(zip(ways, lines)):
            nodes = w.get("nodes") or [None, None]
            for (x, y), node in ((xy[0], nodes[0]), (xy[-1], nodes[-1])):
                if node is not None and uses[node] > 1:
                    continue                                  # already connected there
                kx, ky = int(x // gap_m), int(y // gap_m)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for px, py, j in grid.get((kx + dx, ky + dy), ()):
                            if j != i and (px - x) ** 2 + (py - y) ** 2 <= gap_m * gap_m:
                                a, b = find(i), find(j)
                                if a != b:
                                    parent[a] = b
    groups: dict[int, list[int]] = {}
    for i in range(len(ways)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def route_networks(ways: list[dict]) -> list[dict]:
    """Path networks of MIN_NETWORK_KM or more: name, km, span, fits_5k and access points [lon, lat]."""
    keep = [w for w in ways if runnable(w)]
    out = []
    for group in networks(keep, JOIN_GAP_M):
        members = [keep[i] for i in group]
        lines = [way_xy(w) for w in members]
        lengths = [length_m(xy) for xy in lines]
        km = sum(lengths) / 1000
        if km < MIN_NETWORK_KM:
            continue
        pts = [p for xy in lines for p in resample(xy, SAMPLE_M)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        names = Counter()
        for w, L in zip(members, lengths):
            nm = (w.get("tags", {}).get("name") or "").strip()
            if nm:
                names[nm] += L
        greenway_m = sum(m for nm, m in names.items() if GREENWAY_NAME.search(nm))
        out.append({
            "kind": "paths",
            "name": names.most_common(1)[0][0] if names else "",
            "greenway_share": round(greenway_m / (km * 1000), 2),
            "km": round(km, 2),
            "span_m": round(span),
            "fits_5k": km >= MIN_5K_KM and span >= MIN_SPAN_M,
            "access": [[round(x / KX, 5), round(y / KY, 5)] for x, y in thin(pts, ACCESS_SPACING_M)],
        })
    out.sort(key=lambda r: -r["km"])
    for i, r in enumerate(out, 1):
        r["id"] = f"n{i:04d}"
    return out


# ---------------------------------------------------------------- parks: exclusions, loops, tracks, names

def _midpoint_ll(way: dict) -> tuple[float, float]:
    g = way["geometry"][len(way["geometry"]) // 2]
    return g["lon"], g["lat"]


def inside(polys_ll, lonlat: list) -> np.ndarray:
    """Which (lon, lat) points fall inside any of the polygons (a GeoDataFrame in lon/lat)."""
    import geopandas as gpd
    if polys_ll is None or len(polys_ll) == 0 or not lonlat:
        return np.zeros(len(lonlat), bool)
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(*zip(*lonlat)), crs=polys_ll.crs)
    hit = gpd.sjoin(pts, polys_ll[["geometry"]], predicate="within", how="inner").index.unique()
    out = np.zeros(len(lonlat), bool)
    out[np.asarray(hit, int)] = True
    return out


def drop_no_run_areas(ways: list[dict], areas_ll) -> list[dict]:
    """Ways whose midpoint isn't inside a cemetery, zoo, garden or golf course."""
    keep = ~inside(areas_ll, [_midpoint_ll(w) for w in ways])
    return [w for w, k in zip(ways, keep) if k]


def whole_park(geom):
    """A park's main outline, with pieces split by the streets crossing it joined back up (McCarren is 5 pieces)."""
    from shapely.geometry import Polygon
    if geom is None or geom.is_empty:
        return None
    merged = geom.buffer(STREET_BRIDGE_M).buffer(-STREET_BRIDGE_M)
    polys = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    return max((p for p in polys if isinstance(p, Polygon) and not p.is_empty), key=lambda p: p.area, default=None)


def park_loops(parks_m, no_run_m=None) -> list[dict]:
    """Compact NYC parks with an edge of LOOP_MIN_KM or more, as loop routes along the edge (parks in meters).
    Parks that are mostly a garden, cemetery, zoo or golf course (no_run_m, meters) are skipped."""
    import geopandas as gpd
    from ..context import CRS_LL
    blocked = no_run_m.geometry.union_all() if no_run_m is not None and len(no_run_m) else None
    out = []
    for name, geom in zip(parks_m["signname"], parks_m.geometry):
        poly = whole_park(geom)
        if poly is None:
            continue
        if blocked is not None and poly.intersection(blocked).area > 0.5 * poly.area:
            continue
        per = poly.exterior.length
        if per < LOOP_MIN_KM * 1000 or 4 * math.pi * poly.area / per ** 2 < LOOP_MIN_ROUNDNESS:
            continue
        edge = gpd.GeoSeries([poly.exterior.interpolate(d) for d in np.arange(0, per, ACCESS_SPACING_M)],
                             crs=parks_m.crs).to_crs(CRS_LL)
        out.append({"kind": "park loop", "name": str(name or ""), "km": round(per / 1000, 2), "fits_5k": True,
                    "access": [[round(p.x, 5), round(p.y, 5)] for p in edge]})
    return out


def park_tracks(ways: list[dict], parks_ll) -> list[dict]:
    """Running tracks (leisure=track) inside NYC parks; school tracks outside parks are usually closed."""
    tracks = [w for w in ways if w.get("tags", {}).get("leisure") == "track"
              and w["tags"].get("sport", "running") in ("running", "athletics", "running;athletics")
              and w["tags"].get("access") not in NO_ACCESS
              and length_m(way_xy(w)) >= TRACK_MIN_M]
    ok = inside(parks_ll, [_midpoint_ll(w) for w in tracks])
    return [{"kind": "track", "name": "", "km": round(length_m(way_xy(w)) / 1000, 2), "fits_5k": True,
             "access": [[round(p["lon"], 5), round(p["lat"], 5)] for p in w["geometry"][:: max(1, len(w["geometry"]) // 4)]]}
            for w, k in zip(tracks, ok) if k]


def name_by_park(routes: list[dict], parks_ll) -> None:
    """Name each route after the NYC park most of its access points fall in (keeps the path name otherwise)."""
    import geopandas as gpd
    rows = [(i, lon, lat) for i, r in enumerate(routes) for lon, lat in r["access"]]
    if not rows or parks_ll is None or len(parks_ll) == 0:
        return
    pts = gpd.GeoDataFrame({"r": [i for i, _, _ in rows]},
                           geometry=gpd.points_from_xy([x for _, x, _ in rows], [y for _, _, y in rows]),
                           crs=parks_ll.crs)
    hit = gpd.sjoin(pts, parks_ll[["signname", "geometry"]], predicate="within", how="inner")
    for i, grp in hit.groupby("r"):
        park, n = Counter(grp["signname"]).most_common(1)[0]
        if park and n >= max(1, len(routes[i]["access"]) // 3):
            r = routes[i]
            r["name"] = f"{park} track" if r["kind"] == "track" else str(park)


# ---------------------------------------------------------------- minutes and score

def estimate_minutes(origins: dict, routes: list[dict]) -> pd.DataFrame:
    """Straight-line walking minutes, origin x route (nearest access point)."""
    out = {}
    for r in routes:
        pts = np.array([to_xy(lon, lat) for lon, lat in r["access"]])
        col = {}
        for o, (lon, lat) in origins.items():
            x, y = to_xy(lon, lat)
            col[o] = float(np.min(np.hypot(pts[:, 0] - x, pts[:, 1] - y))) * WALK_DETOUR / WALK_M_PER_MIN
        out[r["id"]] = col
    return pd.DataFrame(out)


def _estimate_minutes_fast(origins: dict, routes: list[dict]) -> pd.DataFrame:
    """estimate_minutes, vectorized for many origins (grid cells)."""
    keys = list(origins)
    o = np.array([to_xy(lon, lat) for lon, lat in origins.values()])
    out = {}
    for r in routes:
        pts = np.array([to_xy(lon, lat) for lon, lat in r["access"]])
        best = np.full(len(o), np.inf)
        for chunk in range(0, len(pts), 200):
            p = pts[chunk:chunk + 200]
            d = np.hypot(o[:, None, 0] - p[None, :, 0], o[:, None, 1] - p[None, :, 1]).min(axis=1)
            best = np.minimum(best, d)
        out[r["id"]] = best * WALK_DETOUR / WALK_M_PER_MIN
    return pd.DataFrame(out, index=keys)


def r5_walk_minutes(ctx, origins: dict, routes: list[dict]) -> pd.DataFrame | None:
    """Routed walking minutes, origin x route (nearest access point), or None without r5py."""
    from .commute import configure_r5
    configure_r5(ctx)
    try:
        import r5py
    except Exception as e:  # ImportError, or Java missing at import
        log.info("r5py unavailable (%s); estimating walks to 5K routes", e)
        return None
    from datetime import datetime, timedelta

    import geopandas as gpd

    from .. import fetch
    from ..context import CRS_LL
    pbf = fetch.download(ctx.src["osm_pbf"], ctx.raw / "transit" / "nyc.osm.pbf", False)
    gtfs = [fetch.download(u, ctx.raw / "transit" / f"gtfs_{i}.zip", False) for i, u in enumerate(ctx.src["gtfs"])]
    network = r5py.TransportNetwork(str(pbf), [str(g) for g in gtfs])   # same inputs as commute: reuses its cache
    o = gpd.GeoDataFrame({"id": list(origins)}, geometry=gpd.points_from_xy(*zip(*origins.values())), crs=CRS_LL)
    ids, lons, lats = [], [], []
    for r in routes:
        for k, (lon, lat) in enumerate(r["access"]):
            ids.append(f"{r['id']}:{k}")
            lons.append(lon)
            lats.append(lat)
    d = gpd.GeoDataFrame({"id": ids}, geometry=gpd.points_from_xy(lons, lats), crs=CRS_LL)
    ttm = pd.DataFrame(r5py.TravelTimeMatrix(network, origins=o, destinations=d,
                                             departure=datetime.now().replace(hour=7, minute=0, second=0),
                                             transport_modes=[r5py.TransportMode.WALK],
                                             max_time=timedelta(minutes=MAX_WALK_MIN)))
    ttm["route"] = ttm["to_id"].str.split(":").str[0]
    return ttm.groupby(["from_id", "route"])["travel_time"].min().unstack().reindex(
        index=list(origins), columns=[r["id"] for r in routes])


def in_parks_share(routes: list[dict], parks_ll) -> list[float]:
    """Share of each route's access points inside a park."""
    rows = [(i, lon, lat) for i, r in enumerate(routes) for lon, lat in r["access"]]
    hit = inside(parks_ll, [(lon, lat) for _, lon, lat in rows])
    tot, inn = Counter(), Counter()
    for (i, _, _), h in zip(rows, hit):
        tot[i] += 1
        inn[i] += int(h)
    return [inn[i] / tot[i] if tot[i] else 0.0 for i in range(len(routes))]


def run5k_scores(minutes: pd.DataFrame, names: dict | None = None) -> pd.DataFrame:
    """run5k_min, run5k_score and run5k_route per origin from an origin x route minutes table.

    Nothing within MAX_WALK_MIN counts as MAX_WALK_MIN (score 0), not as missing data."""
    m = minutes.where(minutes <= MAX_WALK_MIN)
    near = m.min(axis=1)
    which = (m.fillna(np.inf).idxmin(axis=1).where(near.notna()) if m.shape[1]   # all-NaN rows: no route
             else pd.Series(None, index=m.index, dtype=object))
    near = near.fillna(MAX_WALK_MIN)
    out = pd.DataFrame({"run5k_min": near, "run5k_score": pd.Series(run5k_curve(near.values), index=near.index)})
    if names is not None:
        out["run5k_route"] = which.map(lambda r: (names.get(r) or "Unnamed path network") if isinstance(r, str) else None)
    return out


def main_route(grid, cell_route: pd.Series) -> pd.Series:
    """Per neighborhood: the route that's nearest for the most residents."""
    df = pd.DataFrame({"nta": grid["nta2020"].values, "route": cell_route.reindex(grid.index).values,
                       "pop": grid["pop"].fillna(0).values + 1e-6})
    df = df.dropna(subset=["route"])
    if df.empty:
        return pd.Series(dtype=object)
    best = df.groupby(["nta", "route"])["pop"].sum().reset_index().sort_values("pop", ascending=False)
    return best.drop_duplicates("nta").set_index("nta")["route"]


def build(ctx) -> pd.DataFrame:
    out = pd.DataFrame(index=ctx.ntas.index)
    from .. import osm
    from ..context import CRS_LL
    from .green import load_parks
    refresh = ctx.wants_refresh(NAME)
    ways = fetch_ways(ctx.raw / "osm_run_networks", refresh)
    areas = osm.features(ctx, NO_RUN_AREAS, "no_run_areas", refresh)
    areas = areas[areas.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].to_crs(CRS_LL)
    before = len(ways)
    ways = drop_no_run_areas(ways, areas)
    parks_m = load_parks(ctx)
    parks_ll = parks_m.to_crs(CRS_LL)
    osm_parks = osm.features(ctx, PARK_TAGS, "parks_osm", refresh)
    osm_parks = osm_parks[osm_parks.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].to_crs(CRS_LL)
    import geopandas as gpd
    any_park = gpd.GeoDataFrame(pd.concat([parks_ll[["geometry"]], osm_parks[["geometry"]]], ignore_index=True),
                                crs=CRS_LL)
    nets = [r for r in route_networks(ways) if r["fits_5k"]]
    share = in_parks_share(nets, any_park)
    in_park = [r for r, s in zip(nets, share) if s >= IN_PARK_SHARE or r["greenway_share"] >= IN_PARK_SHARE]
    loops = park_loops(parks_m, areas.to_crs(parks_m.crs))
    tracks = park_tracks(ways, any_park)
    routes = in_park + loops + tracks
    for i, r in enumerate(routes, 1):
        r["id"] = f"r{i:04d}"
    name_by_park(routes, parks_ll)
    log.info("5K routes: %d ways inside cemeteries/zoos/gardens/golf dropped; %d path networks, %d park loops, "
             "%d park tracks (%d networks outside parks dropped)", before - len(ways), len(in_park), len(loops),
             len(tracks), len(nets) - len(in_park))
    (ctx.interim / "run5k_routes.json").write_text(json.dumps(routes), encoding="utf-8")
    if not routes:
        log.warning("no car-free 5K routes found in the OSM data")
        return out
    # From every grid cell (like the other factors), then a population-weighted mean per neighborhood.
    from .. import geo
    grid = ctx.grid
    cells_ll = gpd.GeoSeries(gpd.points_from_xy(grid.x, grid.y), crs=grid.crs).to_crs(CRS_LL)
    origins = {cid: (p.x, p.y) for cid, p in zip(grid.index, cells_ll)}
    minutes, method = r5_walk_minutes(ctx, origins, routes), "routed"
    if minutes is None:
        minutes, method = _estimate_minutes_fast(origins, routes), "straight-line estimate"
    cells = run5k_scores(minutes, {r["id"]: r["name"] for r in routes})
    cells.to_parquet(ctx.interim / "run5k_cells.parquet")          # per cell, for the hex view
    out["run5k_min"] = geo.to_nta(grid, cells["run5k_min"].reindex(grid.index).values, "run5k_min")
    out["run5k_score"] = run5k_curve(out["run5k_min"].values)
    out["run5k_route"] = main_route(grid, cells["run5k_route"])
    log.info("5K routes (%s, %d cells): %d routes; median neighborhood %.0f min", method, len(grid),
             len(routes), out["run5k_min"].median())
    return out
