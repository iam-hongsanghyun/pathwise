"""P3 backend: end-to-end run + validation folding."""

from __future__ import annotations

import copy

from pathwise.backends import available_backends, get_backend
from tests.data.example import example_workbook


def _scenario() -> dict:
    return {"domain": "process", "economics": {"base_year": 2025}}


def test_backend_registered() -> None:
    names = {b["name"] for b in available_backends()}
    assert "linopy" in names
    assert get_backend("linopy").capabilities()["features"]["network"] is True


def test_run_end_to_end() -> None:
    res = get_backend("linopy").run(example_workbook(), _scenario(), {})
    assert res["status"] == "optimal"
    assert res["objective"] is not None
    base = {(c["process"], c["period"]): c["technology"] for c in res["outputs"]["technology"]}
    assert base[("F1", 2025)] == "BF"
    # The iron stream is routed F1 → F2.
    assert any(f["flow"] == "iron" for f in res["outputs"]["flows"])


def test_run_invalid_workbook_folds_validation() -> None:
    wb = copy.deepcopy(example_workbook())
    del wb["demand"]
    res = get_backend("linopy").run(wb, _scenario(), {})
    assert res["status"] == "invalid"
    assert any("demand" in e for e in res["validation"]["errors"])
