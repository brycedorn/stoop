"""Neighborhoods + population: the base table every other factor joins onto."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import geo

NAME = "neighborhoods"


def build(ctx) -> pd.DataFrame:
    ntas = ctx.ntas
    grid = ctx.grid            # builds grid + population if not cached
    tracts = geo.load_tracts(ctx)

    t = pd.DataFrame(tracts.drop(columns="geometry"))
    g = t.groupby("nta2020")
    out = pd.DataFrame(index=ntas.index)
    out["pop"] = g["pop"].sum().reindex(ntas.index).fillna(0)
    out["renter_units"] = g["renter_units"].sum().reindex(ntas.index)
    out["pop_density_km2"] = out["pop"] / ntas["land_km2"].replace(0, np.nan)

    # ACS median gross rent by bedroom count, averaged over tracts weighted by renter units.
    for col in ["rent_all", "rent_0br", "rent_1br", "rent_2br", "rent_3br"]:
        w = t["renter_units"].fillna(0)
        num = (t[col] * w).groupby(t["nta2020"]).sum(min_count=1)
        den = w.where(t[col].notna(), 0).groupby(t["nta2020"]).sum()
        out[f"acs_{col}"] = (num / den.replace(0, np.nan)).reindex(ntas.index)

    out["grid_cells"] = grid.groupby("nta2020").size().reindex(ntas.index).fillna(0)
    return out
