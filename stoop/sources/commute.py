"""Commute: door-to-door transit time from every grid cell to your destination(s).

Preferred: r5py (Conveyal R5) routing on OpenStreetMap + MTA GTFS, at a weekday
morning departure, using the median over a one-hour window. Needs Java 21
(`pip install r5py`). Without it, falls back to an estimate: walk to the
nearest subway station + straight-line ride at an average subway speed + a wait.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import fetch, geo
from ..context import CRS_LL

log = logging.getLogger("stoop.commute")
NAME = "commute"

WALK_M_PER_MIN = 80
SUBWAY_M_PER_MIN = 330    # ~20 km/h door-to-door average including stops/transfers
WAIT_MIN = 5
DETOUR = 1.3              # street-grid detour factor for walking straight-line distances

# Airports. The MTA GTFS has no AirTrain or NJ Transit, so JFK and Newark are routed to the rail stop where you
# change, plus a fixed last leg (ride + average wait). LaGuardia's buses (Q70 Link, M60-SBS...) are in the GTFS,
# so it's routed straight to Terminal B. hub id -> (airport, lat, lon, last-leg minutes)
AIRPORT_HUBS = {
    "jfk_jamaica": ("jfk", 40.7005, -73.8080, 12),   # Sutphin Blvd-Archer Av (E/J/Z), AirTrain ~8 min + wait
    "jfk_howard": ("jfk", 40.6605, -73.8303, 14),    # Howard Beach-JFK (A), AirTrain ~10 min + wait
    "lga": ("lga", 40.7746, -73.8721, 0),            # LaGuardia Terminal B, by bus
    "ewr_penn": ("ewr", 40.7506, -73.9935, 42),      # Penn Station: NJ Transit ~27 min + wait + AirTrain Newark
}
AIRPORTS = {"jfk": "JFK", "lga": "LaGuardia", "ewr": "Newark"}


def airport_minutes(hub_mins: pd.DataFrame) -> pd.DataFrame:
    """Per airport: the fastest way in (routed minutes to each hub + its last leg). Columns jfk, lga, ewr."""
    out = {}
    for code in AIRPORTS:
        legs = [hub_mins[h] + leg for h, (a, _, _, leg) in AIRPORT_HUBS.items() if a == code and h in hub_mins]
        if legs:
            out[code] = pd.concat(legs, axis=1).min(axis=1)
    return pd.DataFrame(out, index=hub_mins.index)


def dest_slug(name) -> str:
    """Column suffix for one destination's minutes: commute_min_<slug>."""
    return "".join(c if c.isalnum() else "_" for c in str(name).lower()).strip("_")


def active_destination(cfg) -> int | None:
    """Index of `you.commute_to` among the destinations (case-insensitive name), or None to average them all."""
    want = str((cfg.get("you") or {}).get("commute_to") or "").strip().lower()
    if not want:
        return None
    names = [str(d.get("name", "")).strip().lower() for d in cfg["you"]["commute_destinations"]]
    return names.index(want) if want in names else 0


def apply_commute_choice(table: pd.DataFrame, cfg) -> pd.DataFrame:
    """Point commute_min at the chosen destination's routed minutes (no re-routing: every destination is cached)."""
    i = active_destination(cfg)
    if i is None:
        return table
    col = f"commute_min_{dest_slug(cfg['you']['commute_destinations'][i].get('name', ''))}"
    if col in table.columns:
        table = table.copy()
        table["commute_min"] = table[col]
    return table


def subway_stations(ctx) -> np.ndarray:
    df = fetch.socrata_rows(ctx.src["ny_state_open_data"], ctx.src["subway_stations"], ctx.raw,
                            refresh=ctx.wants_refresh(NAME))
    cols = {c.lower(): c for c in df.columns}
    lat = next(cols[c] for c in cols if "latitude" in c)
    lon = next(cols[c] for c in cols if "longitude" in c)
    # The map re-estimates commutes live when you drag a destination pin; it needs the stations.
    ll = df[[lon, lat]].apply(pd.to_numeric, errors="coerce").dropna()
    ll = ll[ll[lat].between(40.4, 41.0) & ll[lon].between(-74.3, -73.6)].round(5).drop_duplicates()
    (ctx.interim / "subway_stations.json").write_text(json.dumps(ll.values.tolist()))
    return geo.df_xy(df, lon=lon, lat=lat)


def estimate_minutes(cells: np.ndarray, stations: np.ndarray, dest: np.ndarray) -> np.ndarray:
    from scipy.spatial import cKDTree
    tree = cKDTree(stations)
    d_walk, idx = tree.query(cells)
    d_dest_walk, dest_idx = tree.query(dest[None, :])
    ride = np.hypot(*(stations[idx] - stations[dest_idx[0]]).T)
    transit = d_walk / WALK_M_PER_MIN + WAIT_MIN + ride / SUBWAY_M_PER_MIN + d_dest_walk[0] / WALK_M_PER_MIN
    walk_only = np.hypot(*(cells - dest).T) * DETOUR / WALK_M_PER_MIN
    return np.minimum(transit, walk_only)


