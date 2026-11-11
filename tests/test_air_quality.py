"""Air quality (EHDP) parsing; no network."""
import pytest

from stoop.sources.air_quality import latest_cd_values, nta_to_cd


def test_nta_to_cd():
    assert nta_to_cd("BK0101") == 301
    assert nta_to_cd("MN1201") == 112
    assert nta_to_cd("SI0303") == 503
    assert nta_to_cd("BK5591") is None    # park / joint interest area
    assert nta_to_cd("XX0101") is None


def test_latest_cd_values_picks_latest_annual_district_rows():
    periods = {1: {"TimePeriod": "2024", "TimeType": "year"}, 2: {"TimePeriod": "2025", "TimeType": "year"},
               3: {"TimePeriod": "Summer 2026", "TimeType": "season"}}
    data = {"MeasureID": [1425, 1425, 1425, 1425, 1426, 1425],
            "GeoID": [301, 301, 1, 302, 301, 301],
            "GeoType": ["CD", "CD", "Citywide", "CD", "CD", "CD"],
            "TimePeriodID": [1, 2, 2, 2, 2, 3],
            "Value": [9.0, 7.5, 6.3, 8.1, 99.0, 50.0]}
    year, vals = latest_cd_values(data, 1425, periods)
    assert year == "2025"
    assert vals == {301: 7.5, 302: 8.1}


def test_latest_cd_values_errors_when_missing():
    with pytest.raises(ValueError):
        latest_cd_values({"MeasureID": [], "GeoID": [], "GeoType": [], "TimePeriodID": [], "Value": []}, 1425, {})
