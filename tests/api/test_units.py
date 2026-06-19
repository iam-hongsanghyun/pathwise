"""Units API: read the unit system, edit it, and reject unparseable custom units.

The config seeds from the bundled default and is copied to a writable
``<data_dir>/units.yaml`` on first PUT; a bad custom unit is rejected with 422
before anything is written.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pathwise import units
from pathwise.api.main import app
from pathwise.config import get_settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PATHWISE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    units.reload()
    yield
    get_settings.cache_clear()
    units.reload()


def test_get_units_returns_config_and_factors() -> None:
    body = client.get("/api/units").json()
    assert body["config"]["dimensions"]["energy"]["base"] == "GJ"
    assert body["factors"]["MWh"]["factor_to_base"] == pytest.approx(3.6)


def test_put_adds_custom_unit_and_persists(tmp_path: Any) -> None:
    cfg = client.get("/api/units").json()["config"]
    cfg["dimensions"]["energy"]["allowed"].append("Nm3_gas")
    cfg["custom_units"].append("Nm3_gas = 0.04 * GJ")

    out = client.put("/api/units", json=cfg)
    assert out.status_code == 200
    factors = out.json()["factors"]
    assert factors["Nm3_gas"] == {"dimension": "energy", "factor_to_base": pytest.approx(0.04)}
    # The writable copy now exists and the edit survives a re-read.
    assert (Path(tmp_path) / "units.yaml").exists()
    assert "Nm3_gas" in client.get("/api/units").json()["factors"]


def test_put_rejects_unparseable_custom_unit() -> None:
    cfg = client.get("/api/units").json()["config"]
    cfg["custom_units"].append("totally invalid definition")
    resp = client.put("/api/units", json=cfg)
    assert resp.status_code == 422
    assert "invalid custom unit" in resp.json()["detail"]
