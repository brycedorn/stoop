"""Pipeline steps in run order. Each returns a DataFrame indexed by nta2020."""
from . import (air_quality, airport_routes, base, commute, convenience, familiarity, favorites, green, housing, rent, run_routes,
               runner_hexes, running, safety)

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
    "flood": convenience.build_flood,
    "air_quality": air_quality.build,   # PM2.5 / NO2 by community district (EHDP); detail panel only
    "familiarity": familiarity.build,   # no downloads; rerun after editing liked_neighborhoods
    "runner_hexes": runner_hexes.build,   # runner traffic by hex (sources.runner_hexes, from any tool)
    "run_routes": run_routes.build,       # car-free 5K routes nearby (OpenStreetMap paths)
}
