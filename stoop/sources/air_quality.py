"""Air quality (detail panel only, not scored): annual mean PM2.5 and NO2 by community district.

Source: NYC Health's Environment & Health Data Portal (EHDP), which publishes the NYC Community
Air Survey (NYCCAS) estimates as JSON in github.com/nychealth/EHDP-data. Updated yearly; the latest
year is used. The finest current geography is the community district (59 citywide), so every NTA
in a district gets the same value. Fine for "this part of the city has dirtier air", not for
block-level differences such as living next to a highway.

Join: a 2020 NTA code starts with its community district ("BK0101" -> Brooklyn CD 1), and EHDP
numbers districts borough*100 + district ("301"). Parks, airports and other non-residential
NTAs (district 26+) have no match and stay empty.
"""
from __future__ import annotations

import logging

import pandas as pd

from .. import fetch

log = logging.getLogger("stoop.air_quality")
NAME = "air_quality"
DEFAULT_BASE = "https://raw.githubusercontent.com/nychealth/EHDP-data/production/indicators"
BORO_NUM = {"MN": 1, "BX": 2, "BK": 3, "QN": 4, "SI": 5}
# column -> (EHDP indicator file, measure id of the annual mean)
MEASURES = {
    "pm25_ugm3": (2023, 1425),   # Fine particles (PM2.5), annual mean, µg/m³
    "no2_ppb": (2025, 1431),     # Nitrogen dioxide, annual mean, ppb
}


def nta_to_cd(nta: str) -> int | None:
    """'BK0101' -> 301 (EHDP community district id); None if not a regular district."""
    s = str(nta)
    if len(s) < 4 or s[:2] not in BORO_NUM or not s[2:4].isdigit():
        return None
    cd = int(s[2:4])
    return BORO_NUM[s[:2]] * 100 + cd if 1 <= cd <= 18 else None


def latest_cd_values(data: dict, measure_id: int, periods: dict) -> tuple[str, dict[int, float]]:
    """EHDP column-oriented indicator JSON -> (latest annual period label, {district id: value})."""
    rows = pd.DataFrame({k: data[k] for k in ("MeasureID", "GeoID", "GeoType", "TimePeriodID", "Value")})
    rows = rows[(rows["MeasureID"] == measure_id) & (rows["GeoType"] == "CD")]
    rows = rows[rows["TimePeriodID"].map(lambda t: periods.get(t, {}).get("TimeType") == "year")]
    if rows.empty:
        raise ValueError(f"EHDP measure {measure_id} has no annual community-district values")
    last = max(rows["TimePeriodID"], key=lambda t: periods[t]["TimePeriod"])
    rows = rows[rows["TimePeriodID"] == last].dropna(subset=["Value"])
    return periods[last]["TimePeriod"], {int(g): float(v) for g, v in zip(rows["GeoID"], rows["Value"])}


def build(ctx) -> pd.DataFrame:
    base = ctx.src.get("ehdp_data", DEFAULT_BASE).rstrip("/")
    refresh = ctx.wants_refresh(NAME)
    periods = {int(p["TimePeriodID"]): p for p in
               fetch.get_json(f"{base}/metadata/TimePeriods.json", ctx.raw, "ehdp_time_periods", refresh)}
    cds = pd.Series({nta: nta_to_cd(nta) for nta in ctx.ntas.index})
    out = pd.DataFrame(index=ctx.ntas.index)
    for col, (indicator, measure) in MEASURES.items():
        data = fetch.get_json(f"{base}/data/{indicator}.json", ctx.raw, f"ehdp_{indicator}", refresh)
        year, values = latest_cd_values(data, measure, periods)
        out[col] = cds.map(values).astype(float)
        log.info("air quality: %s %s for %d districts, %d NTAs filled", col, year, len(values), out[col].notna().sum())
    return out
