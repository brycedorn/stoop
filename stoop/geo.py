"""Neighborhoods, Census population, the analysis grid, and spatial helpers.

The grid is a set of hex cells (default 150 m center to corner, ~260 m across) covering NYC land, on the
same lattice as the runner hexes (pointy-top, axial q/r on the planar lon*KX, lat*KY projection), so the
browser can rebuild any cell from (q, r). Each cell knows its NTA and an estimated population. Most factors are
computed per cell ("what can I reach from here?") and then averaged up to the NTA, weighted by population, so a
neighborhood's score reflects where people live. While a step runs, every per-cell value it averages with a name
is also kept (`collect_cells`), for the hex view inside a neighborhood.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .context import CRS_LL, CRS_M, Context
from . import fetch

log = logging.getLogger("stoop.geo")

NYC_COUNTIES = {"005": "Bronx", "047": "Brooklyn", "061": "Manhattan", "081": "Queens", "085": "Staten Island"}
RESIDENTIAL_NTATYPE = "0"   # 2020 NTA type codes: 0 = residential; 5-9 = parks, airports, etc.


def _gpd():
    import geopandas as gpd  # imported lazily so scoring/tests run without it
    return gpd


# --- Neighborhoods ----------------------------------------------------------

def load_ntas(ctx: Context):
    gpd = _gpd()
    cache = ctx.interim / "ntas.parquet"
    if cache.exists() and not ctx.wants_refresh("neighborhoods"):
        return gpd.read_parquet(cache)
    path = fetch.socrata_geojson(ctx.src["nyc_open_data"], ctx.src["ntas"], ctx.raw, ctx.wants_refresh("neighborhoods"))
    g = gpd.read_file(path)
    g.columns = [c.lower() for c in g.columns]
    g = g.rename(columns={"ntaname": "name", "boroname": "borough"})
    g["ntatype"] = g["ntatype"].astype(str).str.replace(".0", "", regex=False)
    g = g[["nta2020", "name", "borough", "ntatype", "geometry"]].to_crs(CRS_M)
    g["land_km2"] = g.geometry.area / 1e6
    g = g.set_index("nta2020")
    g.to_parquet(cache)
    log.info("loaded %d NTAs (%d residential)", len(g), (g.ntatype == RESIDENTIAL_NTATYPE).sum())
    return g


# --- Census tracts + ACS ----------------------------------------------------

ACS_VARS = {
    "B01003_001E": "pop",
    "B25003_003E": "renter_units",
    "B25064_001E": "rent_all",
    "B25031_002E": "rent_0br",
    "B25031_003E": "rent_1br",
    "B25031_004E": "rent_2br",
    "B25031_005E": "rent_3br",
}


def load_acs(ctx: Context) -> pd.DataFrame:
    cache = ctx.interim / "acs_tracts.parquet"
    if cache.exists() and not ctx.wants_refresh("neighborhoods"):
        return pd.read_parquet(cache)
    c = ctx.cfg["census"]
    if not c.get("api_key"):
        log.warning("no Census API key set; requests may be rate-limited (set CENSUS_API_KEY)")
    year = c.get("acs_year", 2023)
    frames = []
    for county in NYC_COUNTIES:
        params = {"get": ",".join(ACS_VARS), "for": "tract:*", "in": f"state:36 county:{county}"}
        if c.get("api_key"):
            params["key"] = c["api_key"]
        data = fetch.get_json(f"https://api.census.gov/data/{year}/acs/acs5", ctx.raw,
                              f"acs{year}_{county}", ctx.wants_refresh("neighborhoods"), params)
        frames.append(pd.DataFrame(data[1:], columns=data[0]))
    df = pd.concat(frames, ignore_index=True)
    df["geoid"] = df["state"] + df["county"] + df["tract"]
    df = df.rename(columns=ACS_VARS)
    for col in ACS_VARS.values():
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df.loc[df[col] < 0, col] = np.nan   # Census uses large negatives for "not available"
    df = df[["geoid", *ACS_VARS.values()]]
    df.to_parquet(cache)
    return df


def load_tracts(ctx: Context):
    gpd = _gpd()
    path = fetch.socrata_geojson(ctx.src["nyc_open_data"], ctx.src["tracts"], ctx.raw, ctx.wants_refresh("neighborhoods"))
    t = gpd.read_file(path)
    t.columns = [c.lower() for c in t.columns]
    t = t[["geoid", "nta2020", "geometry"]].to_crs(CRS_M)
    t["geoid"] = t["geoid"].astype(str)
    return t.merge(load_acs(ctx), on="geoid", how="left")


# --- Grid -------------------------------------------------------------------

HEX_LAT0 = 40.7
HEX_KX = 111320 * float(np.cos(np.radians(HEX_LAT0)))   # same projection as sources.runner_hexes
HEX_KY = 110540.0


def hex_lattice(lon_min, lat_min, lon_max, lat_max, size: float):
    """(q, r, x, y) arrays of pointy-top hex centers covering a lon/lat box, x/y on the planar KX/KY projection."""
    w, h = size * np.sqrt(3), size * 1.5
    x0, x1, y0, y1 = lon_min * HEX_KX, lon_max * HEX_KX, lat_min * HEX_KY, lat_max * HEX_KY
    rs = np.arange(int(np.floor(y0 / h)) - 1, int(np.ceil(y1 / h)) + 2)
    qs, rr = [], []
    for r in rs:
        q0 = int(np.floor(x0 / w - r / 2)) - 1
        q1 = int(np.ceil(x1 / w - r / 2)) + 1
        q = np.arange(q0, q1 + 1)
        qs.append(q)
        rr.append(np.full(len(q), r))
    q, r = np.concatenate(qs), np.concatenate(rr)
    return q, r, w * (q + r / 2), h * r


def hex_polygon(x: float, y: float, size: float):
    """Hex outline in lon/lat around planar center (x, y)."""
    from shapely.geometry import Polygon
    a = np.radians(60 * np.arange(6) - 30)
    return Polygon(np.column_stack([(x + size * np.cos(a)) / HEX_KX, (y + size * np.sin(a)) / HEX_KY]))


def hex_round(fq: float, fr: float) -> tuple[int, int]:
    """Nearest hex (axial) to fractional axial coordinates."""
    fs = -fq - fr
    q, r, s_ = round(fq), round(fr), round(fs)
    dq, dr, ds = abs(q - fq), abs(r - fr), abs(s_ - fs)
    if dq > dr and dq > ds:
        q = -r - s_
    elif dr > ds:
        r = -q - s_
    return int(q), int(r)


def hex_at(x: float, y: float, size: float) -> tuple[int, int]:
    """Axial (q, r) of the hex containing planar point (x, y)."""
    return hex_round((np.sqrt(3) / 3 * x - y / 3) / size, (2 / 3 * y) / size)


def build_hex_grid(ntas, size: float):
    """Hex cells whose centers fall on land inside an NTA (columns q, r, x, y, nta2020; meters CRS).

    An NTA too small to hold a hex center still gets the hex at its representative point, so every NTA has data."""
    gpd = _gpd()
    ll = ntas.to_crs(CRS_LL)
    q, r, hx, hy = hex_lattice(*ll.total_bounds, size)
    pts = gpd.GeoDataFrame({"q": q, "r": r, "hx": hx, "hy": hy},
                           geometry=gpd.points_from_xy(hx / HEX_KX, hy / HEX_KY), crs=CRS_LL)
    nt = ll.reset_index()[["nta2020", "geometry"]]
    joined = gpd.sjoin(pts, nt, predicate="within", how="inner").drop(columns="index_right")
    joined = pd.DataFrame(joined.drop_duplicates(subset=["q", "r"]).drop(columns="geometry"))
    missing = sorted(set(nt["nta2020"]) - set(joined["nta2020"]))
    if missing:
        w, h = size * np.sqrt(3), size * 1.5
        extra = []
        for nta, pt in ll.loc[missing].geometry.representative_point().items():
            rq, rr = hex_at(pt.x * HEX_KX, pt.y * HEX_KY, size)
            extra.append({"q": rq, "r": rr, "hx": w * (rq + rr / 2), "hy": h * rr, "nta2020": nta})
        joined = pd.concat([joined, pd.DataFrame(extra)], ignore_index=True)
        log.info("grid: %d small NTAs got the hex at their representative point", len(extra))
    joined = joined.reset_index(drop=True)
    centers = gpd.GeoSeries(gpd.points_from_xy(joined.hx / HEX_KX, joined.hy / HEX_KY), crs=CRS_LL).to_crs(CRS_M)
    polys = gpd.GeoSeries([hex_polygon(x, y, size) for x, y in zip(joined.hx, joined.hy)], crs=CRS_LL).to_crs(CRS_M)
    out = gpd.GeoDataFrame({"q": joined.q.astype(int).values, "r": joined.r.astype(int).values,
                            "x": centers.x.values, "y": centers.y.values, "nta2020": joined.nta2020.values},
                           geometry=polys.values, crs=CRS_M)
    out.index = pd.RangeIndex(len(out), name="cell_id")
    return out


def build_grid(ntas, cell_m: int):
    """Square cells whose centers fall on land inside an NTA (the older grid; `grid: square` in config)."""
    gpd = _gpd()
    from shapely.geometry import box
    minx, miny, maxx, maxy = ntas.total_bounds
    xs = np.arange(minx, maxx, cell_m) + cell_m / 2
    ys = np.arange(miny, maxy, cell_m) + cell_m / 2
    X, Y = np.meshgrid(xs, ys)
    pts = gpd.GeoDataFrame({"x": X.ravel(), "y": Y.ravel()},
                           geometry=gpd.points_from_xy(X.ravel(), Y.ravel()), crs=CRS_M)
    joined = gpd.sjoin(pts, ntas.reset_index()[["nta2020", "geometry"]], predicate="within", how="inner")
    joined = joined.drop(columns="index_right").drop_duplicates(subset=["x", "y"]).reset_index(drop=True)
    h = cell_m / 2
    joined["geometry"] = [box(x - h, y - h, x + h, y + h) for x, y in zip(joined.x, joined.y)]
    joined["cell_id"] = np.arange(len(joined))
    return gpd.GeoDataFrame(joined, geometry="geometry", crs=CRS_M).set_index("cell_id")


def allocate_population(grid, tracts) -> pd.Series:
    """Spread each tract's population over the grid cells it overlaps, by area."""
    gpd = _gpd()
    inter = gpd.overlay(grid.reset_index()[["cell_id", "geometry"]], tracts[["geoid", "pop", "geometry"]],
                        how="intersection", keep_geom_type=True)
    inter["a"] = inter.geometry.area
    inter["share"] = inter["a"] / inter.groupby("geoid")["a"].transform("sum")
    inter["cell_pop"] = inter["share"] * inter["pop"].fillna(0)
    return inter.groupby("cell_id")["cell_pop"].sum().reindex(grid.index, fill_value=0.0)


