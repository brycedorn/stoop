"""Pipeline steps in run order. Each returns a DataFrame indexed by nta2020."""
from . import (air_quality, airport_routes, base, commute, convenience, familiarity, favorites, green, housing, rent, run_routes,
               running, safety)

STEPS = {
    "neighborhoods": base.build,     # must run first: population used by later steps
    "rent": rent.build,
    "housing": housing.build,       # apartment size (PLUTO)
    "commute": commute.build,
    "airport_routes": airport_routes.build,   # route cards for the map's airport markers (r5py; ~15 min)
    "green": green.build,            # before running: builds the parks cache
    "running": running.build,
    "favorites": favorites.build,
    "safety": safety.build_safety,
    "quiet": safety.build_quiet,
    "errands": convenience.build_errands,
    "gyms": convenience.build_gyms,     # full-size gyms (chains, YMCAs, rec centers) from the errands OSM cache
    "citibike": convenience.build_citibike,
    "air_quality": air_quality.build,   # PM2.5 / NO2 by district (EHDP) + distance from highways (OSM)
    "familiarity": familiarity.build,   # no downloads; rerun after editing liked_neighborhoods
    "run_routes": run_routes.build,       # car-free 5K routes nearby (OpenStreetMap paths)
}
