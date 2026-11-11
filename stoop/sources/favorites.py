"""Favorites: how close each area is to the bars and restaurants you like.

inputs/places.csv columns (only `name` is required):
  name, category, address, lat, lon, weight
A plain list of names, one per line with no header, works too.
Rows without lat/lon are geocoded with OpenStreetMap Nominatim (1 request/s,
cached in data/interim/geocode_cache.json). A name without an address keeps
every NYC branch Nominatim finds (chains, multi-location cafes); add an address
to pin one branch. Check data/interim/places_geocoded.csv and add lat/lon by
hand for anything it gets wrong.

Score = Σ over places of weight × exp(-(distance to its nearest branch / 700 m)²):
a place next door counts 1, one ~10 min walk away counts ~0.4, and a chain
counts once however many branches it has. A general food-and-drink density
from OSM is computed too, so areas near nothing on your list still show liveliness.
"""
from __future__ import annotations

import difflib
import io
import json
import logging
import re
import time
import unicodedata

import numpy as np
import pandas as pd

from .. import fetch, geo, osm

log = logging.getLogger("stoop.favorites")
NAME = "favorites"
DECAY_M = 700
FOOD_TAGS = {"amenity": ["bar", "pub", "restaurant", "cafe", "biergarten"]}


COLUMNS = ["name", "category", "address", "lat", "lon", "weight"]


def read_places(path) -> pd.DataFrame:
    # Skip only lines that *start* with '#', so an address like "Apt #2" survives.
    lines = [ln for ln in open(path, encoding="utf-8-sig").read().splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return pd.DataFrame(columns=COLUMNS)
    first = [c.strip().lower() for c in lines[0].split(",")]
    has_header = "name" in first
    text = io.StringIO("\n".join(lines))
    if has_header:
        df = pd.read_csv(text, skipinitialspace=True, dtype=str)
        df.columns = [str(c).strip().lower() for c in df.columns]
    else:   # headerless: columns in the documented order, trailing ones optional
        df = pd.read_csv(text, skipinitialspace=True, dtype=str, header=None, names=COLUMNS)
    for c in ["category", "address"]:
        if c not in df.columns:
            df[c] = ""
    for c in ["lat", "lon"]:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(1.0) if "weight" in df.columns else 1.0
    df["name"] = df["name"].fillna("").astype(str).str.strip()
    df = df[df["name"] != ""]
    df[["category", "address"]] = df[["category", "address"]].fillna("")
    df["place_id"] = np.arange(len(df))
    return df.reset_index(drop=True)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def same_name(query: str, found: str) -> bool:
    """Does a Nominatim hit's name plausibly refer to the place asked for?"""
    q, f = _norm(query), _norm(found)
    return bool(q and f) and (q in f or f in q or difflib.SequenceMatcher(None, q, f).ratio() >= 0.8)


def geocode(df: pd.DataFrame, cache_path) -> pd.DataFrame:
    """One output row per located branch (same place_id); unlocated places keep a NaN row."""
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    rows = []
    for _, r in df.iterrows():
        if pd.notna(r["lat"]) and pd.notna(r["lon"]):
            rows.append(r.to_dict())
            continue
        pinned = bool(r["address"])
        q = f"{r['name']}, {r['address']}, New York, NY" if pinned else f"{r['name']}, New York, NY"
        if q not in cache:
            time.sleep(1.1)   # Nominatim policy: max 1 request/second
            try:
                resp = fetch.SESSION.get("https://nominatim.openstreetmap.org/search",
                                         params={"q": q, "format": "json", "limit": 1 if pinned else 50,
                                                 "viewbox": "-74.26,40.92,-73.70,40.49", "bounded": 1},
                                         timeout=30)
                resp.raise_for_status()
                hits = resp.json()
                if not pinned:   # drop streets/areas that merely share a word with the name
                    hits = [h for h in hits if same_name(r["name"], h.get("name") or h["display_name"].split(",")[0])]
                cache[q] = [[float(h["lat"]), float(h["lon"])] for h in hits]
            except Exception as e:
                log.warning("geocode failed for %s: %s", q, e)
                continue
            cache_path.write_text(json.dumps(cache, indent=1))
        found = cache.get(q) or []
        if found and not isinstance(found[0], list):   # older cache format: a single [lat, lon]
            found = [found]
        found = list(dict.fromkeys(tuple(round(c, 5) for c in p) for p in found))   # dedupe repeated OSM objects
        if not found:
            rows.append(r.to_dict())
        for lat, lon in found:
            rows.append({**r.to_dict(), "lat": lat, "lon": lon})
    out = pd.DataFrame(rows, columns=df.columns)
    located = out.dropna(subset=["lat"])["place_id"].unique()
    missing = df.loc[~df["place_id"].isin(located), "name"].astype(str).tolist()
    if missing:
        log.warning("%d places could not be located; add an address or lat/lon in places.csv: %s",
                    len(missing), ", ".join(missing))
    return out


def favorites_score(cells: np.ndarray, branches_xy: np.ndarray, place_ids: np.ndarray,
                    weights: np.ndarray, walk_m: float) -> tuple[np.ndarray, np.ndarray]:
    """(Σ weight × decay to each place's nearest branch, count of places within walk_m)."""
    score, within = np.zeros(len(cells)), np.zeros(len(cells))
    for pid in np.unique(place_ids):
        m = place_ids == pid
        d = geo.nearest_dist(cells, branches_xy[m])
        score += weights[m][0] * np.exp(-(d / DECAY_M) ** 2)
        within += d <= walk_m
    return score, within


def build(ctx) -> pd.DataFrame:
    grid = ctx.grid
    cells = geo.cell_xy(grid)
    out = pd.DataFrame(index=ctx.ntas.index)

    path = ctx.inputs / "places.csv"
    if path.exists():
        places = geocode(read_places(path), ctx.interim / "geocode_cache.json")
        places.to_csv(ctx.interim / "places_geocoded.csv", index=False)
        ok = places.dropna(subset=["lat", "lon"])
        if len(ok):
            pxy = geo.to_xy(ok.lon.values, ok.lat.values)
            score, within = favorites_score(cells, pxy, ok.place_id.to_numpy(), ok.weight.to_numpy(float),
                                            ctx.cfg.get("walk_radius_m", 1000))
            out["fav_score"] = geo.to_nta(grid, score, "fav_score")
            out["fav_within_walk"] = geo.to_nta(grid, within, "fav_within_walk")
        log.info("favorites: %d/%d places located (%d branches)",
                 ok.place_id.nunique(), places.place_id.nunique(), len(ok))
    else:
        log.warning("no inputs/places.csv: favorites will use general food & drink density only")

    food = osm.features(ctx, FOOD_TAGS, "food_drink", ctx.wants_refresh(NAME))
    out["food_drink_600m"] = geo.to_nta(grid, geo.sum_within(cells, osm.point_xy(food), 600), "food_drink_600m")
    return out
