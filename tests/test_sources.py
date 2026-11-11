"""Tests for source parsing that don't need network or geopandas."""
import gzip
import json

import numpy as np
import pandas as pd
import pytest

from stoop.demo import make_demo
from stoop.export import build_payload
from stoop.sources.favorites import read_places
from stoop.sources.rent import match_listing_areas, nta_name_variants, read_listing_rents
from stoop.sources.running import activity_points, activity_runs

CFG = {"you": {"max_rent": 4500, "commute_destinations": [{"name": "Work", "lat": 40.75, "lon": -73.98}]},
       "default_weights": {"rent": 10, "commute": 10, "running": 10}}


def test_nta_name_variants():
    v = nta_name_variants("Bedford-Stuyvesant (East)")
    assert "bedford stuyvesant" in v and "bedford" in v


def test_match_listing_areas():
    ntas = pd.DataFrame({
        "name": ["Upper West Side (Central)", "Bedford-Stuyvesant (East)", "Park Slope", "Midtown-Times Square", "Nowhere Land"],
        "borough": ["Manhattan", "Brooklyn", "Brooklyn", "Manhattan", "Queens"],
    }, index=["MN1", "BK1", "BK2", "MN2", "QN1"])
    se = pd.DataFrame({"area": ["Upper West Side", "Bedford-Stuyvesant", "Park Slope", "Midtown", "Park Slope"],
                       "borough": ["Manhattan", "Brooklyn", "Brooklyn", "Manhattan", "Queens"]})
    m = match_listing_areas(ntas, se)
    assert m.at["MN1", "listing_area"] == "Upper West Side"
    assert m.at["BK1", "listing_area"] == "Bedford-Stuyvesant"
    assert m.at["BK2", "listing_area"] == "Park Slope"
    assert m.at["MN2", "listing_area"] == "Midtown"
    assert pd.isna(m.at["QN1", "listing_area"])     # no same-borough match


def test_read_listing_rents_picks_bedroom_file(tmp_path):
    cols = "areaName,Borough,areaType,2026-08,2026-09\n"
    (tmp_path / "medianAskingRent_All.csv").write_text(cols + "Chelsea,Manhattan,neighborhood,5000,5100\n")
    (tmp_path / "medianAskingRent_OneBd.csv").write_text(
        cols + "Chelsea,Manhattan,neighborhood,4300,\nManhattan,Manhattan,borough,4000,4100\n")
    df = read_listing_rents(tmp_path, bedrooms=1)
    assert list(df["area"]) == ["Chelsea"]          # borough rows dropped
    assert df["listing_rent"].iloc[0] == 4300            # falls back to last non-empty month


def test_read_places(tmp_path):
    p = tmp_path / "places.csv"
    p.write_text("name,category,address,lat,lon,weight\n# comment\nExample Bar,bar,,,,\nExample Bistro,restaurant,123 Example Ave Brooklyn,40.7176,-73.9524,2\n")
    df = read_places(p)
    assert len(df) == 2 and df.weight.tolist() == [1.0, 2.0]
    assert np.isnan(df.lat[0]) and df.lat[1] == 40.7176


GPX = b"""<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="40.78" lon="-73.97"/><trkpt lat="40.781" lon="-73.969"/></trkseg></trk></gpx>"""


def test_activity_files_runs_only(tmp_path):
    ride = GPX.replace(b"<trk>", b"<trk><type>cycling</type>")
    run = GPX.replace(b"<trk>", b"<trk><type>running</type>")
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "a.gpx").write_bytes(run)
    (tmp_path / "b.gpx.gz").write_bytes(gzip.compress(ride))
    (tmp_path / "c.gpx").write_bytes(GPX)                 # no sport recorded: kept
    pts = activity_runs(tmp_path, every=1)
    assert pts.shape == (4, 2)                       # the ride is skipped
    assert activity_points(tmp_path / "b.gpx.gz")[0] == (-73.97, 40.78)


def test_demo_payload_is_valid_json():
    table, scores, geoms = make_demo(CFG)
    payload = build_payload(table, scores, geoms, CFG)
    text = json.dumps(payload, allow_nan=False)      # raises on NaN
    feats = payload["geojson"]["features"]
    assert len(feats) == len(table) > 50
    p = feats[0]["properties"]
    assert set(p["scores"]) >= {"rent", "commute", "running", "safety"}
    assert payload["meta"]["factors"]["rent"]["available"]
    assert all(0 <= v <= 100 for f in feats for v in f["properties"]["scores"].values() if v is not None)
    assert len(text) < 2_000_000


