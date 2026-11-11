"""Familiarity: closeness to neighborhoods you've spent time in and liked.

List them in config.yaml under you.liked_neighborhoods, by NTA name ("Greenpoint"),
a piece of one ("Ditmas Park" finds "Flatbush (West)-Ditmas Park-Parkville") or an NTA
code ("BK0101"). Inside a liked area the distance is 0; elsewhere it's the
straight-line distance from each grid cell to the nearest liked area, averaged over
residents. Scored with an absolute curve (scoring.familiar_curve): areas next door get
partial credit, which captures "I know this part of town".
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .. import geo
from .rent import _norm, nta_name_variants

log = logging.getLogger("stoop.familiarity")
NAME = "familiarity"


def match_liked(ntas: pd.DataFrame, liked: list[str]) -> list[str]:
    """NTA codes for each liked entry: exact code, else exact name, else a name piece."""
    codes = []
    names = ntas["name"].astype(str)
    for entry in liked:
        e = str(entry).strip()
        if e.upper() in ntas.index:
            hit = [e.upper()]
        else:
            hit = list(ntas.index[names.map(_norm) == _norm(e)])
            if not hit:
                hit = [i for i, n in names.items() if _norm(e) in nta_name_variants(n)]
        if not hit:
            log.warning("liked neighborhood %r matches no NTA name; check data/interim/neighborhood_scores.csv", e)
        codes += [h for h in hit if h not in codes]
    return codes


def build(ctx) -> pd.DataFrame:
    liked = ctx.cfg["you"].get("liked_neighborhoods") or []
    out = pd.DataFrame(index=ctx.ntas.index)
    codes = match_liked(ctx.ntas, liked)
    if not codes:
        log.warning("no liked_neighborhoods in config.yaml: familiarity has no data")
        return out
    import shapely
    grid = ctx.grid
    area = ctx.ntas.loc[codes].geometry.union_all()
    d = shapely.distance(shapely.points(geo.cell_xy(grid)), area)
    d = np.where(grid["nta2020"].isin(codes).to_numpy(), 0.0, d)
    out["familiar_dist_m"] = geo.to_nta(grid, d, "familiar_dist_m")
    out.loc[codes, "familiar_dist_m"] = 0.0
    log.info("familiarity: %s", ", ".join(f"{c} {ctx.ntas.at[c, 'name']}" for c in codes))
    return out
