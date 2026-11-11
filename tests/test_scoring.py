import numpy as np
import pandas as pd
import pytest

from stoop import scoring
from stoop.scoring import commute_curve, flood_curve, percentile, rent_curve, score_table, total_score

CFG = {"you": {"max_rent": 4000}}


def test_rent_curve_breakpoints():
    s = rent_curve([2000, 2800, 4000, 4600, 6000, np.nan], 4000)
    assert s[0] == 100 and s[1] == pytest.approx(100)        # <=70% of budget
    assert s[2] == pytest.approx(50)                          # at budget
    assert s[3] == pytest.approx(0)                           # 15% over
    assert s[4] == 0
    assert np.isnan(s[5])


def test_rent_curve_monotonic():
    r = np.linspace(1000, 8000, 200)
    assert np.all(np.diff(rent_curve(r, 4000)) <= 1e-9)


def test_commute_and_flood_curves():
    assert list(commute_curve([10, 20, 47.5, 75, 90])) == pytest.approx([100, 100, 50, 0, 0])
    assert list(flood_curve([0, 0.15, 0.3, 0.9])) == pytest.approx([100, 50, 0, 0])


def test_percentile_direction_and_mask():
    v = pd.Series([10, 20, 30, 40, 1000])
    mask = pd.Series([True, True, True, True, False])
    up = percentile(v, mask, +1)
    down = percentile(v, mask, -1)
    assert list(up[:4]) == [0, pytest.approx(100 / 3), pytest.approx(200 / 3), 100]
    assert list(down[:4]) == [100, pytest.approx(200 / 3), pytest.approx(100 / 3), 0]
    assert np.isnan(up[4])    # non-residential rows aren't ranked


def test_score_table_skips_missing_components():
    # running has 3 components; with your GPS runs missing, the other two carry it
    f = pd.DataFrame({"run_path_m": [1, 2, 3], "big_park_dist_m": [300, 200, 100]}, index=list("abc"))
    s = score_table(f, CFG)
    assert list(s["running"]) == [0, 50, 100]
    assert s["safety"].isna().all()     # no data -> NaN, not 0


def test_score_table_row_level_missing():
    f = pd.DataFrame({"park_ha_walk": [1, 2, np.nan], "trees_300m": [5, 10, 20]}, index=list("abc"))
    s = score_table(f, CFG)
    # 'c' has only trees (best) -> 100, not dragged down by the missing park value
    assert s.at["c", "green"] == 100


def test_total_score_renormalizes():
    s = pd.DataFrame({"rent": [100, 0], "commute": [50, np.nan]}, index=["x", "y"])
    t = total_score(s, {"rent": 1, "commute": 1, "running": 5})
    assert t["x"] == 75
    assert t["y"] == 0          # only rent available for y
    assert total_score(s, {"rent": 0}).isna().all()


def test_every_factor_has_label_and_components():
    for k, spec in scoring.FACTORS.items():
        assert spec["label"] and spec["help"]
        assert sum(w for _, _, w in spec["components"]) == pytest.approx(1.0), k


def test_familiar_curve():
    v = scoring.familiar_curve([0, 1000, 2000, 5000])
    assert v[0] == 100 and 60 < v[1] < 66 and 14 < v[2] < 20 and v[3] < 0.1


def test_gym_curve():
    v = scoring.gym_curve([0, 400, 1200, 2000, 5000])
    assert list(v) == [100, 100, 50, 0, 0]


def test_airport_curve():
    assert list(scoring.airport_curve([40, 55, 85, 115, 130])) == [100, 100, 50, 0, 0]


def test_publish_rent_bands_and_public_table():
    from stoop.publish import CENSUS_SOURCE, RENT_BAND, band, public_table
    from stoop.sources.rent import DEFAULT_ACS_UPLIFT
    assert RENT_BAND == 500
    assert band([3620, 3500, 3999, None]).tolist()[:3] == [3750, 3750, 3750]
    t = pd.DataFrame({"rent_est": [9999.0], "rent_est_2br": [9999.0], "rent_source_2br": ["listings"], "rent_acs": [1.0],
                      "acs_rent_all": [2000.0], "acs_rent_1br": [2500.0], "acs_rent_2br": [np.nan],
                      "familiar_dist_m": [100.0], "fav_within_walk": [3], "commute_min": [30.0]})
    p = public_table(t, bedrooms=2)
    # listing rents are replaced by Census ones: 2br has no ACS value, so all-units 2000 x uplift, but never below 1br
    want_2br = band(max(2000, 2500) * DEFAULT_ACS_UPLIFT)
    assert p["rent_est_2br"].iloc[0] == want_2br and p["rent_est"].iloc[0] == want_2br
    assert set(p.filter(like="rent_source").iloc[0]) == {CENSUS_SOURCE}
    assert "commute_min" in p
    assert not {"rent_acs", "acs_rent_all", "familiar_dist_m", "fav_within_walk"} & set(p.columns)


def test_config_local_layers_on_top():
    from stoop.context import merge_config
    base = {"you": {"max_rent": 4000, "liked": [], "dests": [{"name": "A"}]}, "x": 1}
    over = {"you": {"max_rent": 5000, "dests": [{"name": "A", "label": "Job"}]}}
    m = merge_config(base, over)
    assert m["you"] == {"max_rent": 5000, "liked": [], "dests": [{"name": "A", "label": "Job"}]} and m["x"] == 1
    assert base["you"]["max_rent"] == 4000                   # the base isn't modified
