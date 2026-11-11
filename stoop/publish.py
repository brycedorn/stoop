"""`python -m stoop publish`: the public site, built from cached results (no pipeline run, about a minute).

What's published is what stoop derives, never a source's own records:
- factor scores (neighborhoods and hexes), commute and walking times stoop routed itself, and per-person or
  per-area figures stoop computed from open data (NYC Open Data, Census, MTA, NYC Health, OpenStreetMap);
- rent as Census estimates only (ACS median rent by bedroom count, scaled toward asking rents), in $500 bands:
  listing rents you supply locally are never published, not even through the calibration ratio;
- context layers from open data (parks, subway, bus, grocery, gyms, airports), credited on the map.
Nothing personal: it reads config.yaml only (never config.local.yaml), and leaves out your places, liked areas,
your GPS runs and runner hexes. `check_site` refuses to finish if any of that shows up in the output.

The site goes to `site/` (gitignored) and, with --commit, onto the `gh-pages` branch as one new commit, without
touching your working tree. Push it with `git push origin gh-pages`; GitHub Pages serves that branch.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("stoop.publish")

RENT_BAND = 500
RESTRICTED_NAMES = ["listings"]   # plus config.local.yaml `publish.never_name`: sources the site must never name
SITE_FILES = ["index.html", "app.js", "style.css"]
PERSONAL_COLUMNS = {"familiar_dist_m", "fav_score", "fav_within_walk", "activity_density", "runhex_score"}
PERSONAL_LAYERS = ("places", "runhex")
PERSONAL_FACTORS = {"familiarity", "runhex"}


def band(rent):
    """Middle of the RENT_BAND-wide band the rent falls in ($3,620 -> 3,750 for the $3,500-4,000 band)."""
    r = np.asarray(pd.to_numeric(rent, errors="coerce"), float)
    return np.where(np.isnan(r), np.nan, np.floor(r / RENT_BAND) * RENT_BAND + RENT_BAND / 2)


CENSUS_SOURCE = "census_estimate"


def census_rents(t: pd.DataFrame, bedrooms: int) -> pd.DataFrame:
    """Rents from Census ACS only: median rent for the bedroom count (else all units) × DEFAULT_ACS_UPLIFT, never
    smaller for more bedrooms. Replaces every rent_est/rent_source column; no listing data goes into them."""
    from .sources.rent import DEFAULT_ACS_UPLIFT
    t = t.copy()
    prev = None
    for b in range(4):
        acs = pd.to_numeric(t.get(f"acs_rent_{b}br"), errors="coerce") if f"acs_rent_{b}br" in t else None
        allu = pd.to_numeric(t.get("acs_rent_all"), errors="coerce")
        est = (acs.fillna(allu) if acs is not None else allu) * DEFAULT_ACS_UPLIFT
        if prev is not None:
            est = np.fmax(est, prev)
        prev = est
        t[f"rent_est_{b}br"] = est
        t[f"rent_source_{b}br"] = np.where(est.notna(), CENSUS_SOURCE, None)
    b = min(int(bedrooms), 3)
    t["rent_est"], t["rent_source"] = t[f"rent_est_{b}br"], t[f"rent_source_{b}br"]
    return t


def public_table(table: pd.DataFrame, bedrooms: int = 1) -> pd.DataFrame:
    """The merged feature table with personal columns dropped, rents from Census only, in bands."""
    t = table.drop(columns=[c for c in table.columns if c in PERSONAL_COLUMNS], errors="ignore").copy()
    t = census_rents(t, bedrooms)
    for c in [c for c in t.columns if re.fullmatch(r"rent_est(_\dbr)?", c)]:
        t[c] = band(t[c])
    for c in [c for c in t.columns if (c.startswith("rent_") or c.startswith("acs_rent"))
              and not re.fullmatch(r"rent_(est|source)(_\dbr)?", c)]:
        t = t.drop(columns=c)        # every other rent figure (listing ratios, raw ACS) stays local
    return t


def build_site(out: Path, root: Path | None = None) -> Path:
    from . import export, hexes, layers, scoring
    from .cli import merge_features
    from .context import ROOT, Context, load_config
    from .sources.commute import apply_commute_choice
    root = Path(root or ROOT)
    cfg = load_config(root / "config.yaml", local=False)
    cfg["default_weights"] = {k: (0 if k in PERSONAL_FACTORS else v) for k, v in cfg["default_weights"].items()}
    cfg["you"]["liked_neighborhoods"] = []
    for d in cfg["you"]["commute_destinations"]:
        d.pop("label", None)
    ctx = Context(cfg=cfg, root=root)
    table = public_table(apply_commute_choice(merge_features(ctx), cfg), cfg["you"].get("bedrooms", 1))
    residential = table["ntatype"].astype(str) == "0"
    scores = scoring.score_table(table, cfg, residential)
    for k in PERSONAL_FACTORS & set(scores.columns):
        scores[k] = np.nan

    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    for f in SITE_FILES:
        shutil.copy2(root / "web" / f, out / f)
    (out / ".nojekyll").write_text("", encoding="utf-8")   # serve files as they are

    st_path = ctx.interim / "subway_stations.json"
    stations = json.loads(st_path.read_text()) if st_path.exists() else None
    payload = export.build_payload(table, scores, export.geometries_from_gdf(ctx.ntas), cfg,
                                   labels=export.label_points(ctx.ntas), stations=stations)
    payload["meta"]["rent_band"] = RENT_BAND
    payload["meta"]["rent_basis"] = "census"
    payload["meta"]["metrics"] = {k: v for k, v in payload["meta"]["metrics"].items() if k not in PERSONAL_COLUMNS}
    for f in payload["geojson"]["features"]:
        f["properties"]["metrics"] = {k: v for k, v in f["properties"]["metrics"].items() if k not in PERSONAL_COLUMNS}
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    (out / "data" / "stoop.js").write_text(f"window.STOOP_DATA={text};\n", encoding="utf-8")
    export.write_airport_routes(table, out)
    layers.write_layers(ctx, out, skip=PERSONAL_LAYERS)
    hexes.write(hexes.build_payload(ctx, table, scores, residential, drop=PERSONAL_COLUMNS), out)
    check_site(out, root)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    log.info("public site written to %s (%.1f MB)", out, size)
    return out


def _load_js(path: Path) -> dict:
    s = path.read_text(encoding="utf-8")
    return json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))


def personal_strings(root: Path) -> list[str]:
    """Words that must never appear in the public site: your destination labels, places and liked areas."""
    import yaml
    words = []
    local = root / "config.local.yaml"
    if local.exists():
        you = (yaml.safe_load(local.read_text(encoding="utf-8")) or {}).get("you") or {}
        local_cfg = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
        words += [str(d["label"]) for d in you.get("commute_destinations") or [] if d.get("label")]
        words += [str(w) for w in (local_cfg.get("publish") or {}).get("never_name") or []]
    places = root / "inputs" / "places.csv"
    if places.exists():       # a CSV with a `name` column, or a plain list of names (no header)
        lines = [ln.strip() for ln in places.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#")]
        if lines and "name" in [c.strip().lower() for c in lines[0].split(",")]:
            words += [str(n) for n in pd.read_csv(places, comment="#")["name"].dropna()]
        else:
            words += [ln.split(",")[0] for ln in lines]
    return sorted({w.strip() for w in words if len(w.strip()) >= 4})


def check_site(out: Path, root: Path) -> None:
    """Refuse a site that carries anything personal or a source's exact rent (raises ValueError)."""
    problems = []
    data = _load_js(out / "data" / "stoop.js")
    meta = data["meta"]
    if meta.get("liked_neighborhoods"):
        problems.append("liked neighborhoods in meta")
    if any(d.get("label") for d in meta.get("destinations", [])):
        problems.append("destination labels in meta")
    band_mid = RENT_BAND / 2
    for f in data["geojson"]["features"]:
        p = f["properties"]
        rents = [p["metrics"].get("rent_est")] + list((p.get("rents") or {}).values())
        if any(r is not None and (r - band_mid) % RENT_BAND for r in rents):
            problems.append(f"exact rent for {p['id']}")
            break
        if any(v not in (None, CENSUS_SOURCE) for v in [p["metrics"].get("rent_source"), *(p.get("rent_sources") or {}).values()]):
            problems.append(f"non-Census rent for {p['id']}")
            break
        if set(p["metrics"]) & PERSONAL_COLUMNS:
            problems.append(f"personal metric for {p['id']}")
            break
        if any(p["scores"].get(k) is not None for k in PERSONAL_FACTORS):
            problems.append(f"personal factor score for {p['id']}")
            break
    lay = _load_js(out / "data" / "layers.js")
    for k in PERSONAL_LAYERS:
        if lay.get(k) and (lay[k].get("features") if isinstance(lay[k], dict) else lay[k]):
            problems.append(f"layer {k}")
    hx_path = out / "data" / "hexes.js"
    if hx_path.exists():
        hx = _load_js(hx_path)
        if PERSONAL_FACTORS & set(hx["factors"]):
            problems.append("personal factor in hexes")
    text = "\n".join(p.read_text(encoding="utf-8").lower() for p in (out / "data").glob("*.js"))
    for w in personal_strings(root) + RESTRICTED_NAMES:
        if w.lower() in text:
            problems.append(f"personal text: {w!r}")
    if problems:
        raise ValueError("public site not written safely: " + "; ".join(problems))
    log.info("site check passed: no personal data, rents in $%d bands", RENT_BAND)


def commit_pages(site: Path, root: Path, branch: str = "gh-pages", message: str | None = None) -> str:
    """Commit `site` as the whole tree of `branch` (parent = its current tip), leaving your checkout untouched."""
    def git(*args, env=None):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                              env={**os.environ, **(env or {})}).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("--work-tree", str(site), "add", "-A", ".", env=env)
        tree = git("write-tree", env=env)
    parent = subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], cwd=root,
                            capture_output=True, text=True).stdout.strip()
    if parent and git("rev-parse", f"{parent}^{{tree}}") == tree:
        log.info("%s already has this site; nothing to commit", branch)
        return parent
    msg = message or "Publish site"
    commit = git("commit-tree", tree, *(["-p", parent] if parent else []), "-m", msg)
    git("update-ref", f"refs/heads/{branch}", commit)
    log.info("committed the site to %s (%s); push with: git push origin %s", branch, commit[:7], branch)
    return commit