def test_departure_time_auto_is_next_tuesday_morning():
    from stoop.sources.commute import departure_time
    d = departure_time("auto")
    assert d.weekday() == 1 and (d.hour, d.minute) == (8, 30)
    assert departure_time("2026-11-10T08:30").day == 10


def test_month_windows_cover_range_without_gaps():
    from datetime import date
    from stoop.sources.safety import month_windows
    w = month_windows(date(2025, 11, 8), date(2026, 11, 8))
    assert w[0] == (date(2025, 11, 8), date(2025, 12, 1))
    assert w[1] == (date(2025, 12, 1), date(2026, 1, 1))
    assert w[-1] == (date(2026, 11, 1), None)          # current month stays open-ended
    assert all(a[1] == b[0] for a, b in zip(w, w[1:]))  # contiguous
    assert len(w) == 13


def test_cap_repeat_locations():
    from stoop.sources.safety import cap_repeat_locations
    df = pd.DataFrame({"latitude": ["40.7"] * 100 + ["40.8", "99"],
                       "longitude": ["-73.9"] * 100 + ["-73.95", "-73.9"]})
    w, capped = cap_repeat_locations(df, 52)
    assert capped == 1
    assert w.sum() == 53          # 100 capped to 52, plus one; out-of-bounds row dropped


def test_read_places_headerless_and_hash_in_address(tmp_path):
    p = tmp_path / "places.csv"
    p.write_text("burrito chain\nmike's corner bar\n# skipped\n\"Example Bistro\",restaurant,\"123 Example Ave #2\"\n")
    df = read_places(p)
    assert df.name.tolist() == ["burrito chain", "mike's corner bar", "Example Bistro"]
    assert df.address[2] == "123 Example Ave #2" and df.place_id.tolist() == [0, 1, 2]


def test_favorites_chain_counts_once():
    from stoop.sources.favorites import favorites_score, same_name
    cells = np.array([[0.0, 0.0]])
    # place 0 has 3 branches all next door; place 1 is one spot 5 km away
    xy = np.array([[0, 0], [10, 0], [0, 10], [5000, 0]], float)
    score, within = favorites_score(cells, xy, np.array([0, 0, 0, 1]), np.ones(4), 1000)
    assert 0.99 < score[0] < 1.01 and within[0] == 1
    assert same_name("cafe noir", "Café Noir") and not same_name("harbor bagels", "Harbor Street")


def test_match_listing_areas_combines_pieces_and_aliases():
    from stoop.sources.rent import mean_rent
    ntas = pd.DataFrame({"name": ["Tribeca-Civic Center", "Hell's Kitchen", "Rockaway Beach-Arverne-Edgemere"],
                         "borough": ["Manhattan", "Manhattan", "Queens"]}, index=["MN1", "MN2", "QN1"])
    se = pd.DataFrame({"area": ["Tribeca", "Civic Center", "Midtown West", "Rockaway All"],
                       "borough": ["Manhattan", "Manhattan", "Manhattan", "Queens"]})
    m = match_listing_areas(ntas, se)
    assert m.at["MN1", "listing_area"] == "Tribeca; Civic Center"
    assert m.at["MN2", "listing_area"] == "Midtown West"
    assert m.at["QN1", "listing_area"] == "Rockaway All"
    rents = pd.Series({"Tribeca": 7000.0, "Civic Center": 5000.0})
    assert mean_rent("Tribeca; Civic Center", rents) == 6000
    assert np.isnan(mean_rent(None, rents))


def test_match_liked_neighborhoods():
    from stoop.sources.familiarity import match_liked
    ntas = pd.DataFrame({"name": ["Williamsburg", "South Williamsburg", "Greenpoint",
                                  "Flatbush (West)-Ditmas Park-Parkville"]},
                        index=["BK0102", "BK0103", "BK0101", "BK1402"])
    assert match_liked(ntas, ["williamsburg"]) == ["BK0102"]          # exact name beats substring
    assert match_liked(ntas, ["Ditmas Park", "bk0101"]) == ["BK1402", "BK0101"]
    assert match_liked(ntas, ["Atlantis"]) == []


