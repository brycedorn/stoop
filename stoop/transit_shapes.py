"""Subway line geometry for the map: smooth curves, and side-by-side lines where services share a corridor.

The MTA's GTFS shapes are sparse at curves (a few points per bend), so drawn as-is they turn in hard angles.
`smooth` rounds every corner with a capped corner cut (Chaikin's algorithm), so long straights stay straight.

Where services of different colors run together (E/F/M/R on Queens Boulevard, 2/3 and 4/5 in Brooklyn), drawing
both lines on the same spot hides one under the other. Like the official subway map, each color then gets its own
lane, side by side: `assign_lanes` finds, along each route, which other colors run parallel within a few meters,
and cuts the route into pieces carrying `off` = its lane's offset in line widths from the shared center line.
Services of the same color (A/C/E) share a lane, so they still draw as one line. The map multiplies `off` by
the line width at every zoom, so the lanes stay touching at any scale.

MapLibre offsets a line to the right of its direction of travel, so every shared piece is pointed the same way
along the corridor (`_orient`); otherwise two services running opposite ways would swap sides.
"""
from __future__ import annotations

import numpy as np

SAMPLE_M = 15          # spacing of the points used to compare routes
NEAR_M = 28            # another color within this distance, running parallel, shares the corridor
PARALLEL_COS = 0.9     # ~25°: crossings and junction approaches don't count as running together
MIN_RUN_M = 150        # shorter shared or unshared stretches are folded into their neighbors (no lane flicker)
# corridor axis used to point shared pieces the same way: along Manhattan's avenues (29° east of north),
# with the cross-town axis as a fallback for pieces that run nearly across it
AXIS = np.array([np.sin(np.radians(29)), np.cos(np.radians(29))])
AXIS2 = np.array([AXIS[1], -AXIS[0]])


def smooth(coords, cut_m=(40.0, 18.0, 8.0)) -> np.ndarray:
    """Round the corners of a polyline (meters): each pass replaces every inner vertex by two points a quarter of
    the way along its segments, at most `cut` meters from it. Endpoints stay put."""
    p = np.asarray(coords, float)
    for cut in cut_m:
        if len(p) < 3:
            break
        a, b = p[:-1], p[1:]
        seg = np.hypot(*(b - a).T)
        d = np.minimum(seg * 0.25, cut)[:, None]
        u = (b - a) / np.where(seg > 0, seg, 1)[:, None]
        q = a + u * d            # near each segment's start
        r = b - u * d            # near each segment's end
        mid = np.empty((2 * (len(p) - 2), 2))
        mid[0::2] = r[:-1]
        mid[1::2] = q[1:]
        p = np.vstack([p[:1], mid, p[-1:]])
    return p


def _resample(line, step: float):
    """Points every `step` m along a shapely line, with the unit direction at each."""
    n = max(int(line.length // step), 1)
    ds = np.linspace(0, line.length, n + 1)
    pts = np.array([line.interpolate(d).coords[0] for d in ds])
    dirs = np.gradient(pts, axis=0)
    dirs /= np.maximum(np.hypot(*dirs.T), 1e-9)[:, None]
    return ds, pts, dirs


def _fold_short_runs(keys: list, ds: np.ndarray, min_len: float) -> list:
    """Replace stretches shorter than `min_len` by the longer neighboring stretch's key, repeatedly."""
    keys = list(keys)
    while True:
        runs, s = [], 0
        for i in range(1, len(keys) + 1):
            if i == len(keys) or keys[i] != keys[s]:
                runs.append((s, i))
                s = i
        if len(runs) <= 1:
            return keys
        lens = [ds[min(e, len(ds) - 1)] - ds[s] for s, e in runs]
        k = int(np.argmin(lens))
        if lens[k] >= min_len:
            return keys
        s, e = runs[k]
        left = lens[k - 1] if k > 0 else -1
        right = lens[k + 1] if k + 1 < len(runs) else -1
        src = runs[k - 1][0] if left >= right else runs[k + 1][0]
        keys[s:e] = [keys[src]] * (e - s)


def _orient(coords: np.ndarray) -> np.ndarray:
    v = coords[-1] - coords[0]
    n = np.hypot(*v)
    if n == 0:
        return coords
    axis = AXIS if abs(v @ AXIS) / n >= 0.35 else AXIS2
    return coords if v @ axis >= 0 else coords[::-1]


def assign_lanes(routes: list[dict], order: list[str]) -> list[dict]:
    """routes: [{"coords": (n, 2) meters, "color": str, **props}] -> pieces [{"coords", "off", **props}].

    `order` is the fixed left-to-right order of colors, so two colors keep the same sides everywhere."""
    from scipy.spatial import cKDTree
    from shapely.geometry import LineString
    from shapely.ops import substring
    rank = {c: i for i, c in enumerate(order)}
    lines = [LineString(r["coords"]) for r in routes]
    samples = [_resample(ln, SAMPLE_M) for ln in lines]
    all_pts = np.vstack([s[1] for s in samples])
    all_dir = np.vstack([s[2] for s in samples])
    all_col = np.concatenate([[r["color"]] * len(s[1]) for r, s in zip(routes, samples)])
    tree = cKDTree(all_pts)
    out = []
    for r, ln, (ds, pts, dirs) in zip(routes, lines, samples):
        own = r["color"]
        keys = []
        for p, d, near in zip(pts, dirs, tree.query_ball_point(pts, NEAR_M)):
            cols = {all_col[j] for j in near if all_col[j] != own and abs(all_dir[j] @ d) >= PARALLEL_COS}
            keys.append(tuple(sorted(cols | {own}, key=lambda c: rank.get(c, 99))))
        keys = _fold_short_runs(keys, ds, MIN_RUN_M)
        props = {k: v for k, v in r.items() if k != "coords"}
        s = 0
        for i in range(1, len(keys) + 1):
            if i < len(keys) and keys[i] == keys[s]:
                continue
            a, b = ds[s], ds[min(i, len(ds) - 1)]
            piece = substring(ln, a, b) if (a > 0 or b < ln.length) else ln
            if piece.length > 0 and piece.geom_type == "LineString":
                lane = keys[s]
                off = lane.index(own) - (len(lane) - 1) / 2
                c = np.asarray(piece.coords)
                out.append({**props, "coords": _orient(c) if len(lane) > 1 else c, "off": round(float(off), 2)})
            s = i
    return out
