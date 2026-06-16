"""Petrochemical MACC port reproduces the source model exactly.

Guards the faithful port: pathwise's ``macc`` backend, fed the vendored cost
curve + target (the source's Module 1+2 output), must reproduce the source's
per-year greedy deployment (``tests/data/refs/petrochemical_deployment.csv``)
and the published 2050 endpoint. See ``scripts/build_petrochemical.py``.
"""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

from pathwise.backends.macc_backend import MaccBackend

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "tests" / "data" / "refs" / "petrochemical_deployment.csv"

# Published headline numbers from the source's committed summary (default run).
ENDPOINT_EMISSIONS_MT = 29.84799634775603
ENDPOINT_CAPEX_MUSD = 36154.80638609345


def _build_workbook() -> dict:
    spec = importlib.util.spec_from_file_location(
        "build_petrochemical", ROOT / "scripts" / "build_petrochemical.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_workbook()


def _ref() -> list[dict[str, str]]:
    with REF.open(newline="") as fh:
        return list(csv.DictReader(fh))


def test_macc_port_reproduces_source_per_year() -> None:
    res = MaccBackend().run(_build_workbook(), {}, None)
    assert res["status"] == "optimal"
    by_year = {r["year"]: r for r in res["outputs"]["macc"]["by_year"]}

    ref = _ref()
    assert len(ref) == 26  # 2025–2050 inclusive
    for r in ref:
        y = int(r["year"])
        got = by_year[y]
        assert got["actual_emissions"] == pytest.approx(float(r["actual_emissions_mt"]), abs=1e-6)
        assert got["cumulative_capex"] == pytest.approx(float(r["cumulative_capex_musd"]), abs=1e-3)


def test_macc_port_hits_published_2050_endpoint() -> None:
    res = MaccBackend().run(_build_workbook(), {}, None)
    end = next(r for r in res["outputs"]["macc"]["by_year"] if r["year"] == 2050)
    assert end["actual_emissions"] == pytest.approx(ENDPOINT_EMISSIONS_MT, abs=1e-6)
    assert end["cumulative_capex"] == pytest.approx(ENDPOINT_CAPEX_MUSD, abs=1e-3)
    assert res["objective"] == pytest.approx(ENDPOINT_CAPEX_MUSD, abs=1e-3)