def load_grid(ctx: Context):
    gpd = _gpd()
    cache = ctx.interim / "grid.parquet"
    if cache.exists() and not ctx.wants_refresh("neighborhoods"):
        g = gpd.read_parquet(cache)
        if (ctx.cfg.get("grid", "hex") != "square") == ("q" in g.columns):
            return g
        log.info("grid: the cached grid is the other shape; rebuilding")
    if ctx.cfg.get("grid", "hex") == "square":
        grid = build_grid(ctx.ntas, ctx.cfg.get("grid_cell_m", 200))
    else:
        grid = build_hex_grid(ctx.ntas, ctx.cfg.get("grid_hex_m", 150))
    grid["pop"] = allocate_population(grid, load_tracts(ctx))
    grid.to_parquet(cache)
    log.info("grid: %d cells, %.0f people", len(grid), grid["pop"].sum())
    return grid


# --- Spatial helpers (grid-based, pure numpy) -------------------------------

def to_xy(lon, lat) -> np.ndarray:
    """WGS84 lon/lat arrays -> projected meters (N x 2)."""
    from pyproj import Transformer
    t = Transformer.from_crs(CRS_LL, CRS_M, always_xy=True)
    x, y = t.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.column_stack([x, y])


def df_xy(df: pd.DataFrame, lon="longitude", lat="latitude") -> np.ndarray:
    d = df[[lon, lat]].apply(pd.to_numeric, errors="coerce").dropna()
    d = d[(d[lat].between(40.4, 41.0)) & (d[lon].between(-74.3, -73.6))]
    return to_xy(d[lon].values, d[lat].values)


