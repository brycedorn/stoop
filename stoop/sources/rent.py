"""Rent: median asking rent from listing data where you supply it, calibrated ACS elsewhere.

Listing rents are CSVs you provide (inputs/rents/, or downloaded from `sources.rent_csv_url` set in your
config.local.yaml): one row per area (columns areaName, Borough, areaType) and one column per month. They use their
own neighborhood names, so we match them to NTA names
(same borough, exact or close match). Anything unmatched gets the NTA's ACS
median gross rent × a per-borough ratio learned from the matched NTAs. ACS
includes long-time and rent-stabilized tenants, so it runs well below asking rents.

Review data/interim/rent_matches.csv and pin corrections in
inputs/rent_crosswalk.csv (columns: nta2020, listing_area).
"""
from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("stoop.rent")
NAME = "rent"

BEDROOM_FILE_HINTS = {
    0: ["studio"],
    1: ["onebd", "1bd", "1bed", "onebed", "one_bd"],
    2: ["twobd", "2bd", "2bed", "twobed", "two_bd"],
    3: ["threeplus", "3bd", "3bed", "threebd", "3plus"],
}
DEFAULT_ACS_UPLIFT = 1.45   # ACS -> asking rent when there's no listing data (also the public site's rents)
LISTING_BEDROOM_CODES = {0: "Studio", 1: "OneBd", 2: "TwoBd", 3: "ThreePlusBd"}


def download_listing_rents(url: str, dest: Path, refresh: bool = False) -> Path:
    """Fetch median-asking-rent CSVs (zipped, one per bedroom code + "All") from `url` ({b} = code) into `dest`."""
    import zipfile
    from .. import fetch
    dest.mkdir(parents=True, exist_ok=True)
    for b in [*LISTING_BEDROOM_CODES.values(), "All"]:
        z = fetch.download(url.format(b=b), dest / f"medianAskingRent_{b}.zip", refresh)
        with zipfile.ZipFile(z) as zf:
            for member in zf.namelist():   # extract CSVs only, flattened (never trust archive paths)
                if member.lower().endswith(".csv"):
                    (dest / Path(member).name).write_bytes(zf.read(member))
    return dest


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace("st.", "saint")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def nta_name_variants(name: str) -> list[str]:
    """'Bedford-Stuyvesant (East)' -> ['bedford stuyvesant east', 'bedford stuyvesant', 'bedford', 'stuyvesant']."""
    base = re.sub(r"\(.*?\)", "", name)
    pieces = [p for p in re.split(r"[-/]", base) if p.strip()]
    out = [_norm(name), _norm(base), *(_norm(p) for p in pieces)]
    return list(dict.fromkeys(v for v in out if v))


# NTA name piece (normalized) -> listing-data area, where the two use different names for the same place.
AREA_ALIASES = {
    ("manhattan", "hell s kitchen"): "Midtown West",
    ("manhattan", "turtle bay"): "Midtown East",
    ("manhattan", "east midtown"): "Midtown East",
    ("manhattan", "murray hill"): "Midtown East",      # the listings' Midtown East covers Murray Hill + Kips Bay
    ("manhattan", "kips bay"): "Midtown East",
    ("manhattan", "harlem"): "Central Harlem",
    ("manhattan", "gramercy"): "Gramercy Park",
    ("queens", "rockaway beach"): "Rockaway All",
    ("queens", "far rockaway"): "Rockaway All",
    ("queens", "rockaway park"): "Rockaway All",
    ("queens", "ravenswood"): "Long Island City",
    ("queens", "dutch kills"): "Long Island City",
    ("queens", "old astoria"): "Astoria",
    ("brooklyn", "sea gate"): "Seagate",
    ("bronx", "westchester square"): "Westchester Village",
    ("bronx", "kingsbridge heights"): "Kingsbridge",
}
AREA_SEP = "; "


