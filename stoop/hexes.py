"""Hex view data: factor scores for every hex cell, grouped by neighborhood, for web/data/hexes.js.

Each pipeline step keeps the per-cell values behind its neighborhood averages (data/interim/cells_<step>.parquet,
see geo.collect_cells). Here they're scored on the neighborhood scale (scoring.score_cells) and written compactly:

    window.STOOP_HEXES = {
      "size_m": 150, "kx": ..., "ky": ...,          # hex (q, r) center = (size*√3*(q + r/2), size*1.5*r) / (kx, ky)
      "factors": [...],                            # per-hex score columns, in order
      "inherited": [...],                          # factors that are neighborhood-wide (the hex shows its NTA's)
      "dests": [...],                              # configured commute destinations, in order
      "by_nta": {"BK0101": [[q, r, pop, f1..fn, commute_min, d1..dk, station_pct], ...]},
      "clip": {"BK0101": {"3": [[ring, ...], ...]}}  # edge hexes cut to the neighborhood outline, keyed by row
    }                                              # index: polygons of rings, each ring delta-encoded (encode_ring)
Scores and minutes are whole numbers; null = no data.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from . import scoring

log = logging.getLogger("stoop.hexes")
FEW_PEOPLE = 25    # hexes with fewer residents are drawn as "few residents" (parks, rail yards, industry)


def load_cells(ctx, grid) -> pd.DataFrame:
    """All steps' per-cell values for the current grid (stale files from another grid are skipped)."""
    from .sources import STEPS
    parts = []
    for name in STEPS:
        f = ctx.interim / f"cells_{name}.parquet"
        if not f.exists():
            continue
        df = pd.read_parquet(f)
        if len(df) != len(grid) or not df.index.equals(grid.index):
            log.warning("hexes: %s was computed on another grid; rerun that step", f.name)
            continue
        parts.append(df)
    cells = pd.concat(parts, axis=1) if parts else pd.DataFrame(index=grid.index)
    cells = cells.loc[:, ~cells.columns.duplicated()]
    area_km2 = grid.geometry.area / 1e6
    cells["pop_density_km2"] = (grid["pop"] / area_km2).values
    if "run5k_min" in cells:
        cells["run5k_score"] = scoring.run5k_curve(cells["run5k_min"].values)
    return cells


CLIP_SIMPLIFY_M = 15   # same tolerance as the neighborhood outlines (export.geometries_from_gdf), so edges line up
FULL_SHARE = 0.995     # a hex this much inside its neighborhood is drawn whole


def clip_shapes(ctx, grid) -> dict[int, list]:
    """{cell_id: MultiPolygon coordinates} for hexes that stick out of their neighborhood: over the water at the
    shoreline, or across a boundary. Cut to the same outline the map draws for the neighborhood."""
    import shapely
    from shapely.geometry import mapping
    from .export import drop_stray_parts
    from .context import CRS_LL
    import geopandas as gpd
    outline = ctx.ntas.geometry.map(drop_stray_parts).simplify(CLIP_SIMPLIFY_M, preserve_topology=True)
    hexes = grid.geometry.values
    shapes = outline.reindex(grid["nta2020"].values).values
    cut = shapely.intersection(hexes, shapes)
    share = shapely.area(cut) / shapely.area(hexes)
    edge = np.flatnonzero((share < FULL_SHARE) & (share > 0.01))
    cut = gpd.GeoSeries(cut[edge], crs=grid.crs).to_crs(CRS_LL)
    cut = shapely.set_precision(shapely.make_valid(cut.values), 1e-5)
    out = {}
    for i, g in zip(edge, cut):
        parts = shapely.get_parts(shapely.get_parts(g))   # collections and multipolygons -> single parts
        polys = [p for p in parts if p.geom_type == "Polygon" and not p.is_empty]
        if polys:
            out[int(grid.index[i])] = [[encode_ring(ring) for ring in mapping(p)["coordinates"]] for p in polys]
    log.info("hexes: %d of %d cut to the neighborhood outline", len(out), len(grid))
    return out


