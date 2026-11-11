"""Airport routes: for each residential neighborhood, the fastest transit itinerary to JFK, LaGuardia and Newark
(legs, stops, path) and the driving time without traffic. Shown on the map when you hover or click an airport.

Needs r5py + Java 21, like the commute step (`config.yaml` transit). Routes from each neighborhood's label point
(inside it, near where people live). JFK and Newark end with the fixed AirTrain / NJ Transit leg from
commute.AIRPORT_HUBS, since those aren't in the MTA GTFS. Car times are free-flow: no traffic data is free.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import timedelta

import pandas as pd

from .. import fetch

log = logging.getLogger("stoop.airport_routes")
NAME = "airport_routes"

# Where the plane markers are (terminal areas); car trips route here.
AIRPORT_TERMINALS = {"jfk": (40.6413, -73.7781), "lga": (40.7769, -73.8740), "ewr": (40.6895, -74.1745)}
# hub -> (where you change, the fixed last leg)
HUB_INFO = {
    "jfk_jamaica": ("Sutphin Blvd-Archer Av (Jamaica)", "AirTrain JFK"),
    "jfk_howard": ("Howard Beach-JFK", "AirTrain JFK"),
    "lga": (None, None),
    "ewr_penn": ("Penn Station", "NJ Transit + AirTrain Newark"),
}
WALK_MAX_MIN = 25


def _r(v: float) -> float:
    return round(float(v), 5)


def gtfs_names(ctx) -> tuple[dict, dict]:
    """stop_id -> stop name and route_id -> short name, from the GTFS feeds the commute step downloads."""
    stops, routes = {}, {}
    for i, url in enumerate(ctx.src.get("gtfs") or []):
        path = ctx.raw / "transit" / f"gtfs_{i}.zip"
        if not path.exists():
            path = fetch.download(url, path)
        z = zipfile.ZipFile(path)
        read = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str).fillna("")
        for r in read("stops.txt").itertuples():
            stops.setdefault(r.stop_id, r.stop_name)
        for r in read("routes.txt").itertuples():
            routes.setdefault(r.route_id, r.route_short_name or r.route_id)
    return stops, routes


def _minutes(td) -> float:
    if td is None or (not isinstance(td, timedelta) and pd.isna(td)):
        return 0.0
    return td.total_seconds() / 60 if isinstance(td, timedelta) else float(pd.Timedelta(td).total_seconds()) / 60


def _mode(m) -> str:
    return str(getattr(m, "name", m)).split(".")[-1].lower()


def _coords(geom, tol=0.0002) -> list:
    if geom is None or getattr(geom, "is_empty", True):
        return []
    g = geom.simplify(tol)
    parts = [g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))
    return [[_r(x), _r(y)] for part in parts for x, y, *_ in part.coords]


def summarize_itineraries(di: pd.DataFrame, stop_names: dict, route_names: dict) -> dict:
    """{(from_id, to_id): {"min": total minutes, "legs": [...]}} keeping the fastest option per pair.
    A leg: {"m": mode, "min": ride or walk minutes, "wait": minutes, "r": route, "from": stop, "to": stop, "g": path}.
    Consecutive walk legs are merged."""
    out = {}
    if di is None or len(di) == 0:
        return out
    di = di.copy()
    di["_t"] = [_minutes(a) + _minutes(b) for a, b in zip(di["travel_time"], di["wait_time"])]
    for (f, t), g in di.groupby(["from_id", "to_id"]):
        totals = g.groupby("option")["_t"].sum()
        best = g[g["option"] == totals.idxmin()].sort_values("segment")
        legs = []
        for r in best.itertuples():
            mode = _mode(r.transport_mode)
            leg = {"m": mode, "min": round(_minutes(r.travel_time), 1), "wait": round(_minutes(r.wait_time), 1),
                   "g": _coords(r.geometry)}
            if mode != "walk":
                rid = str(r.route_id or "")
                leg.update(r=route_names.get(rid, rid), **{"from": stop_names.get(str(r.start_stop_id), ""),
                                                          "to": stop_names.get(str(r.end_stop_id), "")})
            if legs and mode == "walk" and legs[-1]["m"] == "walk":
                legs[-1]["min"] = round(legs[-1]["min"] + leg["min"], 1)
                legs[-1]["g"] += leg["g"]
            else:
                legs.append(leg)
        out[(f, t)] = {"min": round(float(totals.min()), 1), "legs": legs}
    return out


def best_routes(itins: dict, nta: str, car: dict) -> dict:
    """Per airport, the hub with the fastest itinerary + fixed last leg, as the map's route card wants it."""
    from .commute import AIRPORT_HUBS
    out = {}
    for code, (lat, lon) in AIRPORT_TERMINALS.items():
        best = None
        for hub, (airport, hlat, hlon, leg_min) in AIRPORT_HUBS.items():
            it = itins.get((nta, hub))
            if airport != code or not it:
                continue
            total = it["min"] + leg_min
            if best is None or total < best["min"]:
                via, label = HUB_INFO.get(hub, (None, None))
                legs = list(it["legs"])
                if leg_min:
                    legs.append({"m": "airtrain" if code == "jfk" else "rail", "label": label, "min": leg_min,
                                 "g": [[_r(hlon), _r(hlat)], [_r(lon), _r(lat)]], "fixed": True})
                best = {"min": round(total), "via": via, "legs": legs}
        if best or car.get(code) is not None:
            out[code] = {**(best or {}), "car": None if car.get(code) is None else round(car[code])}
    return out


