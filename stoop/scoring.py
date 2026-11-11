"""Turn raw neighborhood metrics into 0-100 factor scores.

Pure pandas/numpy (no geo dependencies) so it's easy to unit-test.

Two kinds of scoring:
- percentile: rank among residential NTAs; 100 = best in the city.
- absolute: a fixed curve where the number itself matters (rent vs your
  budget, minutes of commute, share of land that floods).
A factor with several components averages them by weight, skipping any
component that's missing for that neighborhood.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# (column, direction or curve, weight). direction +1 = higher is better, -1 = lower is better.
FACTORS: dict[str, dict] = {
    "running": {
        "label": "Running",
        "help": "Dedicated paths within ~1 km, distance to a 20+ acre park, and where you actually run (your GPS files).",
        "components": [("run_path_m", +1, 0.45), ("big_park_dist_m", -1, 0.20), ("activity_density", +1, 0.35)],
    },
    # Your bars & restaurants are shown on the map as context, not scored. The favorites step
    # still geocodes them and computes fav_score / food_drink_600m as raw numbers for the detail panel.
    "size": {
        "label": "Apartment size",
        "help": "Average floor area per apartment in 3+ unit buildings (NYC PLUTO). Gross area, so real rooms are ~15-20% smaller.",
        "components": [("unit_sqft", +1, 1.0)],
    },
    "commute": {
        "label": "Commute",
        "help": "Door-to-door transit time to your destination(s): 20 min or less = 100, 75+ min = 0.",
        "components": [("commute_min", "commute", 0.85), ("station_dist_m", -1, 0.15)],
    },
    "rent": {
        "label": "Rent fit",
        "help": "Median asking rent vs your budget: ≤70% of budget = 100, at budget = 50, 15% over = 0.",
        "components": [("rent_est", "rent", 1.0)],
    },
    "safety": {
        "label": "Safety",
        "help": "NYPD complaints per 1,000 residents over the last year (felonies weighted ×3).",
        "components": [("crime_weighted_per_1k", -1, 1.0)],
    },
    "quiet": {
        "label": "Quiet",
        "help": "311 noise complaints per 1,000 residents over the last year.",
        "components": [("noise_per_1k", -1, 1.0)],
    },
    "green": {
        "label": "Green space",
        "help": "Park area within walking distance and street trees on nearby blocks.",
        "components": [("park_ha_walk", +1, 0.6), ("trees_300m", +1, 0.4)],
    },
    "errands": {
        "label": "Daily errands",
        "help": "Distance to the nearest supermarket, pharmacy and laundromat.",
        "components": [("errands_score", +1, 1.0)],
    },
    "gym": {
        "label": "Gyms",
        "help": "Full-size gyms (Equinox, Planet Fitness, Blink, Crunch, NYSC, YMCA, Parks rec centers…), not boutique studios: "
                "nearest within 400 m = 100, 2 km+ = 0; plus how many are within ~1 km.",
        "components": [("nearest_gym_full_m", "gym", 0.75), ("gyms_walk", +1, 0.25)],
    },
    "airports": {
        "label": "Airports",
        "help": "Transit time to JFK, LaGuardia and Newark, averaged: 55 min or less = 100, 115+ min = 0. "
                "JFK via the AirTrain (Jamaica or Howard Beach), Newark via NJ Transit from Penn Station.",
        "components": [("airport_min", "airport", 1.0)],
    },
    "citibike": {
        "label": "Citi Bike",
        "help": "Citi Bike docks within 400 m.",
        "components": [("citibike_400m", +1, 0.7), ("citibike_dist_m", -1, 0.3)],
    },
    "flood": {
        "label": "Flood safety",
        "help": "Share of the area in modeled stormwater-flood or Sandy-inundation zones: 0% = 100, 30%+ = 0.",
        "components": [("flood_share", "flood", 1.0)],
    },
    "space": {
        "label": "Breathing room",
        "help": "Lower population density. Leave at 0 if you don't mind crowds.",
        "components": [("pop_density_km2", -1, 1.0)],
    },
    "runhex": {
        "label": "Runner traffic (hex data)",
        "help": "Runner traffic by hex (0-5) from your runner-hex data file: the busiest few within ~1 km. "
                "No hex nearby = no data.",
        "components": [("runhex_score", "abs", 1.0)],
    },
    "run5k": {
        "label": "5K routes",
        "help": "Walk to the nearest car-free route long enough for a 5K: park loops, greenways, waterfront paths "
                "(OpenStreetMap). 5 min or less = 100, 30+ min = 0.",
        "components": [("run5k_score", "abs", 1.0)],
    },
    "familiarity": {
        "label": "Familiar areas",
        "help": "Neighborhoods you've visited and liked (config: liked_neighborhoods) = 100; ~1 km away ≈ 65, ~2 km ≈ 15.",
        "components": [("familiar_dist_m", "familiar", 1.0)],
    },
}


# --- Curves (mirrored in web/app.js) ---------------------------------------

COMMUTE_GOOD_MIN, COMMUTE_BAD_MIN = 20, 75   # 100 at or under GOOD, 0 at or over BAD


def commute_curve(minutes):
    m = np.asarray(minutes, float)
    return np.clip((COMMUTE_BAD_MIN - m) / (COMMUTE_BAD_MIN - COMMUTE_GOOD_MIN), 0, 1) * 100


def rent_curve(rent, budget: float):
    r = np.asarray(rent, float) / float(budget)
    s = np.where(r <= 0.7, 100.0,
        np.where(r <= 1.0, 100 - (r - 0.7) / 0.3 * 50,
        np.where(r <= 1.15, 50 - (r - 1.0) / 0.15 * 50, 0.0)))
    return np.where(np.isnan(r), np.nan, s)


def flood_curve(share):
    s = np.asarray(share, float)
    return np.clip(1 - s / 0.30, 0, 1) * 100


AIRPORT_GOOD_MIN, AIRPORT_BAD_MIN = 55, 115   # average of the three airports; routed range is 55 (Jackson Hts) to ~136


def airport_curve(minutes):
    m = np.asarray(minutes, float)
    return np.clip((AIRPORT_BAD_MIN - m) / (AIRPORT_BAD_MIN - AIRPORT_GOOD_MIN), 0, 1) * 100


GYM_GOOD_M, GYM_BAD_M = 400, 2000   # 100 within a 5-min walk, 0 beyond ~25 min


def gym_curve(dist_m):
    d = np.asarray(dist_m, float)
    return np.clip((GYM_BAD_M - d) / (GYM_BAD_M - GYM_GOOD_M), 0, 1) * 100


RUN5K_GOOD_MIN, RUN5K_BAD_MIN = 5, 30   # walking minutes to a popular 5K route (you'd jog it in about half)


def run5k_curve(minutes):
    m = np.asarray(minutes, float)
    return np.clip((RUN5K_BAD_MIN - m) / (RUN5K_BAD_MIN - RUN5K_GOOD_MIN), 0, 1) * 100


FAMILIAR_SCALE_M = 1500


def familiar_curve(dist_m):
    """100 inside a liked area, Gaussian falloff with distance (1 km ≈ 64, 2 km ≈ 17)."""
    d = np.asarray(dist_m, float)
    return 100 * np.exp(-(d / FAMILIAR_SCALE_M) ** 2)


def percentile(values: pd.Series, mask: pd.Series, direction: int) -> pd.Series:
    """0-100 percentile among rows where `mask` is True (ties share a rank)."""
    v = values.where(mask)
    n = v.notna().sum()
    if n <= 1:
        return pd.Series(np.where(v.notna(), 50.0, np.nan), index=values.index)
    r = v.rank(method="average", ascending=direction > 0)
    return (r - 1) / (n - 1) * 100


def component_score(features: pd.DataFrame, col: str, how, mask: pd.Series, cfg: dict) -> pd.Series | None:
    if col not in features.columns or features[col].notna().sum() == 0:
        return None
    v = pd.to_numeric(features[col], errors="coerce")
    if how == "commute":
        return pd.Series(commute_curve(v), index=v.index)
    if how == "rent":
        return pd.Series(rent_curve(v, cfg["you"]["max_rent"]), index=v.index)
    if how == "flood":
        return pd.Series(flood_curve(v), index=v.index)
    if how == "familiar":
        return pd.Series(familiar_curve(v), index=v.index)
    if how == "gym":
        return pd.Series(gym_curve(v), index=v.index)
    if how == "abs":          # already 0-100
        return v.clip(0, 100)
    if how == "airport":
        return pd.Series(airport_curve(v), index=v.index)
    return percentile(v, mask, int(how))


def score_table(features: pd.DataFrame, cfg: dict, residential: pd.Series | None = None) -> pd.DataFrame:
    """Factor scores (0-100, NaN = no data) for every row of `features`."""
    mask = residential if residential is not None else pd.Series(True, index=features.index)
    out = pd.DataFrame(index=features.index)
    for name, spec in FACTORS.items():
        num = pd.Series(0.0, index=features.index)
        den = pd.Series(0.0, index=features.index)
        for col, how, w in spec["components"]:
            s = component_score(features, col, how, mask, cfg)
            if s is None:
                continue
            has = s.notna()
            num += s.fillna(0) * w
            den += has * w
        out[name] = (num / den.replace(0, np.nan)).round(1)
    return out


def percentile_against(values, ref: pd.Series, direction: int) -> np.ndarray:
    """0-100 for each value by where it falls among `ref` (residential neighborhoods), interpolated, so a cell
    scores like a neighborhood with the same value would. Outside the neighborhood range = 0 or 100."""
    r = pd.to_numeric(ref, errors="coerce").dropna()
    v = np.asarray(values, float)
    if len(r) <= 1:
        return np.where(np.isnan(v), np.nan, 50.0)
    xs = np.sort(r.values)
    ranks = (pd.Series(xs).rank(method="average").values - 1) / (len(xs) - 1) * 100
    xs, idx = np.unique(xs, return_index=True)          # ties share their average rank
    s = np.interp(v, xs, ranks[idx]) if len(xs) > 1 else np.full(len(v), 50.0)
    s = s if direction > 0 else 100 - s
    return np.where(np.isnan(v), np.nan, s)


def score_cells(cells: pd.DataFrame, cell_nta: pd.Series, features: pd.DataFrame, scores: pd.DataFrame,
                cfg: dict, residential: pd.Series) -> tuple[pd.DataFrame, list[str]]:
    """Factor scores (0-100) for each grid cell, on the same scale as the neighborhoods.

    A component the cell has its own value for is scored like score_table scores it, with percentiles taken
    against the residential neighborhoods; a component it doesn't have (rent, crime per resident...) uses its
    neighborhood's component score. Returns the scores and the factors that are entirely neighborhood-wide."""
    mask = residential.reindex(features.index).fillna(False).astype(bool)
    out = pd.DataFrame(index=cells.index)
    inherited = []
    for name, spec in FACTORS.items():
        num = pd.Series(0.0, index=cells.index)
        den = pd.Series(0.0, index=cells.index)
        own = False
        for col, how, w in spec["components"]:
            if col in cells.columns and cells[col].notna().any():
                own = True
                v = pd.to_numeric(cells[col], errors="coerce")
                if how in ("+1", "-1") or isinstance(how, int):
                    ref = pd.to_numeric(features[col], errors="coerce").where(mask) if col in features else pd.Series(dtype=float)
                    s = pd.Series(percentile_against(v, ref, int(how)), index=cells.index)
                else:
                    s = component_score(pd.DataFrame({col: v}), col, how, pd.Series(True, index=cells.index), cfg)
            else:
                nta_s = component_score(features, col, how, mask, cfg)
                if nta_s is None:
                    continue
                s = pd.Series(cell_nta.map(nta_s).values, index=cells.index, dtype=float)
            if s is None:
                continue
            has = s.notna()
            num += s.fillna(0) * w
            den += has * w
        out[name] = (num / den.replace(0, np.nan)).round(1)
        if not own:
            out[name] = pd.Series(cell_nta.map(scores[name]).values, index=cells.index) if name in scores else np.nan
            inherited.append(name)
    return out, inherited


def total_score(scores: pd.DataFrame, weights: dict) -> pd.Series:
    """Weighted mean across factors, renormalized over factors with data."""
    w = pd.Series({k: float(v) for k, v in weights.items() if k in scores.columns and v})
    if w.empty:
        return pd.Series(np.nan, index=scores.index)
    s = scores[w.index]
    num = (s.fillna(0) * w).sum(axis=1)
    den = (s.notna() * w).sum(axis=1)
    return (num / den.replace(0, np.nan)).round(1)