def cell_xy(grid) -> np.ndarray:
    return grid[["x", "y"]].to_numpy()


def sum_within(cells: np.ndarray, pts: np.ndarray, radius: float, weights=None) -> np.ndarray:
    """For each cell, sum of point weights (default 1) within `radius` meters."""
    if len(pts) == 0:
        return np.zeros(len(cells))
    w = np.ones(len(pts)) if weights is None else np.asarray(weights, float)
    tree = cKDTree(pts)
    hits = tree.query_ball_point(cells, r=radius)
    return np.array([w[h].sum() if h else 0.0 for h in hits])


def decay_sum(cells: np.ndarray, pts: np.ndarray, scale: float, weights=None, cutoff: float = 3.0) -> np.ndarray:
    """Gaussian-decayed sum: nearby points count ~1, points at `scale` meters count ~0.37."""
    if len(pts) == 0:
        return np.zeros(len(cells))
    w = np.ones(len(pts)) if weights is None else np.asarray(weights, float)
    tree = cKDTree(pts)
    out = np.zeros(len(cells))
    for i, h in enumerate(tree.query_ball_point(cells, r=scale * cutoff)):
        if h:
            d = np.hypot(*(pts[h] - cells[i]).T)
            out[i] = (w[h] * np.exp(-(d / scale) ** 2)).sum()
    return out