def build(ctx) -> pd.DataFrame:
    from .commute import AIRPORT_HUBS, configure_r5, departure_time
    from ..export import label_points
    out = pd.DataFrame(index=ctx.ntas.index)
    configure_r5(ctx)
    try:
        import r5py
    except Exception as e:  # ImportError, or Java missing at import
        log.warning("r5py unavailable (%s); no airport routes", e)
        return out
    import geopandas as gpd
    from shapely.geometry import Point

    pbf = fetch.download(ctx.src["osm_pbf"], ctx.raw / "transit" / "nyc.osm.pbf")
    gtfs = [fetch.download(u, ctx.raw / "transit" / f"gtfs_{i}.zip") for i, u in enumerate(ctx.src["gtfs"])]
    log.info("building R5 transport network...")
    network = r5py.TransportNetwork(str(pbf), [str(g) for g in gtfs])

    res = ctx.ntas[ctx.ntas["ntatype"].astype(str) == "0"]
    labels = label_points(res)
    origins = gpd.GeoDataFrame({"id": list(labels)}, geometry=[Point(*labels[k]) for k in labels], crs=4326)
    hubs = gpd.GeoDataFrame({"id": list(AIRPORT_HUBS)}, geometry=[Point(v[2], v[1]) for v in AIRPORT_HUBS.values()], crs=4326)
    terms = gpd.GeoDataFrame({"id": list(AIRPORT_TERMINALS)},
                             geometry=[Point(lon, lat) for lat, lon in AIRPORT_TERMINALS.values()], crs=4326)
    dep = departure_time(ctx.cfg["you"].get("commute_departure"))

    log.info("transit itineraries: %d neighborhoods x %d airport hubs...", len(origins), len(hubs))
    di = pd.DataFrame(r5py.DetailedItineraries(
        network, origins, hubs, force_all_to_all=True, departure=dep,
        transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
        max_time=timedelta(minutes=150), max_time_walking=timedelta(minutes=WALK_MAX_MIN)))
    log.info("driving times (no traffic)...")
    car = pd.DataFrame(r5py.TravelTimeMatrix(
        network, origins=origins, destinations=terms, departure=dep,
        transport_modes=[r5py.TransportMode.CAR], max_time=timedelta(minutes=150)))
    car = car.pivot(index="from_id", columns="to_id", values="travel_time")

    stop_names, route_names = gtfs_names(ctx)
    itins = summarize_itineraries(di, stop_names, route_names)
    routes = {}
    for nta in labels:
        c = {code: (None if pd.isna(car.at[nta, code]) else float(car.at[nta, code]))
             for code in AIRPORT_TERMINALS if nta in car.index and code in car.columns}
        routes[nta] = best_routes(itins, nta, c)
    for code in AIRPORT_TERMINALS:
        out[f"air_route_{code}"] = pd.Series({n: json.dumps(r[code], separators=(",", ":")) if code in r else None
                                              for n, r in routes.items()})
        out[f"car_{code}_min"] = pd.Series({n: (r.get(code) or {}).get("car") for n, r in routes.items()}, dtype=float)
    log.info("airport routes: %d neighborhoods, %d itineraries", len(routes), len(itins))
    return out
