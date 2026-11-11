"""Command line: python -m stoop {run,score,status,demo}."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime

import pandas as pd

from .context import ROOT, Context, load_config

log = logging.getLogger("stoop")


def _split(s: str | None) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


def run_steps(ctx: Context, steps: list[str]) -> dict[str, str]:
    from .sources import STEPS
    results = {}
    for name in steps:
        if name != "neighborhoods" and not (ctx.interim / "features_neighborhoods.parquet").exists():
            raise SystemExit("run the 'neighborhoods' step first")
        t0 = time.time()
        log.info("== %s ==", name)
        from . import geo
        try:
            geo.collect_cells()        # per-cell values behind the averages, for the hex view
            df = STEPS[name](ctx)
            df.index.name = "nta2020"
            df.to_parquet(ctx.interim / f"features_{name}.parquet")
            cells = geo.take_cells()
            cell_file = ctx.interim / f"cells_{name}.parquet"
            if cells is not None:
                cells.to_parquet(cell_file)
            elif cell_file.exists():
                cell_file.unlink()     # the step no longer works per cell: don't keep stale values
            results[name] = f"ok ({time.time() - t0:.0f}s, {df.shape[1]} metrics)"
        except Exception as e:   # keep going: one broken source shouldn't block the rest
            geo.take_cells()
            log.exception("step %s failed", name)
            results[name] = f"FAILED: {e}"
            if name == "neighborhoods":
                break
    return results


def merge_features(ctx: Context) -> pd.DataFrame:
    from .sources import STEPS
    table = pd.DataFrame(ctx.ntas.drop(columns="geometry"))
    for name in STEPS:
        p = ctx.interim / f"features_{name}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            table = table.join(df[[c for c in df.columns if c not in table.columns]], how="left")
    return table


def score_and_export(ctx: Context):
    from . import export, scoring
    from .sources.commute import apply_commute_choice
    table = apply_commute_choice(merge_features(ctx), ctx.cfg)   # commute = the one place in you.commute_to
    residential = table["ntatype"].astype(str) == "0"
    scores = scoring.score_table(table, ctx.cfg, residential)
    routes = [c for c in table.columns if c.startswith("air_route_")]   # route cards go to airports.js, not the CSV
    (table.join(scores.add_prefix("score_")).drop(columns=routes, errors="ignore")
     .to_csv(ctx.interim / "neighborhood_scores.csv"))
    st_path = ctx.interim / "subway_stations.json"
    stations = json.loads(st_path.read_text()) if st_path.exists() else None
    payload = export.build_payload(table, scores, export.geometries_from_gdf(ctx.ntas), ctx.cfg,
                                   labels=export.label_points(ctx.ntas), stations=stations)
    path = export.write_payload(payload, ctx.root / "web")
    export.write_airport_routes(table, ctx.root / "web")
    from . import hexes, layers
    layers.write_layers(ctx, ctx.root / "web")
    hexes.write(hexes.build_payload(ctx, table, scores, residential), ctx.root / "web")
    qa = export.qa_report(table, scores, ctx.interim / "qa_report.md", residential)
    log.info("wrote %s and %s", path.relative_to(ctx.root), qa.relative_to(ctx.root))


def main(argv=None):
    from .sources import STEPS
    p = argparse.ArgumentParser(prog="stoop", description="NYC neighborhood finder")
    p.add_argument("-c", "--config", default=str(ROOT / "config.yaml"))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch + compute factors, then score and export")
    r.add_argument("--steps", help=f"comma list (default all): {','.join(STEPS)}")
    r.add_argument("--skip", help="comma list of steps to skip")
    r.add_argument("--refresh", help="comma list of steps to re-download, or 'all'")
    sub.add_parser("score", help="re-score and export from cached features (fast)")
    sub.add_parser("status", help="show which steps have cached results")
    sub.add_parser("demo", help="write synthetic data to web/data to preview the map")
    pb = sub.add_parser("publish", help="build the public site (scores only, nothing personal) from cached results")
    pb.add_argument("--out", default=str(ROOT / "site"), help="folder for the site (default: site/)")
    pb.add_argument("--commit", action="store_true", help="also commit it to the gh-pages branch (then git push)")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ["urllib3", "fiona", "pyogrio", "osmnx"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_config(a.config)

    if a.cmd == "demo":
        from .demo import make_demo
        from .export import build_payload, write_payload
        table, scores, geoms = make_demo(cfg)
        path = write_payload(build_payload(table, scores, geoms, cfg), ROOT / "web")
        print(f"demo data written to {path}. Open web/index.html in a browser.")
        return 0

    if a.cmd == "publish":
        from .publish import build_site, commit_pages
        site = build_site(a.out)
        if a.commit:
            commit_pages(site, ROOT, message=f"Publish site ({datetime.now():%Y-%m-%d})")
        return 0

    ctx = Context(cfg=cfg, refresh=set(_split(getattr(a, "refresh", None))))

    if a.cmd == "status":
        for name in STEPS:
            f = ctx.interim / f"features_{name}.parquet"
            when = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if f.exists() else "-"
            print(f"  {name:<14} {when}")
        return 0

    if a.cmd == "run":
        steps = _split(a.steps) or list(STEPS)
        unknown = set(steps) - set(STEPS)
        if unknown:
            p.error(f"unknown steps: {', '.join(sorted(unknown))}")
        if "neighborhoods" not in steps and not (ctx.interim / "features_neighborhoods.parquet").exists():
            steps.insert(0, "neighborhoods")
        steps = [s for s in steps if s not in set(_split(a.skip))]
        results = run_steps(ctx, steps)
        print("\nsummary:")
        for k, v in results.items():
            print(f"  {k:<14} {v}")
        if not (ctx.interim / "features_neighborhoods.parquet").exists():
            return 1

    score_and_export(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