def departure_time(value) -> datetime:
    """'auto' -> next Tuesday 08:30 (always inside a freshly downloaded GTFS calendar)."""
    if value and str(value).lower() != "auto":
        return datetime.fromisoformat(str(value))
    today = datetime.now().replace(hour=8, minute=30, second=0, microsecond=0)
    return today + timedelta(days=(1 - today.weekday()) % 7 or 7)


def configure_r5(ctx) -> None:
    """Point r5py at Java 21 and set its heap before it's imported (it reads both at import time)."""
    import os
    import sys
    t = ctx.cfg.get("transit") or {}
    if t.get("java_home"):
        os.environ["JAVA_HOME"] = str(Path(t["java_home"]))
    if t.get("max_memory") and "--max-memory" not in sys.argv:
        sys.argv += ["--max-memory", str(t["max_memory"])]   # r5py parses known args from argv


def r5_minutes(ctx, grid, dests: pd.DataFrame) -> pd.DataFrame | None:
    configure_r5(ctx)
    try:
        import r5py
    except Exception as e:  # ImportError, or Java missing at import
        log.warning("r5py unavailable (%s); using estimated commute times", e)
        return None
    import geopandas as gpd
    refresh = ctx.wants_refresh(NAME)
    pbf = fetch.download(ctx.src["osm_pbf"], ctx.raw / "transit" / "nyc.osm.pbf", refresh)
    gtfs = [fetch.download(u, ctx.raw / "transit" / f"gtfs_{i}.zip", refresh) for i, u in enumerate(ctx.src["gtfs"])]
    log.info("building R5 transport network (first run takes a few minutes)...")
    network = r5py.TransportNetwork(str(pbf), [str(g) for g in gtfs])

    origins = gpd.GeoDataFrame({"id": grid.index.values},
                               geometry=gpd.points_from_xy(grid.x, grid.y), crs=grid.crs).to_crs(CRS_LL)
    destinations = gpd.GeoDataFrame({"id": dests.index.values},
                                    geometry=gpd.points_from_xy(dests.lon, dests.lat), crs=CRS_LL)
    kwargs = dict(
        origins=origins, destinations=destinations,
        departure=departure_time(ctx.cfg["you"].get("commute_departure")),
        departure_time_window=timedelta(minutes=(ctx.cfg.get("transit") or {}).get("departure_window_min", 60)),
        transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
        max_time=timedelta(minutes=120),
    )
    if hasattr(r5py, "TravelTimeMatrix"):          # r5py >= 0.2 / 1.x
        ttm = pd.DataFrame(r5py.TravelTimeMatrix(network, **kwargs))
    else:                                         # older API
        ttm = r5py.TravelTimeMatrixComputer(network, **kwargs).compute_travel_times()
    return ttm.pivot(index="from_id", columns="to_id", values="travel_time").reindex(grid.index)


def build(ctx) -> pd.DataFrame:
    grid = ctx.grid
    cells = geo.cell_xy(grid)
    dests = pd.DataFrame(ctx.cfg["you"]["commute_destinations"])
    dests.index = [f"d{i}" for i in range(len(dests))]
    weights = dests.get("weight", pd.Series(1.0, index=dests.index)).fillna(1.0)

    stations = subway_stations(ctx)
    out = pd.DataFrame(index=ctx.ntas.index)
    out["station_dist_m"] = geo.to_nta(grid, geo.nearest_dist(cells, stations), "station_dist_m")

    # One routing run for your destinations and the airport hubs together (R5 cost is per origin, not per target)
    hubs = pd.DataFrame([{"lat": la, "lon": lo} for _, la, lo, _ in AIRPORT_HUBS.values()],
                        index=[f"h_{h}" for h in AIRPORT_HUBS])
    targets = pd.concat([dests[["lat", "lon"]].astype(float), hubs])
    mins = r5_minutes(ctx, grid, targets)
    method = "r5py"
    if mins is None:
        method = "estimate"
        dxy = geo.to_xy(targets.lon.values, targets.lat.values)
        mins = pd.DataFrame({d: estimate_minutes(cells, stations, dxy[i]) for i, d in enumerate(targets.index)},
                            index=grid.index)
    mins = mins.reindex(columns=targets.index).fillna(120)
    air = airport_minutes(mins[hubs.index].rename(columns=lambda c: c[2:]))
    for code in air.columns:
        out[f"airport_{code}_min"] = geo.to_nta(grid, air[code], f"airport_{code}_min")
    out["airport_min"] = geo.to_nta(grid, air.mean(axis=1), "airport_min")
    active = active_destination(ctx.cfg)
    per_cell = (mins[dests.index[active]] if active is not None
                else (mins[dests.index] * weights.values).sum(axis=1) / weights.sum())
    out["commute_min"] = geo.to_nta(grid, per_cell, "commute_min")
    for d, name in zip(dests.index, dests["name"]):
        out[f"commute_min_{dest_slug(name)}"] = geo.to_nta(grid, mins[d], f"commute_min_{dest_slug(name)}")
    out["commute_method"] = method
    return out