def match_listing_areas(ntas: pd.DataFrame, se: pd.DataFrame, cutoff: float = 0.88) -> pd.DataFrame:
    """Match NTAs (index nta2020; cols name, borough) to listing-data areas (cols area, borough).

    Every name piece that exactly matches a listing area (directly or via AREA_ALIASES)
    is kept, joined with "; " (e.g. "Tribeca; Civic Center"); rents are averaged later.
    Failing that, the closest fuzzy match above `cutoff`. Returns DataFrame indexed by
    nta2020 with listing_area, match_score (1.0 = exact) and best_candidate.
    """
    rows = []
    for nta, r in ntas.iterrows():
        boro = str(r["borough"]).lower()
        cands = se[se["borough"].str.lower() == boro]
        by_norm = {_norm(a): a for a in cands["area"]}
        variants = nta_name_variants(r["name"])
        exact = []
        for v in variants:
            hit = by_norm.get(v) or (AREA_ALIASES.get((boro, v)) if AREA_ALIASES.get((boro, v)) in set(cands["area"]) else None)
            if hit and hit not in exact:
                exact.append(hit)
        if exact:
            rows.append({"nta2020": nta, "listing_area": AREA_SEP.join(exact), "match_score": 1.0, "best_candidate": exact[0]})
            continue
        best, best_score = None, 0.0
        for norm_area, area in by_norm.items():
            for v in variants:
                score = difflib.SequenceMatcher(None, norm_area, v).ratio()
                if score > best_score:
                    best, best_score = area, score
        rows.append({"nta2020": nta, "listing_area": best if best_score >= cutoff else None,
                     "match_score": round(best_score, 3), "best_candidate": best})
    return pd.DataFrame(rows).set_index("nta2020")


def mean_rent(listing_area, listing_rent: pd.Series) -> float:
    """Average listing rent over a "; "-joined list of areas (NaN if none have data)."""
    if not isinstance(listing_area, str) or not listing_area:
        return np.nan
    vals = listing_rent.reindex([a.strip() for a in listing_area.split(AREA_SEP.strip())]).dropna()
    return float(vals.mean()) if len(vals) else np.nan


def read_listing_rents(folder: Path, bedrooms: int) -> pd.DataFrame | None:
    """Latest median asking rent per listing area from the CSVs."""
    files = list(Path(folder).glob("*.csv")) if Path(folder).exists() else []
    rent_files = [f for f in files if "rent" in f.name.lower()]
    pick = None
    for f in rent_files:
        n = f.name.lower().replace("_", "").replace("-", "")
        if any(h.replace("_", "") in n for h in BEDROOM_FILE_HINTS.get(min(bedrooms, 3), [])):
            pick = f
    pick = pick or next((f for f in rent_files if "all" in f.name.lower()), None)
    if pick is None:
        return None
    df = pd.read_csv(pick)
    month_cols = [c for c in df.columns if re.match(r"^\d{4}-\d{2}", str(c))]
    if not month_cols:
        raise ValueError(f"{pick.name}: no YYYY-MM columns found")
    vals = df[sorted(month_cols)].apply(pd.to_numeric, errors="coerce")
    # latest month per row, falling back up to 6 months for sparse areas
    latest = vals.iloc[:, -6:].ffill(axis=1).iloc[:, -1]
    out = pd.DataFrame({
        "area": df["areaName"], "borough": df["Borough"],
        "area_type": df.get("areaType", "neighborhood"), "listing_rent": latest,
    }).dropna(subset=["listing_rent"])
    out = out[out["area_type"].astype(str).str.lower() == "neighborhood"]
    log.info("listing rents: %s, %d areas, latest month %s", pick.name, len(out), sorted(month_cols)[-1])
    return out


BEDROOM_COUNTS = (0, 1, 2, 3)   # studio, 1, 2, 3+; the map switches between them live


