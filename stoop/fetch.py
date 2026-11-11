"""Download helpers with on-disk caching.

Everything lands in data/raw/. A cached file is reused unless `refresh=True`,
so re-running the pipeline is cheap and works offline once data is cached.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("stoop.fetch")

USER_AGENT = "stoop-neighborhood-finder/0.1 (personal research project)"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT
if os.environ.get("SOCRATA_APP_TOKEN"):
    SESSION.headers["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]


def download(url: str, dest: Path, refresh: bool = False, timeout: int = 600) -> Path:
    """Stream a URL to `dest` (skipped if it exists and refresh is False)."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading %s", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with SESSION.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def socrata_rows(
    base: str,
    dataset: str,
    raw_dir: Path,
    *,
    select: str | None = None,
    where: str | None = None,
    group: str | None = None,
    order: str = ":id",
    page: int = 50_000,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch every row of a Socrata dataset matching `where`, paging with $offset.

    `group` aggregates server-side ($group); pass an `order` over the grouped columns then.
    """
    parts = (select, where) if group is None and order == ":id" else (select, where, group, order)
    cache = Path(raw_dir) / f"socrata_{dataset}_{_key(*parts)}.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)
    url = f"{base.rstrip('/')}/resource/{dataset}.json"
    frames, offset = [], 0
    while True:
        params = {"$limit": page, "$offset": offset, "$order": order}
        if select:
            params["$select"] = select
        if where:
            params["$where"] = where
        if group:
            params["$group"] = group
        for attempt in range(4):
            try:
                r = SESSION.get(url, params=params, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 3:
                    raise
                log.warning("retrying %s (%s)", dataset, e)
                throttled = getattr(e.response, "status_code", None) == 429
                time.sleep((30 if throttled else 5) * (attempt + 1))
        rows = r.json()
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        log.info("  %s: %d rows", dataset, offset + len(rows))
        if len(rows) < page:
            break
        offset += page
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def socrata_geojson(base: str, dataset: str, raw_dir: Path, refresh: bool = False) -> Path:
    """Download a Socrata geospatial dataset as GeoJSON.

    NYC Open Data serves geometry through a few different endpoints depending
    on dataset age, so try each in turn.
    """
    dest = Path(raw_dir) / f"socrata_{dataset}.geojson"
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return dest
    base = base.rstrip("/")
    candidates = [
        f"{base}/resource/{dataset}.geojson?$limit=5000000",
        f"{base}/api/geospatial/{dataset}?method=export&format=GeoJSON",
        f"{base}/api/v3/views/{dataset}/query.geojson?accessType=DOWNLOAD",
    ]
    last = None
    for url in candidates:
        try:
            download(url, dest, refresh=True)
            with open(dest, "rb") as f:
                head = f.read(4096)
            # Must contain at least one feature: map views and broken exports return an empty shell.
            if (b"FeatureCollection" in head or b'"features"' in head) and b'"Feature"' in head.replace(b" ", b""):
                return dest
            last = f"no features in response from {url} ({dest.stat().st_size} bytes)"
        except requests.RequestException as e:
            last = e
            log.debug("endpoint failed: %s (%s)", url, e)
    dest.unlink(missing_ok=True)
    raise RuntimeError(f"could not fetch geojson for {dataset}: {last}")


def arcgis_geojson(layer_url: str, raw_dir: Path, refresh: bool = False, page: int = 2000) -> Path:
    """Page through an ArcGIS FeatureServer layer and save it as one GeoJSON."""
    dest = Path(raw_dir) / f"arcgis_{_key(layer_url)}.geojson"
    if dest.exists() and not refresh:
        return dest
    feats, offset = [], 0
    while True:
        params = {
            "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
            "resultOffset": offset, "resultRecordCount": page,
        }
        r = SESSION.get(f"{layer_url.rstrip('/')}/query", params=params, timeout=300)
        r.raise_for_status()
        batch = r.json().get("features", [])
        feats.extend(batch)
        log.info("  arcgis: %d features", len(feats))
        if len(batch) < page:
            break
        offset += page
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return dest


def get_json(url: str, raw_dir: Path, name: str, refresh: bool = False, params: dict | None = None):
    dest = Path(raw_dir) / f"{name}.json"
    if dest.exists() and not refresh:
        return json.loads(dest.read_text())
    r = SESSION.get(url, params=params, timeout=300)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(r.text)
    return r.json()
