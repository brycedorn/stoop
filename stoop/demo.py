"""Synthetic data so the map can be previewed (and tested) without downloads.

Neighborhoods are fake squares labeled "Demo NN". Values follow loose,
made-up spatial patterns (pricier and louder near Midtown, and so on). They are not real data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .scoring import score_table

BOROUGH_BOXES = {   # rough lon/lat boxes; squares land partly in water, it's a demo
    "Manhattan": (-74.02, 40.70, -73.93, 40.82),
    "Brooklyn": (-74.02, 40.60, -73.88, 40.70),
    "Queens": (-73.94, 40.70, -73.78, 40.77),
    "Bronx": (-73.92, 40.82, -73.84, 40.88),
}
MIDTOWN = (-73.985, 40.754)


def make_demo(cfg: dict, seed: int = 7, step: float = 0.018):
    rng = np.random.default_rng(seed)
    rows, geoms = [], {}
    n = 0
    for boro, (x0, y0, x1, y1) in BOROUGH_BOXES.items():
        for x in np.arange(x0, x1, step):
            for y in np.arange(y0, y1, step * 0.76):
                n += 1
                nta = f"DM{n:02d}"
                dx, dy = step * 0.48, step * 0.76 * 0.48
                cx, cy = x + step / 2, y + step * 0.38
                geoms[nta] = {"type": "Polygon", "coordinates": [[
                    [round(cx - dx, 5), round(cy - dy, 5)], [round(cx + dx, 5), round(cy - dy, 5)],
                    [round(cx + dx, 5), round(cy + dy, 5)], [round(cx - dx, 5), round(cy + dy, 5)],
                    [round(cx - dx, 5), round(cy - dy, 5)]]]}
                d_km = np.hypot((cx - MIDTOWN[0]) * 84, (cy - MIDTOWN[1]) * 111)
                near = np.exp(-d_km / 6)
                rows.append({
                    "nta2020": nta, "name": f"Demo {n:02d}", "borough": boro,
                    "ntatype": "0" if rng.random() > 0.05 else "9",
                    "pop": int(rng.uniform(15e3, 60e3)),
                    "pop_density_km2": 8000 + 40000 * near * rng.uniform(0.6, 1.2),
                    "rent_est": 2300 + 3200 * near * rng.uniform(0.75, 1.25),
                    "rent_source": "demo",
                    "commute_min": 12 + d_km * 3.2 * rng.uniform(0.8, 1.2),
                    "commute_method": "demo",
                    "station_dist_m": rng.uniform(100, 1200) * (1.5 - near),
                    "run_path_m": rng.uniform(2e3, 25e3),
                    "big_park_dist_m": rng.uniform(50, 2500),
                    "activity_density": rng.gamma(1.0, 3.0) * near,
                    "fav_score": rng.gamma(1.2, 1.5) * near * 3,
                    "fav_within_walk": int(rng.poisson(6 * near)),
                    "food_drink_600m": int(rng.poisson(20 + 120 * near)),
                    "crime_weighted_per_1k": rng.gamma(4, 15) * (0.6 + near),
                    "felonies_per_1k": rng.gamma(3, 4),
                    "noise_per_1k": rng.gamma(3, 20) * (0.5 + near),
                    "park_ha_walk": rng.gamma(2, 15),
                    "trees_300m": int(rng.uniform(50, 600)),
                    "errands_score": rng.uniform(0.2, 1) * (0.5 + near / 2),
                    "nearest_supermarket_m": rng.uniform(80, 900),
                    "nearest_gym_m": rng.uniform(80, 1500),
                    "citibike_400m": int(rng.poisson(5 * near + 0.5)),
                    "citibike_dist_m": rng.uniform(50, 1500) * (1.3 - near),
                    "flood_share": max(0.0, rng.normal(0.04, 0.08)),
                })
    table = pd.DataFrame(rows).set_index("nta2020")
    scores = score_table(table, cfg, table["ntatype"] == "0")
    return table, scores, geoms