def test_bct_to_geoid():
    from stoop.sources.housing import bct_to_geoid
    assert bct_to_geoid("1000201") == "36061000201"     # Manhattan
    assert bct_to_geoid("3055700") == "36047055700"     # Brooklyn
    assert bct_to_geoid("9000100") is None and bct_to_geoid("") is None


def test_payload_carries_rent_per_bedroom():
    table = pd.DataFrame({"name": ["A"], "borough": ["Brooklyn"], "ntatype": ["0"], "rent_est": [4000.0],
                          "rent_est_0br": [3000.0], "rent_est_2br": [5500.0], "rent_source_2br": ["listings"]},
                         index=["BK1"])
    scores = pd.DataFrame({"rent": [50.0]}, index=["BK1"])
    geom = {"BK1": {"type": "Point", "coordinates": [-73.95, 40.7]}}
    p = build_payload(table, scores, geom, CFG)["geojson"]["features"][0]["properties"]
    assert p["rents"] == {"0": 3000.0, "2": 5500.0} and p["rent_sources"] == {"2": "listings"}


def test_payload_carries_minutes_per_destination():
    from stoop.sources.commute import dest_slug
    dests = CFG["you"]["commute_destinations"]
    cols = {f"commute_min_{dest_slug(d['name'])}": [10.0 + i] for i, d in enumerate(dests)}
    table = pd.DataFrame({"name": ["A"], "borough": ["Brooklyn"], "ntatype": ["0"], **cols}, index=["BK1"])
    scores = pd.DataFrame({"rent": [50.0]}, index=["BK1"])
    geom = {"BK1": {"type": "Point", "coordinates": [-73.95, 40.7]}}
    p = build_payload(table, scores, geom, CFG)["geojson"]["features"][0]["properties"]
    assert p["commutes"] == [10.0 + i for i in range(len(dests))]      # config order
    assert dest_slug("Flatiron-Union Sq") == "flatiron_union_sq"
    # a destination added since the last commute run: only its own slot is empty; the others stay routed
    two = {**CFG, "you": {**CFG["you"], "commute_destinations": [{"name": "New Office"}, {"name": "Work"}]}}
    t2 = pd.DataFrame({"name": ["A"], "borough": ["Brooklyn"], "ntatype": ["0"], "commute_min_work": [25.0]}, index=["BK1"])
    p = build_payload(t2, scores, geom, two)["geojson"]["features"][0]["properties"]
    assert p["commutes"] == [None, 25.0]
    p = build_payload(table.drop(columns=list(cols)), scores, geom, CFG)["geojson"]["features"][0]["properties"]
    assert p["commutes"] is None


def test_is_large_grocery():
    import pandas as pd
    from stoop.layers import is_large_grocery
    assert is_large_grocery("Trader Joe's", None) == "chain"
    assert is_large_grocery("Key Food", 1200) == "footprint"      # mixed-format chain: only by size
    assert is_large_grocery("Key Food", 400) is None
    assert is_large_grocery(pd.NA, None) is None and is_large_grocery(None, 950) == "footprint"


def test_bus_kind():
    from stoop.layers import bus_kind
    assert bus_kind("M14A+", "M14A-SBS") == "sbs" and bus_kind("B44+", "B44-SBS") == "sbs"
    assert bus_kind("BXM1", "BxM1") == "express" and bus_kind("SIM1C", "SIM1C") == "express"
    assert bus_kind("X27", "X27") == "express" and bus_kind("QM2", "QM2") == "express"
    assert bus_kind("B38", "B38") == "local" and bus_kind("Bx12", "Bx12") == "local" and bus_kind("Q70+", "Q70-SBS") == "sbs"


def test_gym_brand():
    from stoop.sources.convenience import gym_brand
    assert gym_brand("Equinox Hudson Yards") == "Equinox" and gym_brand("Blink Fitness") == "Blink Fitness"
    assert gym_brand("NYSC") == "New York Sports Club" and gym_brand("McCarren Park Recreation Center") == "NYC Parks recreation center"
    assert gym_brand("Orangetheory Fitness") is None and gym_brand("SoulCycle") is None and gym_brand("CKO Kickboxing") is None
    assert gym_brand(None) is None and gym_brand(pd.NA) is None


def test_grocery_brand():
    from stoop.layers import grocery_brand
    assert grocery_brand("Whole Foods Market Bowery") == "Whole Foods"
    assert grocery_brand("Trader Joe's") == "Trader Joe's" and grocery_brand("Key Food") == "Key Food"
    assert grocery_brand(None) == "Supermarket"


