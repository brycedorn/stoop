"""Runner traffic by hex: a data source like any other. stoop reads it; it doesn't make it (a separate tool does).

File (config `sources.runner_hexes`, default inputs/runner_hexes.json):
    {"version": 1, "size_m": 150, "hexes": {"q,r": 0-5, ...}}
Hexes are pointy-top, in axial coordinates (q, r), on a planar projection: x = lon * KX, y = lat * KY with
KX = 111320 * cos(40.7°), KY = 110540 (meters). Hex (q, r) is centered at (size * √3 * (q + r/2), size * 1.5 * r).
Values: 0 = checked, no runners ... 5 = busiest. Hexes not in the file are unknown, not 0.

Score per neighborhood: the mean of the HEX_TOP busiest hexes within HEX_RADIUS_M of its label point, 0-5 -> 0-100.
No hex nearby = no data (not a penalty). The map shows the hexes read-only (layers.runner_hex_layer).
"""
from __future__ import annotations

import json
import logging
import math

import numpy as np
import pandas as pd

log = logging.getLogger("stoop.runner_hexes")
NAME = "runner_hexes"

LAT0 = 40.7
KX = 111320 * math.cos(math.radians(LAT0))
KY = 110540
HEX_SIZE_M = 150      # center to corner; ~260 m across
HEX_RADIUS_M = 1000   # "near": about a 12-minute walk
HEX_TOP = 3           # the busiest few nearby hexes decide


def hex_center(q: int, r: int, size: float = HEX_SIZE_M) -> tuple[float, float]:
    return size * math.sqrt(3) * (q + r / 2), size * 1.5 * r


def to_xy(lon: float, lat: float) -> tuple[float, float]:
    return lon * KX, lat * KY


def hex_ring(q: int, r: int, size: float = HEX_SIZE_M) -> list:
    """The hex's outline as [lon, lat] points (closed)."""
    cx, cy = hex_center(q, r, size)
    ring = []
    for i in range(7):
        a = math.radians(60 * (i % 6) - 30)
        ring.append([round((cx + size * math.cos(a)) / KX, 6), round((cy + size * math.sin(a)) / KY, 6)])
    return ring


def is_restricted(data: dict) -> bool:
    """True when the file declares it holds restricted third-party data: the generator sets `meta.contains`
    (e.g. "<provider>_api_derived"). Open data and your own runs leave it unset."""
    return bool((data.get("meta") or {}).get("contains"))


def load(ctx) -> tuple[dict, float] | None:
    """({"q,r": value}, hex size in m) from the configured file, or None if there isn't one."""
    from pathlib import Path
    path = Path(ctx.src.get("runner_hexes") or "inputs/runner_hexes.json")
    path = path if path.is_absolute() else ctx.root / path
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if is_restricted(data):
        log.warning("runner hexes: %s declares restricted third-party data (meta.contains); stoop uses open data and "
                    "your own runs only. Rebuild it from those", path.name)
        return None
    hexes = {k: v for k, v in (data.get("hexes") or {}).items() if isinstance(v, (int, float)) and 0 <= v <= 5}
    return hexes, float(data.get("size_m", HEX_SIZE_M))


def runhex_score(xy, hexes: dict, size: float = HEX_SIZE_M, radius: float = HEX_RADIUS_M, top: int = HEX_TOP):
    """0-100 from painted hexes ({"q,r": value}) near point xy, or None when none are painted nearby."""
    vals = []
    for key, v in hexes.items():
        q, r = (int(t) for t in key.split(","))
        cx, cy = hex_center(q, r, size)
        if math.hypot(cx - xy[0], cy - xy[1]) <= radius:
            vals.append(float(v))
    if not vals:
        return None
    best = sorted(vals, reverse=True)[:top]
    return sum(best) / len(best) * 20


def build(ctx) -> pd.DataFrame:
    from ..export import label_points
    out = pd.DataFrame(index=ctx.ntas.index)
    got = load(ctx)
    if got is None:
        log.info("no runner hex file yet (config sources.runner_hexes, default inputs/runner_hexes.json)")
        return out
    hexes, size = got
    labels = label_points(ctx.ntas)
    out["runhex_score"] = pd.Series({n: runhex_score(to_xy(*labels[n]), hexes, size) for n in out.index if n in labels},
                                    dtype=float)
    log.info("runner hexes: %d painted, %d neighborhoods scored", len(hexes), int(out["runhex_score"].notna().sum()))
    return out