def encode_ring(coords) -> list[int]:
    """[(lon, lat), ...] -> [lon0, lat0, dlon1, dlat1, ...] in 1e-5 degree steps (~1 m): the first point whole, then
    the step from the previous point. About a third the size of plain coordinates. Decoded by decodeRing in app.js."""
    out, px, py = [], 0, 0
    for lon, lat in coords:
        x, y = round(lon * 1e5), round(lat * 1e5)
        out += [x - px, y - py]
        px, py = x, y
    return out


def decode_ring(flat) -> list[tuple[float, float]]:
    x = y = 0
    out = []
    for i in range(0, len(flat), 2):
        x += flat[i]
        y += flat[i + 1]
        out.append((x / 1e5, y / 1e5))
    return out


def _int(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else int(round(float(v)))


def build_payload(ctx, table: pd.DataFrame, scores: pd.DataFrame, residential: pd.Series,
                  drop: set | frozenset = frozenset()) -> dict | None:
    """`drop`: per-cell columns to leave out (the public build drops personal ones, like familiar_dist_m)."""
    from .geo import HEX_KX, HEX_KY
    from .sources.commute import dest_slug
    grid = ctx.grid
    if "q" not in grid.columns:
        log.info("hexes: the analysis grid is square (config grid: square); no hex view")
        return None
    from .sources.commute import active_destination
    cells = load_cells(ctx, grid).drop(columns=list(drop), errors="ignore")
    dests =[d["name"] for d in ctx.cfg["you"]["commute_destinations"]]
    dcols = [f"commute_min_{dest_slug(n)}" for n in dests]
    active = active_destination(ctx.cfg)       # like apply_commute_choice for the neighborhoods
    if active is not None and dcols[active] in cells:
        cells["commute_min"] = cells[dcols[active]]
    cell_scores, inherited = scoring.score_cells(cells, grid["nta2020"], table, scores, ctx.cfg, residential)
    factors = [f for f in scoring.FACTORS if f not in inherited]
    ref = pd.to_numeric(table["station_dist_m"], errors="coerce").where(residential) if "station_dist_m" in table else None
    station_pct = (scoring.percentile_against(cells["station_dist_m"].values, ref, -1)
                   if ref is not None and "station_dist_m" in cells else np.full(len(cells), np.nan))
    cols = [cell_scores[f].values for f in factors]
    cm = cells["commute_min"].values if "commute_min" in cells else np.full(len(cells), np.nan)
    dmins = [cells[c].values if c in cells else np.full(len(cells), np.nan) for c in dcols]
    try:
        clips = clip_shapes(ctx, grid)
    except Exception as e:   # the hex view still works with whole hexes
        log.warning("hexes: couldn't cut edge hexes (%s); drawing them whole", e)
        clips = {}
    by_nta: dict[str, list] = {}
    clip: dict[str, dict] = {}
    for i, (q, r, nta, pop) in enumerate(zip(grid.q.values, grid.r.values, grid.nta2020.values, grid["pop"].values)):
        row = [int(q), int(r), _int(pop)] + [_int(c[i]) for c in cols] + [_int(cm[i])] + [_int(d[i]) for d in dmins]
        row.append(_int(station_pct[i]))
        rows = by_nta.setdefault(str(nta), [])
        if grid.index[i] in clips:
            clip.setdefault(str(nta), {})[str(len(rows))] = clips[grid.index[i]]
        rows.append(row)
    size = float(np.sqrt(grid.geometry.area.median() / (1.5 * np.sqrt(3))))   # hex area = 3√3/2 · size²
    return {"size_m": round(ctx.cfg.get("grid_hex_m", size), 3), "kx": HEX_KX, "ky": HEX_KY,
            "factors": factors, "inherited": inherited, "dests": dests, "few_people": FEW_PEOPLE, "by_nta": by_nta,
            "clip": clip}


def write(payload: dict | None, web_dir: Path) -> Path | None:
    out = Path(web_dir) / "data" / "hexes.js"
    if payload is None:
        if out.exists():
            out.unlink()
        return None
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    out.write_text(f"window.STOOP_HEXES={text};\n", encoding="utf-8")
    n = sum(len(v) for v in payload["by_nta"].values())
    log.info("wrote hexes.js: %d hexes, %d factors per hex (%.1f MB)", n, len(payload["factors"]), len(text) / 1e6)
    return out
