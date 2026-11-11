"""Safety and quiet: NYPD complaints and 311 noise complaints per 1,000 residents.

Both are counted by the NTA the incident falls in, over the last `lookback_days`,
and divided by max(population, 2,000) so near-empty NTAs don't blow up.
Felonies weigh 3, misdemeanors 1, violations 0.25.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import fetch, geo

log = logging.getLogger("stoop.safety")
POP_FLOOR = 2000
NOISE_CAP_PER_YEAR = 52   # max complaints counted per exact location (~1/week): one chronic caller can't dominate an area
LAW_WEIGHTS = {"FELONY": 3.0, "MISDEMEANOR": 1.0, "VIOLATION": 0.25}


def _cutoff(ctx) -> str:
    return (date.today() - timedelta(days=ctx.cfg.get("lookback_days", 365))).isoformat() + "T00:00:00"


def per_1k(counts: pd.Series, pop: pd.Series) -> pd.Series:
    return counts / np.maximum(pop.reindex(counts.index).fillna(0), POP_FLOOR) * 1000


def _pop(ctx) -> pd.Series:
    return pd.read_parquet(ctx.interim / "features_neighborhoods.parquet")["pop"]


def build_safety(ctx) -> pd.DataFrame:
    base, src, refresh = ctx.src["nyc_open_data"], ctx.src, ctx.wants_refresh("safety")
    where = f"cmplnt_fr_dt >= '{_cutoff(ctx)}'"
    sel = "cmplnt_fr_dt,law_cat_cd,latitude,longitude"
    frames = [fetch.socrata_rows(base, src["nypd_complaints"], ctx.raw, select=sel, where=where, refresh=refresh)]
    try:   # the YTD file only covers this year; the historic one fills the rest of the window
        frames.append(fetch.socrata_rows(base, src["nypd_complaints_historic"], ctx.raw, select=sel, where=where, refresh=refresh))
    except Exception as e:
        log.warning("historic complaints unavailable (%s); window may be shorter than lookback_days", e)
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    df["w"] = df["law_cat_cd"].map(LAW_WEIGHTS).fillna(0.5)
    for c in ["latitude", "longitude"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df.latitude.between(40.4, 41.0) & df.longitude.between(-74.3, -73.6)]
    xy = geo.to_xy(df.longitude.values, df.latitude.values)
    w = df["w"].to_numpy()
    counts = geo.count_in_nta(ctx.ntas, xy, weights=w)
    felonies = geo.count_in_nta(ctx.ntas, xy, weights=(df["law_cat_cd"] == "FELONY").astype(float).to_numpy())
    pop = _pop(ctx)
    out = pd.DataFrame(index=ctx.ntas.index)
    out["crime_weighted_per_1k"] = per_1k(counts, pop)
    out["felonies_per_1k"] = per_1k(felonies, pop)
    log.info("safety: %d complaints since %s", len(df), _cutoff(ctx)[:10])
    return out


def month_windows(start: date, end: date) -> list[tuple[date, date | None]]:
    """[start, next month start), whole calendar months..., [this month start, open end)."""
    out, lo = [], start
    while True:
        hi = (lo.replace(day=1) + timedelta(days=32)).replace(day=1)
        if hi > end:
            out.append((lo, None))
            return out
        out.append((lo, hi))
        lo = hi


def build_quiet(ctx) -> pd.DataFrame:
    # 311 is ~40M rows; one year-long query times out or gets throttled deep into paging.
    # Month-sized queries are cheap, and each is cached on its own so a rerun resumes.
    refresh = ctx.wants_refresh("quiet")
    start = date.today() - timedelta(days=ctx.cfg.get("lookback_days", 365))
    frames = []
    for lo, hi in month_windows(start, date.today()):
        where = f"created_date >= '{lo.isoformat()}T00:00:00'"
        if hi is not None:
            where += f" AND created_date < '{hi.isoformat()}T00:00:00'"
        frames.append(fetch.socrata_rows(ctx.src["nyc_open_data"], ctx.src["complaints_311"], ctx.raw,
                                         select="complaint_type,latitude,longitude",
                                         where=f"{where} AND starts_with(complaint_type, 'Noise')",
                                         refresh=refresh or hi is None))   # current month is always re-fetched
    df = pd.concat(frames, ignore_index=True)
    weights, capped = cap_repeat_locations(df, NOISE_CAP_PER_YEAR * ctx.cfg.get("lookback_days", 365) / 365)
    log.info("quiet: capped %d locations with repeat complaints (removed %.0f%% of %d complaints)",
             capped, 100 * (1 - weights.sum() / max(len(df), 1)), len(df))
    xy = geo.to_xy(weights.index.get_level_values("longitude"), weights.index.get_level_values("latitude"))
    out = pd.DataFrame(index=ctx.ntas.index)
    out["noise_per_1k"] = per_1k(geo.count_in_nta(ctx.ntas, xy, weights=weights.to_numpy()), _pop(ctx))
    return out


def cap_repeat_locations(df: pd.DataFrame, cap: float) -> tuple[pd.Series, int]:
    """Complaints per exact (lat, lon), capped at `cap` so one chronic caller can't swamp an area.

    Returns weights indexed by (latitude, longitude) for in-bounds rows, plus how many locations were capped.
    """
    d = df[["latitude", "longitude"]].apply(pd.to_numeric, errors="coerce").dropna()
    d = d[d.latitude.between(40.4, 41.0) & d.longitude.between(-74.3, -73.6)]
    n = d.groupby(["latitude", "longitude"]).size().astype(float)
    return n.clip(upper=cap), int((n > cap).sum())
