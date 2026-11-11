"""Write the web payload (web/data/stoop.js + .json) and a QA report."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .scoring import FACTORS, total_score

# Raw metrics shown in the detail panel: column -> (label, unit/format)
METRICS = {
    "rent_est": ("Median rent (est.)", "usd"),
    "rent_source": ("Rent source", "text"),
    "unit_sqft": ("Avg apartment size (gross)", "sqft"),
    "commute_min": ("Commute", "min"),
    "commute_method": ("Commute method", "text"),
    "station_dist_m": ("Nearest subway", "m"),
    "airport_min": ("Airports, average", "min"),
    "airport_jfk_min": ("To JFK", "min"),
    "airport_lga_min": ("To LaGuardia", "min"),
    "airport_ewr_min": ("To Newark", "min"),
    "car_jfk_min": ("JFK by car, no traffic", "min"),
    "car_lga_min": ("LaGuardia by car, no traffic", "min"),
    "car_ewr_min": ("Newark by car, no traffic", "min"),
    "run_path_m": ("Run paths within walk", "km"),
    "big_park_dist_m": ("Nearest 20+ acre park", "m"),
    "activity_density": ("Your runs nearby (GPS files)", "num"),
    "run5k_min": ("Walk to a car-free 5K route", "min"),
    "run5k_route": ("Nearest 5K route", "text"),
    "fav_within_walk": ("Your places within walk", "int"),
    "food_drink_600m": ("Bars/restaurants within 600 m", "int"),
    "crime_weighted_per_1k": ("Crime index per 1k", "num"),
    "felonies_per_1k": ("Felonies per 1k", "num"),
    "noise_per_1k": ("Noise complaints per 1k", "num"),
    "park_ha_walk": ("Park within walk", "ha"),
    "trees_300m": ("Street trees within 300 m", "int"),
    "nearest_supermarket_m": ("Nearest supermarket", "m"),
    "nearest_gym_full_m": ("Nearest full-size gym", "m"),
    "gyms_walk": ("Full-size gyms within 1 km", "int"),
    "nearest_gym_m": ("Nearest gym or studio", "m"),
    "citibike_400m": ("Citi Bike docks within 400 m", "int"),
    "flood_share": ("Area in flood zones", "pct"),
    "pm25_ugm3": ("Fine particles PM2.5, µg/m³ (district avg)", "num"),
    "no2_ppb": ("Nitrogen dioxide NO₂, ppb (district avg)", "num"),
    "familiar_dist_m": ("Distance to an area you liked", "m"),
    "pop": ("Population", "int"),
    "pop_density_km2": ("People per km²", "int"),
}


def _active_destination(cfg) -> int | None:
    from .sources.commute import active_destination
    return active_destination(cfg)


def _commute_model() -> dict:
    """Constants the map needs to re-estimate commutes live (single source: commute.py / scoring.py)."""
    from .scoring import COMMUTE_BAD_MIN, COMMUTE_GOOD_MIN
    from .sources import commute as c
    return {"walk_m_per_min": c.WALK_M_PER_MIN, "subway_m_per_min": c.SUBWAY_M_PER_MIN, "wait_min": c.WAIT_MIN,
            "detour": c.DETOUR, "curve_good": COMMUTE_GOOD_MIN, "curve_bad": COMMUTE_BAD_MIN,
            "weights": {col: w for col, _, w in FACTORS["commute"]["components"]}}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) else round(float(v), 2)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def build_payload(table: pd.DataFrame, scores: pd.DataFrame, geometries: dict, cfg: dict,
                  labels: dict | None = None, stations: list | None = None) -> dict:
    """table: index nta2020 with name, borough, ntatype + metric columns.
    geometries: {nta2020: GeoJSON geometry dict (WGS84)}.
    labels: optional {nta2020: [lon, lat]} point guaranteed inside the polygon (map rank badges)."""
    from .sources.commute import dest_slug
    labels = labels or {}
    weights = cfg["default_weights"]
    dest_cols = [f"commute_min_{dest_slug(d.get('name', ''))}" for d in cfg["you"]["commute_destinations"]]
    has_dest_cols = any(c in table.columns for c in dest_cols)
    total = total_score(scores, weights)
    feats = []
    for nta, row in table.iterrows():
        if nta not in geometries:
            continue
        feats.append({
            "type": "Feature",
            "id": len(feats),
            "geometry": geometries[nta],
            "properties": {
                "id": nta,
                "name": row.get("name"),
                "borough": row.get("borough"),
                "residential": str(row.get("ntatype")) == "0",
                "label": labels.get(nta),
                "scores": {k: _clean(scores.at[nta, k]) for k in scores.columns},
                "total_default": _clean(total.get(nta)),
                "metrics": {k: _clean(row.get(k)) for k in METRICS if k in table.columns},
                # rent by bedroom count ("0".."3"), so the map can switch bedrooms live
                "rents": {str(b): _clean(row.get(f"rent_est_{b}br")) for b in range(4) if f"rent_est_{b}br" in table.columns},
                "rent_sources": {str(b): _clean(row.get(f"rent_source_{b}br")) for b in range(4)
                                 if f"rent_source_{b}br" in table.columns},
                # minutes to each configured destination, in config order (lets the map toggle
                # destinations exactly, and calibrate its estimate when you move a pin)
                "commutes": [_clean(row.get(c)) if c in table.columns else None for c in dest_cols] if has_dest_cols else None,
            },
        })
    present = {k for f in feats for k, v in f["properties"]["scores"].items() if v is not None}
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "budget": cfg["you"]["max_rent"],
            "bedrooms": cfg["you"].get("bedrooms", 1),
            "exclude_boroughs": cfg["you"].get("exclude_boroughs", []),
            "destinations": cfg["you"]["commute_destinations"],
            "commute_to": _active_destination(cfg),   # index of the one destination commute is scored to
            "liked_neighborhoods": cfg["you"].get("liked_neighborhoods") or [],   # default center of the map's area filter
            # [lon, lat] subway stations: lets the map re-estimate commutes when a destination moves
            "stations": stations or [],
            "commute_model": _commute_model(),
            "weights": {k: v for k, v in weights.items()} | {k: 0 for k in FACTORS if k not in weights},
            "factors": {k: {"label": v["label"], "help": v["help"], "available": k in present}
                        for k, v in FACTORS.items()},
            "metrics": {k: {"label": l, "fmt": f} for k, (l, f) in METRICS.items()},
        },
        "geojson": {"type": "FeatureCollection", "features": feats},
    }


def write_airport_routes(table: pd.DataFrame, web_dir: Path) -> Path | None:
    """web/data/airports.js: {nta: {jfk: route card, lga: ..., ewr: ...}} for the map's airport markers."""
    cols = [c for c in table.columns if c.startswith("air_route_")]
    if not cols:
        return None
    data = {}
    for nta, row in table[cols].iterrows():
        cards = {c[len("air_route_"):]: json.loads(v) for c, v in row.items() if isinstance(v, str) and v}
        if cards:
            data[nta] = cards
    out = Path(web_dir) / "data" / "airports.js"
    out.write_text("window.STOOP_AIRPORTS=" + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    return out


def write_payload(payload: dict, web_dir: Path) -> Path:
    out = Path(web_dir) / "data"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    (out / "stoop.json").write_text(text, encoding="utf-8")
    (out / "stoop.js").write_text(f"window.STOOP_DATA={text};\n", encoding="utf-8")
    return out / "stoop.js"


STRAY_MAX_M2 = 50_000   # pieces this small...
STRAY_GAP_M = 150        # ...and this far from the rest of the neighborhood are dropped from the map shape


def drop_stray_parts(geom, max_m2: float = STRAY_MAX_M2, gap_m: float = STRAY_GAP_M):
    """Drops tiny far-off pieces (slivers in the source shapes, e.g. Murray Hill's bits across the East River).

    Real islands stay: they're bigger than max_m2, or they're the largest piece. Meters CRS."""
    from shapely.geometry import MultiPolygon
    if geom is None or geom.geom_type != "MultiPolygon":
        return geom
    parts = sorted(geom.geoms, key=lambda p: -p.area)
    main = parts[0]
    keep = [main] + [p for p in parts[1:] if p.area >= max_m2 or p.distance(main) <= gap_m]
    return keep[0] if len(keep) == 1 else MultiPolygon(keep)


def geometries_from_gdf(ntas, tolerance_m: float = 15) -> dict:
    """Simplified WGS84 GeoJSON geometry per NTA, coordinates rounded to ~1 m."""
    from shapely.geometry import mapping
    import shapely
    g = ntas.copy()
    g["geometry"] = g.geometry.map(drop_stray_parts).simplify(tolerance_m, preserve_topology=True)
    g = g.to_crs(4326)
    g["geometry"] = shapely.set_precision(g.geometry.values, 1e-5)
    return {idx: mapping(geom) for idx, geom in g.geometry.items()}


def label_points(ntas) -> dict:
    """{nta2020: [lon, lat]} of a point inside each NTA (not the centroid, which can fall outside)."""
    pts = ntas.geometry.representative_point().to_crs(4326)
    return {idx: [round(p.x, 5), round(p.y, 5)] for idx, p in pts.items()}


def qa_report(table: pd.DataFrame, scores: pd.DataFrame, path: Path, residential: pd.Series) -> Path:
    """Coverage and top/bottom lists."""
    lines = [f"# stoop QA report ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"Neighborhoods: {len(table)} ({int(residential.sum())} residential)", "",
             "## Metric coverage (residential NTAs)", "", "| metric | non-missing | min | median | max |", "|---|---|---|---|---|"]
    res = table[residential]
    for col in METRICS:
        if col in res.columns and pd.api.types.is_numeric_dtype(res[col]):
            s = res[col]
            lines.append(f"| {col} | {s.notna().sum()} | {s.min():.1f} | {s.median():.1f} | {s.max():.1f} |")
        elif col not in res.columns:
            lines.append(f"| {col} | **missing** | | | |")
    lines += ["", "## Best and worst 5 per factor", ""]
    for f in scores.columns:
        s = scores.loc[residential, f].dropna()
        if s.empty:
            lines.append(f"**{f}**: no data\n")
            continue
        top = ", ".join(f"{table.at[i, 'name']} ({v:.0f})" for i, v in s.nlargest(5).items())
        bot = ", ".join(f"{table.at[i, 'name']} ({v:.0f})" for i, v in s.nsmallest(5).items())
        lines += [f"**{f}**", f"- best: {top}", f"- worst: {bot}", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return Path(path)
