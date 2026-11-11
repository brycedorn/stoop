"""Green space: park area and street trees within walking distance."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .. import fetch, geo
from ..context import CRS_M

log = logging.getLogger("stoop.green")
NAME = "green"

# Parks Properties "typecategory" values that aren't real green space to spend time in
NOT_GREEN = {"Strip", "Mall", "Parkway", "Triangle/Plaza", "Lot", "Undeveloped", "Retired N/A"}


def load_parks(ctx, refresh: bool = False):
    import geopandas as gpd
    cache = ctx.interim / "parks.parquet"
    if cache.exists() and not refresh:
        return gpd.read_parquet(cache)
    p = gpd.read_file(fetch.socrata_geojson(ctx.src["nyc_open_data"], ctx.src["parks"], ctx.raw, refresh))
    p.columns = [c.lower() for c in p.columns]
    if "typecategory" in p.columns:
        p = p[~p["typecategory"].isin(NOT_GREEN)]
    p = p.to_crs(CRS_M)
    p["geometry"] = p.geometry.make_valid()
    p["acres_calc"] = p.geometry.area / 4046.86
    keep = [c for c in ["signname", "typecategory", "acres_calc", "geometry"] if c in p.columns]
    p = p[keep]
    p.to_parquet(cache)
    return p


def build(ctx) -> pd.DataFrame:
    grid, refresh = ctx.grid, ctx.wants_refresh(NAME)
    r = ctx.cfg.get("walk_radius_m", 1000)
    cells = geo.cell_xy(grid)

    parks = load_parks(ctx, refresh)
    frac = geo.area_fraction(grid, parks)
    cell_ha = grid.geometry.area.iloc[0] / 1e4
    park_ha = geo.grid_neighbor_sum(grid, frac * cell_ha, r)

    trees = fetch.socrata_rows(ctx.src["nyc_open_data"], ctx.src["street_trees"], ctx.raw,
                               select="latitude,longitude", where="status='Alive'", refresh=refresh)
    tree_xy = geo.df_xy(trees)
    trees_300 = geo.sum_within(cells, tree_xy, 300)

    out = pd.DataFrame(index=ctx.ntas.index)
    out["park_ha_walk"] = geo.to_nta(grid, park_ha, "park_ha_walk")
    out["trees_300m"] = geo.to_nta(grid, trees_300, "trees_300m")
    out["park_share"] = geo.to_nta(grid, frac.values, "park_share")
    log.info("green: %d park polygons, %d trees", len(parks), len(tree_xy))
    return out