def test_commute_to_one_destination():
    from stoop.sources.commute import active_destination, apply_commute_choice
    cfg = {"you": {"commute_to": "chelsea", "commute_destinations": [{"name": "FiDi-WTC"}, {"name": "Chelsea"}]}}
    assert active_destination(cfg) == 1
    t = pd.DataFrame({"commute_min": [40.0], "commute_min_fidi_wtc": [30.0], "commute_min_chelsea": [50.0]})
    assert apply_commute_choice(t, cfg)["commute_min"].iloc[0] == 50.0
    assert active_destination({"you": {"commute_destinations": [{"name": "A"}]}}) is None      # unset: average
    cfg["you"]["commute_to"] = "nowhere"
    assert active_destination(cfg) == 0                                                         # unknown: first


def test_airport_minutes_takes_fastest_way_in():
    from stoop.sources.commute import airport_minutes
    hub = pd.DataFrame({"jfk_jamaica": [30.0, 60.0], "jfk_howard": [50.0, 20.0], "lga": [25.0, 40.0], "ewr_penn": [15.0, 50.0]})
    a = airport_minutes(hub)
    assert list(a["jfk"]) == [42.0, 34.0]          # Jamaica +12 vs Howard Beach +14, whichever is faster
    assert list(a["lga"]) == [25.0, 40.0] and list(a["ewr"]) == [57.0, 92.0]


def test_split_lines_by_boro():
    from stoop.layers import split_lines_by_boro
    # a line crossing from x<0 ("Manhattan") to x>0 ("Brooklyn"); boroughs by segment midpoint
    f = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-3, 0], [-1, 0], [1, 0], [3, 0], [5, 0]]},
          "properties": {"route": "L"}}]
    of = lambda xs, ys: ["Manhattan" if x < 0 else "Brooklyn" for x in xs]
    out = {o["properties"]["boro"]: o for o in split_lines_by_boro(f, of)}
    assert out["Manhattan"]["geometry"]["coordinates"] == [[-3, 0], [-1, 0]]
    assert out["Brooklyn"]["geometry"]["coordinates"] == [[-1, 0], [1, 0], [3, 0], [5, 0]]   # midpoint 0 -> Brooklyn
    assert out["Brooklyn"]["properties"]["route"] == "L"


def test_airport_route_cards():
    from datetime import timedelta
    from shapely.geometry import LineString
    from stoop.sources.airport_routes import best_routes, summarize_itineraries
    m = lambda x: timedelta(minutes=x)
    line = LineString([(-73.95, 40.72), (-73.94, 40.73)])
    rows = [  # option 0: walk, walk, G, E (34 min); option 1: one slow bus (60 min)
        ("BK1", "jfk_jamaica", 0, 0, "WALK", m(3), m(0), None, None, None),
        ("BK1", "jfk_jamaica", 0, 1, "WALK", m(2), m(0), None, None, None),
        ("BK1", "jfk_jamaica", 0, 2, "SUBWAY", m(10), m(4), "G", "G26", "G22"),
        ("BK1", "jfk_jamaica", 0, 3, "SUBWAY", m(12), m(3), "E", "F09", "G06"),
        ("BK1", "jfk_jamaica", 1, 0, "BUS", m(55), m(5), "Q99", "1", "2"),
        ("BK1", "jfk_howard", 0, 0, "SUBWAY", m(40), m(6), "A", "A1", "H28"),
    ]
    di = pd.DataFrame(rows, columns=["from_id", "to_id", "option", "segment", "transport_mode", "travel_time",
                                     "wait_time", "route_id", "start_stop_id", "end_stop_id"])
    di["geometry"] = line
    it = summarize_itineraries(di, {"G26": "Greenpoint Av", "G22": "Court Sq", "F09": "Court Sq", "G06": "Sutphin Blvd"}, {})
    j = it[("BK1", "jfk_jamaica")]
    assert j["min"] == 34 and [l["m"] for l in j["legs"]] == ["walk", "subway", "subway"]   # walks merged
    assert j["legs"][0]["min"] == 5 and j["legs"][1]["from"] == "Greenpoint Av" and j["legs"][2]["to"] == "Sutphin Blvd"
    card = best_routes(it, "BK1", {"jfk": 31.4})["jfk"]
    assert card["min"] == 46 and card["via"].startswith("Sutphin")        # 34 + 12 beats Howard Beach 46 + 14
    assert card["legs"][-1]["fixed"] and card["legs"][-1]["label"] == "AirTrain JFK" and card["car"] == 31


