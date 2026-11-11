"""Grid helpers that only need numpy/scipy (no geopandas)."""
import numpy as np
import pandas as pd
import pytest

from stoop import geo




def make_grid():
    g = pd.DataFrame({"x": [0, 100, 200, 1000], "y": [0, 0, 0, 0],
                      "nta2020": ["A", "A", "A", "B"], "pop": [100, 0, 300, 0]})
    g.index.name = "cell_id"
    return g


def test_sum_within_and_nearest():
    cells = np.array([[0, 0], [1000, 0]])
    pts = np.array([[50, 0], [120, 0], [990, 0]])
    assert list(geo.sum_within(cells, pts, 150)) == [2, 1]
    assert list(geo.sum_within(cells, pts, 150, weights=[1, 2, 5])) == [3, 5]
    assert list(geo.nearest_dist(cells, pts)) == [50, 10]
    assert geo.sum_within(cells, np.empty((0, 2)), 100).tolist() == [0, 0]


def test_decay_sum():
    cells = np.array([[0.0, 0.0]])
    assert geo.decay_sum(cells, np.array([[0.0, 0.0]]), 500)[0] == pytest.approx(1)
    assert geo.decay_sum(cells, np.array([[500.0, 0.0]]), 500)[0] == pytest.approx(np.exp(-1))
    assert geo.decay_sum(cells, np.array([[5000.0, 0.0]]), 500)[0] == 0


def test_to_nta_population_weighted():
    g = make_grid()
    out = geo.to_nta(g, [10, 999, 30, 7])
    assert out["A"] == pytest.approx((10 * 100 + 30 * 300) / 400)   # empty cell ignored
    assert out["B"] == 7                                            # no residents -> plain mean


def test_grid_neighbor_sum():
    g = make_grid()
    s = geo.grid_neighbor_sum(g, pd.Series([1.0, 1.0, 1.0, 1.0], index=g.index), 150)
    assert list(s) == [2, 3, 2, 1]


def test_drop_stray_parts_keeps_islands_drops_slivers():
    pytest.importorskip("shapely")
    from shapely.geometry import MultiPolygon, box
    from stoop.export import drop_stray_parts
    main = box(0, 0, 1000, 1000)
    sliver_far = box(1800, 0, 1830, 30)        # 900 m2, 800 m away: dropped
    sliver_near = box(1050, 0, 1080, 30)       # 50 m away: kept (a pier on the same shore)
    island = box(3000, 0, 3300, 300)           # 90,000 m2: kept however far
    out = drop_stray_parts(MultiPolygon([main, sliver_far, sliver_near, island]))
    assert sorted(round(p.area) for p in out.geoms) == [900, 90_000, 1_000_000]
    assert drop_stray_parts(MultiPolygon([main, sliver_far])).geom_type == "Polygon"
    assert drop_stray_parts(main) is main


def test_hex_lattice_matches_runner_hex_projection_and_rounds_back():
    from stoop import geo
    from stoop.sources.runner_hexes import hex_center
    q, r, x, y = geo.hex_lattice(-74.0, 40.70, -73.99, 40.71, 150)
    assert len(q) > 20
    for qi, ri, xi, yi in list(zip(q, r, x, y))[::7]:
        assert (xi, yi) == pytest.approx(hex_center(int(qi), int(ri), 150))   # same lattice as runner hexes
        assert geo.hex_at(xi + 40, yi - 60, 150) == (qi, ri)                 # a point inside rounds to its hex
    # the box is covered: every point in it is within one hex radius of a center
    pts = np.column_stack([x, y])
    for lon, lat in [(-73.995, 40.705), (-73.9999, 40.7001), (-73.9901, 40.7099)]:
        d = np.hypot(pts[:, 0] - lon * geo.HEX_KX, pts[:, 1] - lat * geo.HEX_KY).min()
        assert d <= 150 + 1e-6


def test_percentile_against_neighborhoods():
    from stoop.scoring import percentile_against
    ref = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    s = percentile_against([10, 30, 35, 50, 5, 99, np.nan], ref, +1)
    assert s[:4] == pytest.approx([0, 50, 62.5, 100])
    assert s[4] == 0 and s[5] == 100 and np.isnan(s[6])          # outside the range clamps
    assert percentile_against([10, 50], ref, -1) == pytest.approx([100, 0])


def test_score_cells_own_values_and_inherited_factors():
    from stoop.scoring import FACTORS, score_cells
    ntas = ["A", "B", "C"]
    features = pd.DataFrame({"commute_min": [20, 47.5, 75], "station_dist_m": [100, 500, 900],
                             "crime_weighted_per_1k": [10, 20, 30]}, index=ntas)
    scores = pd.DataFrame({"safety": [100, 50, 0], "commute": [90, 50, 10]}, index=ntas)
    residential = pd.Series(True, index=ntas)
    cells = pd.DataFrame({"commute_min": [20, 75], "station_dist_m": [500, 500]})
    out, inherited = score_cells(cells, pd.Series(["A", "C"]), features, scores, {"you": {"max_rent": 5000}}, residential)
    assert out["commute"].tolist() == pytest.approx([0.85 * 100 + 0.15 * 50, 0.15 * 50])
    assert "safety" in inherited and "commute" not in inherited
    assert out["safety"].tolist() == [100, 0]                     # neighborhood-wide: each cell shows its NTA's
    assert set(out.columns) == set(FACTORS)
