"""OpenStreetMap features via osmnx/Overpass, cached as GeoParquet."""
from __future__ import annotations

import hashlib
import json
import logging

from .context import CRS_LL, CRS_M

log = logging.getLogger("stoop.osm")


def features(ctx, tags: dict, name: str, refresh: bool = False):
    """All OSM features matching `tags` inside NYC, in meters CRS."""
    import geopandas as gpd
    key = hashlib.sha1(json.dumps(tags, sort_keys=True).encode()).hexdigest()[:8]
    cache = ctx.raw / f"osm_{name}_{key}.parquet"
    if cache.exists() and not refresh:
        return gpd.read_parquet(cache)
    import osmnx as ox
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(ctx.raw / "osmnx_cache")
    ox.settings.requests_timeout = 600
    boundary = ctx.ntas.to_crs(CRS_LL).union_all().buffer(0.002)   # ~200 m buffer catches waterfront paths
    log.info("querying OSM for %s (this can take a while the first time)...", name)
    g = ox.features_from_polygon(boundary, tags=tags)
    keep = [c for c in ["highway", "footway", "leisure", "amenity", "shop", "name", "access", "geometry"] if c in g.columns]
    g = g[keep].reset_index(drop=True)
    for c in keep:
        if c != "geometry":
            g[c] = g[c].astype("string")
    g = g.to_crs(CRS_M)
    g.to_parquet(cache)
    return g


NYC_MARGIN_M = 25    # absorbs coordinate rounding at the shoreline; Nassau stores at Green Acres sit 52-82 m past the line
_NYC = {}


def nyc_area(ctx, crs=None):
    """The five boroughs (union of NTAs) plus a small margin, as one shapely geometry (meters CRS, or `crs`)."""
    import geopandas as gpd
    key = (id(ctx.ntas), str(crs))
    if key not in _NYC:
        shape = ctx.ntas.union_all().buffer(NYC_MARGIN_M)
        if crs is not None:
            shape = gpd.GeoSeries([shape], crs=ctx.ntas.crs).to_crs(crs).iloc[0]
        _NYC[key] = shape
    return _NYC[key]


def in_nyc(ctx, gdf):
    """Boolean mask: features whose representative point is inside NYC (not New Jersey, Nassau or Westchester)."""
    import numpy as np
    import shapely
    if len(gdf) == 0:
        return np.zeros(0, bool)
    pts = gdf.to_crs(ctx.ntas.crs).geometry.representative_point()
    return shapely.contains_xy(nyc_area(ctx), pts.x.values, pts.y.values)


def in_nyc_ll(ctx, lon, lat):
    """Same for lon/lat arrays."""
    import numpy as np
    import shapely
    return shapely.contains_xy(nyc_area(ctx, crs=4326), np.asarray(lon, float), np.asarray(lat, float))


def point_xy(gdf):
    """Representative point for each feature (centroid for shops in building polygons)."""
    import numpy as np
    if len(gdf) == 0:
        return np.empty((0, 2))
    pts = gdf.geometry.representative_point()
    return np.column_stack([pts.x.values, pts.y.values])
