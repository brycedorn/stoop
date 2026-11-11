"""Running: dedicated paths nearby, distance to a big park, and where *you* run.

- OSM: length of footpaths, park paths, greenways and tracks within ~1 km,
  excluding sidewalks and crossings (NYC maps every sidewalk).
- Distance to the nearest park of 20+ acres (room for an uninterrupted loop).
- Your own runs: GPS files (GPX, TCX or FIT, optionally .gz) from any app or watch,
  in inputs/activities/ (any subfolders). A file that says it's another sport
  (GPX <type>, TCX Sport, FIT sport) is skipped; files that don't say are kept.
"""
from __future__ import annotations

import gzip
import io
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from .. import geo, osm
from .green import load_parks

log = logging.getLogger("stoop.running")
NAME = "running"

RUN_TAGS = {"highway": ["footway", "path", "pedestrian", "track", "cycleway", "bridleway"],
            "leisure": ["track"]}
EXCLUDE_FOOTWAY = {"sidewalk", "crossing", "traffic_island", "access_aisle"}
BIG_PARK_ACRES = 20


# --- Your GPS files --------------------------------------------------------

def _open(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def _gpx_points(raw: bytes):
    root = ET.fromstring(raw)
    for el in root.iter():
        if el.tag.endswith("trkpt"):
            yield float(el.get("lon")), float(el.get("lat"))


def _tcx_points(raw: bytes):
    root = ET.fromstring(raw.strip())
    lat = lon = None
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "LatitudeDegrees":
            lat = float(el.text)
        elif tag == "LongitudeDegrees":
            lon = float(el.text)
            if lat is not None:
                yield lon, lat
                lat = None


def _fit_points(raw: bytes):
    import fitdecode
    with fitdecode.FitReader(io.BytesIO(raw)) as fr:
        for frame in fr:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "record":
                if frame.has_field("position_lat") and frame.has_field("position_long"):
                    la, lo = frame.get_value("position_lat"), frame.get_value("position_long")
                    if la is not None and lo is not None:
                        yield lo * (180 / 2**31), la * (180 / 2**31)   # semicircles -> degrees


def is_run(path: Path) -> bool:
    """False only when the file says it's another sport. Standard fields: GPX <type>, TCX Sport, FIT sport."""
    name = path.name.lower()
    try:
        raw = _open(path)
        if ".gpx" in name or ".tcx" in name:
            head = raw[:20000].decode("utf-8", "ignore")
            m = re.search(r"<type>\s*([^<]+?)\s*</type>", head) or re.search(r'Sport="([^"]+)"', head)
            return m is None or "run" in m.group(1).lower()
        if ".fit" in name:
            import fitdecode
            with fitdecode.FitReader(io.BytesIO(raw)) as fr:
                for frame in fr:
                    if isinstance(frame, fitdecode.FitDataMessage) and frame.name in ("sport", "session") \
                            and frame.has_field("sport"):
                        return "run" in str(frame.get_value("sport")).lower()
    except Exception:   # unreadable here: let activity_points decide
        pass
    return True


def activity_points(path: Path):
    name = path.name.lower()
    raw = _open(path)
    if ".gpx" in name:
        return list(_gpx_points(raw))
    if ".tcx" in name:
        return list(_tcx_points(raw))
    if ".fit" in name:
        try:
            return list(_fit_points(raw))
        except ImportError:
            log.warning("pip install fitdecode to read .fit files; skipping %s", path.name)
    return []


def activity_runs(folder: Path, every: int = 5) -> np.ndarray:
    """(lon, lat) points from your run files, keeping every Nth point (~5-20 m apart)."""
    files = [p for p in Path(folder).rglob("*") if re.search(r"\.(gpx|tcx|fit)(\.gz)?$", p.name.lower())]
    runs = [f for f in files if is_run(f)]
    pts = []
    for f in runs:
        try:
            pts.extend(activity_points(f)[::every])
        except Exception as e:   # one corrupt file shouldn't sink the run
            log.debug("skip %s: %s", f.name, e)
    log.info("activities: %d run files of %d, %d points", len(runs), len(files), len(pts))
    return np.array(pts) if pts else np.empty((0, 2))


# --- Factor ---------------------------------------------------------------

def build(ctx) -> pd.DataFrame:
    grid, refresh = ctx.grid, ctx.wants_refresh(NAME)
    r = ctx.cfg.get("walk_radius_m", 1000)
    cells = geo.cell_xy(grid)
    out = pd.DataFrame(index=ctx.ntas.index)

    paths = osm.features(ctx, RUN_TAGS, "run_paths", refresh)
    paths = paths[paths.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    if "footway" in paths.columns:
        paths = paths[~paths["footway"].isin(EXCLUDE_FOOTWAY)]
    if "access" in paths.columns:
        paths = paths[~paths["access"].isin({"private", "no"})]
    pts = geo.lines_to_points(paths.geometry, step=25)
    out["run_path_m"] = geo.to_nta(grid, geo.sum_within(cells, pts, r, weights=np.full(len(pts), 25.0)), "run_path_m")

    parks = load_parks(ctx, refresh=False)
    big = parks[parks["acres_calc"] >= BIG_PARK_ACRES]
    edge = geo.lines_to_points(big.geometry.boundary, step=50)
    out["big_park_dist_m"] = geo.to_nta(grid, geo.nearest_dist(cells, edge), "big_park_dist_m")

    act_dir = ctx.inputs / "activities"
    lonlat = activity_runs(act_dir) if act_dir.exists() else np.empty((0, 2))
    if len(lonlat):
        sxy = geo.to_xy(lonlat[:, 0], lonlat[:, 1])
        out["activity_density"] = geo.to_nta(grid, geo.decay_sum(cells, sxy, scale=500), "activity_density")
    log.info("running: %d path segments, %d big parks", len(paths), len(big))
    return out