def test_runner_hex_score():
    from stoop.sources.runner_hexes import hex_center, runhex_score
    assert hex_center(0, 0) == (0, 0) and round(hex_center(1, 0)[0]) == 260 and hex_center(0, 2)[1] == 450
    hexes = {"0,0": 5, "1,0": 4, "0,1": 1, "40,0": 5}          # (40,0) is ~10 km away: ignored
    assert runhex_score((0, 0), hexes) == (5 + 4 + 1) / 3 * 20
    assert runhex_score((0, 0), {"0,0": 0}) == 0                # painted 0 = checked, no runners
    assert runhex_score((0, 0), {"40,0": 5}) is None            # nothing painted nearby = no data


def test_hex_ring_round_trip():
    from stoop.sources.runner_hexes import KX, KY, hex_center, hex_ring
    ring = hex_ring(10, -4)
    assert len(ring) == 7 and ring[0] == ring[-1]
    cx, cy = hex_center(10, -4)
    mx = sum(p[0] for p in ring[:6]) / 6 * KX
    my = sum(p[1] for p in ring[:6]) / 6 * KY
    assert abs(mx - cx) < 1 and abs(my - cy) < 1       # the outline is centered on its hex (within a meter)


def test_run_routes_score_is_access_only():
    import pandas as pd
    from stoop.sources.run_routes import run5k_scores
    mins = pd.DataFrame({"a": [20.0, 70.0, 80.0], "b": [3.0, 10.0, 90.0]}, index=["n1", "n2", "n3"])
    res = run5k_scores(mins, {"a": "Greenway", "b": ""})
    assert res.loc["n1", "run5k_min"] == 3 and res.loc["n1", "run5k_score"] == 100
    assert res.loc["n1", "run5k_route"] == "Unnamed path network"
    assert res.loc["n2", "run5k_min"] == 10 and res.loc["n2", "run5k_score"] == pytest.approx(80)
    assert res.loc["n3", "run5k_min"] == 60 and res.loc["n3", "run5k_score"] == 0   # nothing within an hour: 0, not no data
    assert pd.isna(res.loc["n3", "run5k_route"])


def test_run_routes_estimate_uses_nearest_access_point():
    from stoop.sources.run_routes import WALK_DETOUR, WALK_M_PER_MIN, estimate_minutes
    from stoop.sources.runner_hexes import KX
    routes = [{"id": "a", "access": [[-73.95 + 2000 / KX, 40.72], [-73.95 + 800 / KX, 40.72]]}]
    m = estimate_minutes({"n1": [-73.95, 40.72]}, routes)
    assert m.loc["n1", "a"] == pytest.approx(800 * WALK_DETOUR / WALK_M_PER_MIN, rel=1e-3)


_NODE = [1000]


def _way(lat, lon0, km, tags=None, start=None, end=None, n=10):
    """Made-up OSM way running east from (lat, lon0); shares nodes with others only via start/end."""
    from stoop.sources.runner_hexes import KX
    nodes = []
    for _ in range(n + 1):
        _NODE[0] += 1
        nodes.append(_NODE[0])
    if start is not None:
        nodes[0] = start
    if end is not None:
        nodes[-1] = end
    dlon = km * 1000 / KX
    return {"id": nodes[1], "nodes": nodes, "tags": {"highway": "footway", **(tags or {})},
            "geometry": [{"lat": lat, "lon": lon0 + dlon * i / n} for i in range(n + 1)]}


def test_run_routes_runnable_filters():
    from stoop.sources.run_routes import runnable
    assert runnable(_way(40.72, -73.95, 0.5))
    for tags in ({"footway": "sidewalk"}, {"footway": "crossing"}, {"access": "private"}, {"area": "yes"},
                 {"foot": "no"}):
        assert not runnable(_way(40.72, -73.95, 0.5, tags)), tags
    assert runnable(_way(40.72, -73.95, 0.5, {"access": "no", "foot": "yes"}))


