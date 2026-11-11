"""Errands, Citi Bike, and flood risk."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .. import fetch, geo, osm

log = logging.getLogger("stoop.convenience")

ERRAND_TAGS = {"shop": ["supermarket", "greengrocer", "laundry", "dry_cleaning"],
               "amenity": ["pharmacy"], "leisure": ["fitness_centre"]}
# category -> (how to pick it out, importance). Score uses distance to the nearest one.
# Gyms moved to their own factor (full-size gyms only); any fitness centre is still reported as nearest_gym_m.
ERRAND_KINDS = {
    "supermarket": (lambda g: g.get("shop").isin(["supermarket", "greengrocer"]), 2.0),
    "pharmacy": (lambda g: g.get("amenity").eq("pharmacy"), 1.0),
    "laundry": (lambda g: g.get("shop").isin(["laundry", "dry_cleaning"]), 0.5),
}
INFO_ONLY_KINDS = {"gym": lambda g: g.get("leisure").eq("fitness_centre")}

# Full-size gyms: chains whose NYC locations are full gyms (weights, cardio floor, locker rooms), plus YMCAs, JCCs
# and NYC Parks recreation centers. OSM has footprints for only ~5% of gyms, so size can't come from area. Boutique
# studios (Orangetheory, SoulCycle, Barry's, Pilates/yoga, CrossFit boxes) don't count.
# (pattern in the lowercased name, brand shown on the map)
GYM_CHAINS = [
    ("equinox", "Equinox"), ("planet fitness", "Planet Fitness"), ("blink", "Blink Fitness"),
    ("crunch", "Crunch Fitness"), ("new york sports club", "New York Sports Club"), ("nysc", "New York Sports Club"),
    ("retro fitness", "Retro Fitness"), ("puregym", "PureGym"), ("pure gym", "PureGym"), ("harbor fitness", "Harbor Fitness"),
    ("la fitness", "LA Fitness"), ("life time", "Life Time"), ("lifetime", "Life Time"), ("24 hour fitness", "24 Hour Fitness"),
    ("chelsea piers", "Chelsea Piers Fitness"), ("synergy fitness", "Synergy Fitness"), ("intoxx", "Intoxx Fitness"),
    ("lucille roberts", "Lucille Roberts"), ("gold's gym", "Gold's Gym"), ("golds gym", "Gold's Gym"),
    ("edge fitness", "The Edge Fitness Clubs"), ("level fitness", "Level Fitness"), ("complete body", "Complete Body"),
    ("dolphin fitness", "Dolphin Fitness"), ("tmpl", "TMPL"), ("asphalt green", "Asphalt Green"),
    ("ymca", "YMCA"), ("92ny", "92NY"), ("92nd street y", "92NY"), ("jcc", "JCC"),
    ("recreation center", "NYC Parks recreation center"), ("rec center", "NYC Parks recreation center"),
]
GYM_RADIUS_M = 1000   # "how many full-size gyms within a walk"


def gym_brand(name) -> str | None:
    """Brand of a full-size gym (e.g. 'Equinox'), or None for boutique studios and unknown gyms."""
    n = "" if name is None or (not isinstance(name, str) and pd.isna(name)) else str(name).lower()
    return next((brand for pat, brand in GYM_CHAINS if pat in n), None)


def big_gyms(ctx, refresh: bool = False) -> pd.DataFrame:
    """Full-size gyms from OSM: x, y (meters), name, brand."""
    g = osm.features(ctx, ERRAND_TAGS, "errands", refresh)
    g = g[osm.in_nyc(ctx, g)]   # only gyms in the five boroughs
    if "leisure" not in g.columns:
        return pd.DataFrame(columns=["x", "y", "name", "brand"])
    gy = g[g["leisure"].eq("fitness_centre").fillna(False).astype(bool)].copy()
    gy["brand"] = [gym_brand(n) for n in gy["name"]]
    gy = gy[gy["brand"].notna()]
    xy = osm.point_xy(gy)
    out = pd.DataFrame({"x": xy[:, 0], "y": xy[:, 1], "name": gy["name"].astype(str).values, "brand": gy["brand"].values})
    out = out.drop_duplicates(subset=["brand", "x", "y"])
    return out


def build_gyms(ctx) -> pd.DataFrame:
    grid = ctx.grid
    cells = geo.cell_xy(grid)
    gyms = big_gyms(ctx, ctx.wants_refresh("gyms"))
    xy = gyms[["x", "y"]].to_numpy(float)
    out = pd.DataFrame(index=ctx.ntas.index)
    out["nearest_gym_full_m"] = geo.to_nta(grid, geo.nearest_dist(cells, xy), "nearest_gym_full_m")
    out["gyms_walk"] = geo.to_nta(grid, geo.sum_within(cells, xy, GYM_RADIUS_M), "gyms_walk")
    log.info("gyms: %d full-size gyms (%s)", len(gyms), ", ".join(f"{b} {n}" for b, n in gyms["brand"].value_counts().head(6).items()))
    return out
ERRAND_DECAY_M = 400   # nearest at 0 m -> 1.0, at 400 m -> 0.37


def build_errands(ctx) -> pd.DataFrame:
    grid = ctx.grid
    cells = geo.cell_xy(grid)
    g = osm.features(ctx, ERRAND_TAGS, "errands", ctx.wants_refresh("errands"))
    g = g[osm.in_nyc(ctx, g)]   # a store across the city line doesn't count
    for c in ["shop", "amenity", "leisure"]:
        if c not in g.columns:
            g[c] = pd.NA
    out = pd.DataFrame(index=ctx.ntas.index)
    total, wsum = np.zeros(len(cells)), 0.0
    for kind, (sel, w) in ERRAND_KINDS.items():
        sub = g[sel(g).fillna(False).astype(bool)]
        d = geo.nearest_dist(cells, osm.point_xy(sub))
        out[f"nearest_{kind}_m"] = geo.to_nta(grid, d, f"nearest_{kind}_m")
        if len(sub):
            total += w * np.exp(-np.nan_to_num(d, nan=1e5) / ERRAND_DECAY_M)
            wsum += w
    for kind, sel in INFO_ONLY_KINDS.items():
        sub = g[sel(g).fillna(False).astype(bool)]
        out[f"nearest_{kind}_m"] = geo.to_nta(grid, geo.nearest_dist(cells, osm.point_xy(sub)), f"nearest_{kind}_m")
    out["errands_score"] = geo.to_nta(grid, total / wsum if wsum else total, "errands_score")
    return out


def build_citibike(ctx) -> pd.DataFrame:
    data = fetch.get_json(ctx.src["citibike_stations"], ctx.raw, "citibike_stations", ctx.wants_refresh("citibike"))
    st = pd.DataFrame(data["data"]["stations"])
    xy = geo.df_xy(st, lon="lon", lat="lat")
    cells = geo.cell_xy(ctx.grid)
    out = pd.DataFrame(index=ctx.ntas.index)
    out["citibike_400m"] = geo.to_nta(ctx.grid, geo.sum_within(cells, xy, 400), "citibike_400m")
    out["citibike_dist_m"] = geo.to_nta(ctx.grid, geo.nearest_dist(cells, xy), "citibike_dist_m")
    log.info("citibike: %d stations", len(st))
    return out


def build_flood(ctx) -> pd.DataFrame:
    import geopandas as gpd
    refresh = ctx.wants_refresh("flood")
    layers = []
    try:
        layers.append(gpd.read_file(fetch.arcgis_geojson(ctx.src["stormwater_flood_arcgis"], ctx.raw, refresh)))
    except Exception as e:
        log.warning("stormwater flood map unavailable: %s", e)
    try:
        layers.append(gpd.read_file(fetch.socrata_geojson(ctx.src["nyc_open_data"], ctx.src["sandy_inundation"], ctx.raw, refresh)))
    except Exception as e:
        log.warning("Sandy inundation zone unavailable: %s", e)
    if not layers:
        raise RuntimeError("no flood layers could be loaded")
    polys = pd.concat([l[["geometry"]].to_crs(4326) for l in layers], ignore_index=True)
    frac = geo.area_fraction(ctx.grid, gpd.GeoDataFrame(polys, crs=4326))
    out = pd.DataFrame(index=ctx.ntas.index)
    out["flood_share"] = geo.to_nta(ctx.grid, frac.values, "flood_share")
    return out
