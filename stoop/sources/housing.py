"""Apartment size: average residential floor area per unit, from NYC PLUTO.

PLUTO (the city's tax-lot database) records residential floor area and unit count
for every lot. We total both per 2020 census tract on the server (one small query),
map tracts to NTAs, and divide. Only buildings with 3+ units count, since that's
the rental stock; one- and two-family houses would inflate outer-borough averages.

Caveats: it's gross floor area (hallways, walls, lobbies included), so real living
space is roughly 15-20% smaller; and it averages all unit types, so an area of
family-size apartments looks roomier than one of studios. Good for comparing areas,
not for quoting a specific apartment's size.

For the hex view, the same average is taken over the 3+ unit buildings around each spot (lot coordinates from
PLUTO, Gaussian over a few hundred meters), pulled toward the neighborhood's average as if PRIOR_UNITS more
apartments there had that size, so a block of a few buildings doesn't swing the number.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .. import fetch, geo

log = logging.getLogger("stoop.housing")
NAME = "housing"
PLUTO = "64uk-42ks"
BORO_COUNTY = {"1": "061", "2": "005", "3": "047", "4": "081", "5": "085"}
LOCAL_SCALE_M = 300
PRIOR_UNITS = 300


def keep_local_size(ctx, nta_sqft: pd.Series) -> None:
    """Average unit size around each grid cell, for the hex view."""
    lots = fetch.socrata_rows(ctx.src["nyc_open_data"], PLUTO, ctx.raw, select="latitude,longitude,resarea,unitsres",
                              where="unitsres >= 3 AND resarea > 0 AND latitude IS NOT NULL",
                              refresh=ctx.wants_refresh(NAME))
    for c in lots.columns:
        lots[c] = pd.to_numeric(lots[c], errors="coerce")
    lots = lots.dropna()
    xy = geo.to_xy(lots["longitude"].values, lots["latitude"].values)
    grid = ctx.grid
    area = geo.bin_to_cells(grid, xy, lots["resarea"].values)
    units = geo.bin_to_cells(grid, xy, lots["unitsres"].values)
    prior = grid["nta2020"].map(nta_sqft).fillna(float(nta_sqft.median())).values
    geo.keep_cells(grid, geo.local_ratio(grid, area, units, prior, PRIOR_UNITS, LOCAL_SCALE_M), "unit_sqft")
    log.info("housing: %d lots with 3+ units placed on the grid", len(lots))


def bct_to_geoid(bct: str) -> str | None:
    """PLUTO bct2020 ('1000201' = borough 1, tract 000201) -> Census GEOID '36061000201'."""
    s = str(bct).strip()
    if len(s) != 7 or s[0] not in BORO_COUNTY:
        return None
    return "36" + BORO_COUNTY[s[0]] + s[1:]


def build(ctx) -> pd.DataFrame:
    rows = fetch.get_json(f"{ctx.src['nyc_open_data'].rstrip('/')}/resource/{PLUTO}.json", ctx.raw,
                          "pluto_unitsize_by_tract", ctx.wants_refresh(NAME), params={
                              "$select": "bct2020, sum(resarea) as res_sqft, sum(unitsres) as units",
                              "$where": "unitsres >= 3 AND resarea > 0",
                              "$group": "bct2020", "$limit": 50000})
    df = pd.DataFrame(rows)
    df["geoid"] = df["bct2020"].map(bct_to_geoid)
    for c in ["res_sqft", "units"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    tracts = pd.DataFrame(geo.load_tracts(ctx)[["geoid", "nta2020"]])
    df = df.merge(tracts, on="geoid", how="inner")
    g = df.groupby("nta2020")[["res_sqft", "units"]].sum()
    out = pd.DataFrame(index=ctx.ntas.index)
    # need a few hundred units for a stable average
    out["unit_sqft"] = (g["res_sqft"] / g["units"]).where(g["units"] >= 200).reindex(ctx.ntas.index)
    try:
        keep_local_size(ctx, out["unit_sqft"])
    except Exception as e:   # the hex view falls back to the neighborhood's size
        log.warning("housing: no per-spot sizes (%s)", e)
    log.info("housing: %d tracts matched, %d NTAs with unit size, city mean %.0f sq ft",
             len(df), out["unit_sqft"].notna().sum(), df["res_sqft"].sum() / max(df["units"].sum(), 1))
    return out