def nearest_dist(cells: np.ndarray, pts: np.ndarray) -> np.ndarray:
    if len(pts) == 0:
        return np.full(len(cells), np.nan)
    d, _ = cKDTree(pts).query(cells)
    return d


def lines_to_points(geoms, step: float = 25.0):
    """Densify (multi)lines into points every `step` m; each point stands for `step` meters."""
    out = []
    for g in geoms:
        if g is None or g.is_empty:
            continue
        parts = getattr(g, "geoms", [g])
        for p in parts:
            n = max(int(p.length // step), 1)
            for k in range(n):
                pt = p.interpolate((k + 0.5) * p.length / n)
                out.append((pt.x, pt.y))
    return np.array(out) if out else np.empty((0, 2))


def grid_neighbor_sum(grid, values: pd.Series, radius: float) -> np.ndarray:
    """Sum a per-cell quantity over all cells within `radius` (e.g. park area within 1 km)."""
    xy = cell_xy(grid)
    return sum_within(xy, xy, radius, weights=values.reindex(grid.index).fillna(0).values)


def area_fraction(grid, polygons) -> pd.Series:
    """Fraction of each grid cell covered by `polygons` (any CRS)."""
    gpd = _gpd()
    polys = polygons.to_crs(CRS_M)
    polys = gpd.GeoDataFrame(geometry=[polys.geometry.make_valid().union_all()], crs=CRS_M).explode(index_parts=False)
    inter = gpd.overlay(grid.reset_index()[["cell_id", "geometry"]], polys, how="intersection", keep_geom_type=True)
    covered = inter.assign(a=inter.geometry.area).groupby("cell_id")["a"].sum()
    frac = covered / grid.geometry.area.reindex(covered.index)   # per cell: projected hexes differ by a hair
    return frac.clip(0, 1).reindex(grid.index, fill_value=0.0)


_CELLS: dict | None = None   # per-cell values kept while a step runs (collect_cells)


def collect_cells() -> None:
    """Start keeping the per-cell values that `to_nta` averages under a name."""
    global _CELLS
    _CELLS = {}


def take_cells() -> pd.DataFrame | None:
    """The per-cell values kept since `collect_cells` (index cell_id), and stop keeping them."""
    global _CELLS
    got, _CELLS = _CELLS, None
    return pd.DataFrame(got) if got else None


def to_nta(grid, values, name: str | None = None) -> pd.Series:
    """Population-weighted mean of a per-cell value for each NTA.

    NTAs with no residents fall back to a plain mean. With `name`, the per-cell values are also kept for the hex
    view while collect_cells is on.
    """
    v = pd.Series(np.asarray(values, float), index=grid.index)
    if name and _CELLS is not None:
        _CELLS[name] = v.astype("float32")
    df = pd.DataFrame({"nta": grid["nta2020"].values, "v": v.values, "w": grid["pop"].values})
    df = df.dropna(subset=["v"])
    df["vw"] = df["v"] * df["w"]
    g = df.groupby("nta")
    weighted = g["vw"].sum() / g["w"].sum().replace(0, np.nan)
    out = weighted.fillna(g["v"].mean())
    out.index.name = "nta2020"
    return out.rename(name) if name else out


def count_in_nta(ntas, pts_xy: np.ndarray, weights=None) -> pd.Series:
    """Count (or sum weights of) projected points falling inside each NTA."""
    gpd = _gpd()
    if len(pts_xy) == 0:
        return pd.Series(0.0, index=ntas.index)
    p = gpd.GeoDataFrame({"w": np.ones(len(pts_xy)) if weights is None else np.asarray(weights, float)},
                         geometry=gpd.points_from_xy(pts_xy[:, 0], pts_xy[:, 1]), crs=CRS_M)
    j = gpd.sjoin(p, ntas.reset_index()[["nta2020", "geometry"]], predicate="within", how="inner")
    return j.groupby("nta2020")["w"].sum().reindex(ntas.index, fill_value=0.0)