def test_run_routes_networks_length_span_and_names():
    from stoop.sources.run_routes import networks, route_networks
    from stoop.sources.runner_hexes import KX
    g1 = _way(40.72, -73.95, 1.0, {"name": "Waterfront Greenway"}, end=1)
    g2 = _way(40.72, -73.95 + 1000 / KX, 1.0, {"name": "Waterfront Greenway"}, start=1, end=2)
    g3 = _way(40.72, -73.95 + 2000 / KX, 1.0, start=2)
    tangle = [_way(40.75 + k * 0.00005, -73.93, 0.15, {"name": "Pocket Park"}, start=3) for k in range(20)]
    stub = _way(40.78, -73.92, 0.5)
    ways = [g1, g2, g3, *tangle, stub]
    assert sorted(len(g) for g in networks(ways)) == [1, 3, 20]
    nets = {r["name"]: r for r in route_networks(ways)}
    assert nets["Waterfront Greenway"]["km"] == pytest.approx(3.0, rel=0.02)
    assert nets["Waterfront Greenway"]["fits_5k"] is True
    assert nets["Pocket Park"]["fits_5k"] is False            # 3 km of paths, but only ~150 m across
    assert len(nets) == 2                                     # the 0.5 km stub is below MIN_NETWORK_KM
    gaps = nets["Waterfront Greenway"]["access"]
    assert 11 <= len(gaps) <= 14                              # a point every ~250 m along 3 km


def test_run_routes_join_small_mapping_gaps_and_greenway_share():
    from stoop.sources.run_routes import JOIN_GAP_M, networks, route_networks
    from stoop.sources.runner_hexes import KX
    a = _way(40.72, -73.95, 1.5, {"name": "East River Esplanade"}, start=10, end=11)
    b = _way(40.72, -73.95 + (1500 + JOIN_GAP_M / 2) / KX, 1.5, {"name": "East River Esplanade"}, start=12)
    far = _way(40.72, -73.95 + (3000 + 40) / KX, 1.0, start=13)          # across a street: stays apart
    assert sorted(len(g) for g in networks([a, b, far])) == [1, 1, 1]  # shared nodes only
    assert sorted(len(g) for g in networks([a, b, far], JOIN_GAP_M)) == [1, 2]
    nets = route_networks([a, b, far])
    esp = next(r for r in nets if r["name"] == "East River Esplanade")
    assert esp["km"] == pytest.approx(3.0, rel=0.02) and esp["fits_5k"] and esp["greenway_share"] == 1.0
    assert all(r["greenway_share"] == 0 for r in nets if r is not esp)


def test_run_routes_fetch_reads_cached_tiles(tmp_path):
    import json

    from stoop.sources.run_routes import TILES, fetch_ways
    tdir = tmp_path / "tiles"
    tdir.mkdir()
    w = _way(40.72, -73.95, 1.0)
    for k in range(TILES * TILES):
        (tdir / f"tile_{k:02d}.json").write_text(json.dumps([w] if k == 3 else []))

    class NoNetwork:
        def post(self, *a, **k):
            raise AssertionError("should read the cache")

    assert [x["id"] for x in fetch_ways(tmp_path, session=NoNetwork())] == [w["id"]]


def test_run_routes_fast_estimate_matches_slow():
    from stoop.sources.run_routes import _estimate_minutes_fast, estimate_minutes
    routes = [{"id": "a", "access": [[-73.95, 40.72], [-73.94, 40.73]]}, {"id": "b", "access": [[-73.99, 40.70]]}]
    origins = {1: (-73.955, 40.721), 2: (-73.98, 40.71), 3: (-73.94, 40.74)}
    slow, fast = estimate_minutes(origins, routes), _estimate_minutes_fast(origins, routes)
    assert (abs(slow - fast) < 1e-9).all().all()


def test_run_routes_main_route_is_population_weighted():
    import pandas as pd
    from stoop.sources.run_routes import main_route
    grid = pd.DataFrame({"nta2020": ["A", "A", "A", "B"], "pop": [10, 500, 20, 5]}, index=[0, 1, 2, 3])
    routes = pd.Series(["Park X", "Park Y", "Park X", None], index=[0, 1, 2, 3])
    m = main_route(grid, routes)
    assert m["A"] == "Park Y" and "B" not in m.index


def test_runner_hexes_refuses_restricted_files():
    from stoop.sources.runner_hexes import is_restricted
    assert is_restricted({"meta": {"contains": "provider_api_derived"}})
    assert not is_restricted({"meta": {"sources": ["gpx", "osm_paths"], "source": "my GPX runs"}})
    assert not is_restricted({"hexes": {}})