def estimate_rent(ctx, base: pd.DataFrame, beds: int, listing_dir: Path | None):
    """(rent_est, rent_source, matches) for one bedroom count."""
    acs = base[f"acs_rent_{beds}br"].fillna(base["acs_rent_all"])
    ntas = ctx.ntas[["name", "borough"]]
    se = read_listing_rents(listing_dir, beds) if listing_dir else None
    if se is None:
        return acs * DEFAULT_ACS_UPLIFT, pd.Series("acs_scaled", index=base.index), None

    m = match_listing_areas(ntas, se)
    xw_path = ctx.inputs / "rent_crosswalk.csv"
    if xw_path.exists():
        xw = pd.read_csv(xw_path).dropna().rename(columns={"se_area": "listing_area"}).set_index("nta2020")["listing_area"]
        m.loc[m.index.intersection(xw.index), "listing_area"] = xw
        m.loc[m.index.intersection(xw.index), "match_score"] = 1.0
    listing_rent = se.drop_duplicates("area").set_index("area")["listing_rent"]
    m["listing_rent"] = m["listing_area"].map(lambda a: mean_rent(a, listing_rent))
    m["rent_acs"] = acs

    # Per-borough asking/ACS ratio from matched NTAs, for areas the listings don't cover
    ratio = (m["listing_rent"] / acs).replace([np.inf, -np.inf], np.nan)
    by_boro = ratio.groupby(ntas["borough"]).median()
    city = ratio.median() if ratio.notna().any() else DEFAULT_ACS_UPLIFT
    est = m["listing_rent"].fillna(acs * ntas["borough"].map(by_boro).fillna(city))
    source = pd.Series(np.where(m["listing_rent"].notna(), "listings", "acs_calibrated"), index=m.index)
    log.info("rent %s: %d NTAs matched to listing areas, ratio by borough %s", BEDROOM_LABELS[beds],
             m["listing_rent"].notna().sum(), by_boro.round(2).to_dict())
    return est, source, m


BEDROOM_LABELS = {0: "studio", 1: "1br", 2: "2br", 3: "3br+"}


def build(ctx) -> pd.DataFrame:
    base = pd.read_parquet(ctx.interim / "features_neighborhoods.parquet")
    beds = min(int(ctx.cfg["you"].get("bedrooms", 1)), 3)

    listing_dir = ctx.root / ctx.src.get("rents_dir", "inputs/rents")
    hand_placed = listing_dir.exists() and any("rent" in f.name.lower() for f in listing_dir.glob("*.csv"))
    url = ctx.src.get("rent_csv_url")
    if not hand_placed:
        listing_dir = None
        if url:
            try:
                listing_dir = download_listing_rents(url, ctx.raw / "listing_rents", ctx.wants_refresh(NAME))
            except Exception as e:
                log.warning("listing rent download failed (%s): estimating from ACS × %.2f", e, DEFAULT_ACS_UPLIFT)
        else:
            log.info("no listing rents (inputs/rents/ or sources.rent_csv_url): estimating from ACS × %.2f",
                     DEFAULT_ACS_UPLIFT)

    out = pd.DataFrame(index=base.index)
    prev = None
    for b in BEDROOM_COUNTS:
        est, source, m = estimate_rent(ctx, base, b, listing_dir)
        # Thin listing mixes can put a median 2BR below the 1BR (Gramercy, Tremont...);
        # never let a bigger apartment come out cheaper than a smaller one in the same area.
        if prev is not None:
            est = np.fmax(est, prev)
        prev = est
        out[f"rent_est_{b}br"] = est
        out[f"rent_source_{b}br"] = source
        if b == beds:   # your configured bedroom count drives the Python-side score and QA
            out["rent_est"], out["rent_source"] = est, source
            out["rent_acs"] = base[f"acs_rent_{b}br"].fillna(base["acs_rent_all"])
            if m is not None:
                m.join(ctx.ntas[["name", "borough"]]).to_csv(ctx.interim / "rent_matches.csv")
    return out
