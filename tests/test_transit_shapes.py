import numpy as np
import pytest

from stoop.transit_shapes import _fold_short_runs, _orient, smooth


def test_smooth_rounds_corners_and_keeps_ends():
    corner = [(0, 0), (500, 0), (500, 500)]
    p = smooth(corner)
    assert tuple(p[0]) == (0, 0) and tuple(p[-1]) == (500, 500)
    assert len(p) > 3
    # the corner is cut: no point sits on (500, 0), and no point is farther than the first cut (40 m) from it
    d = np.hypot(p[:, 0] - 500, p[:, 1])
    assert d.min() > 1 and d.min() < 40
    # turning angles are all gentle (no hard 90° turn left)
    v = np.diff(p, axis=0)
    cross = v[:-1, 0] * v[1:, 1] - v[:-1, 1] * v[1:, 0]
    ang = np.degrees(np.abs(np.arctan2(cross, (v[:-1] * v[1:]).sum(1))))
    assert ang.max() < 25


def test_short_runs_fold_into_neighbors():
    ds = np.arange(0, 1000, 15.0)
    keys = ["a"] * 30 + ["b"] * 3 + ["a"] * (len(ds) - 33)   # a 45 m blip
    assert set(_fold_short_runs(keys, ds, 150)) == {"a"}


def test_orient_points_pieces_the_same_way():
    up = np.array([[0, 0], [100, 180]], float)
    assert (_orient(up) == up).all() and (_orient(up[::-1]) == up).all()
