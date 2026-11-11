"""Apartment size: average residential floor area per unit, from NYC PLUTO.

PLUTO (the city's tax-lot database) records residential floor area and unit count
for every lot. We total both per 2020 census tract on the server (one small query),
map tracts to NTAs, and divide. Only buildings with 3+ units count, since that's
the rental stock; one- and two-family houses would inflate outer-borough averages.

Caveats: it's gross floor area (hallways, walls, lobbies included), so real living
space is roughly 15-20% smaller; and it averages all unit types, so an area of
family-size apartments looks roomier than one of studios. Good for comparing areas,
not for quoting a specific apartment's size.
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
    log.info("housing: %d tracts matched, %d NTAs with unit size, city mean %.0f sq ft",
             len(df), out["unit_sqft"].notna().sum(), df["res_sqft"].sum() / max(df["units"].sum(), 1))
    return out
