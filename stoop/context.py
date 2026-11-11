"""Shared state for a pipeline run: config, paths, and the analysis grid."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

log = logging.getLogger("stoop")

ROOT = Path(__file__).resolve().parent.parent
CRS_M = "EPSG:32618"   # UTM 18N, meters. Good for distance math across NYC.
CRS_LL = "EPSG:4326"


def merge_config(base: dict, over: dict) -> dict:
    """`over` on top of `base`: dicts merge key by key, anything else (lists included) is replaced."""
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge_config(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path | None = None, local: bool = True) -> dict:
    """config.yaml (public defaults), plus config.local.yaml next to it (your personal settings, gitignored)
    unless local=False (what `stoop publish` uses, so nothing personal reaches the public site)."""
    path = Path(path or ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    local_path = path.with_name(path.stem + ".local" + path.suffix)
    if local and local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            cfg = merge_config(cfg, yaml.safe_load(f) or {})
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        cfg.setdefault("census", {})["api_key"] = key
    return cfg


@dataclass
class Context:
    cfg: dict
    root: Path = ROOT
    refresh: set[str] = field(default_factory=set)   # step names to re-download

    @property
    def raw(self) -> Path:
        p = self.root / "data" / "raw"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def interim(self) -> Path:
        p = self.root / "data" / "interim"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def inputs(self) -> Path:
        return self.root / "inputs"

    def wants_refresh(self, step: str) -> bool:
        return "all" in self.refresh or step in self.refresh

    @property
    def src(self) -> dict:
        return self.cfg["sources"]

    # Geometry built once per run (and cached to disk by stoop.geo)
    @cached_property
    def ntas(self):
        from . import geo
        return geo.load_ntas(self)

    @cached_property
    def grid(self):
        from . import geo
        return geo.load_grid(self)
