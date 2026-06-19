"""Units router — the user-editable unit system the builder reads and edits.

The unit system (canonical base per dimension, the picker's allowed units, and
the custom unit definitions fed to pint) is reference *data*, not code. It ships
as a bundled seed (``assets/units.yaml``) and is copied to a writable
``<data_dir>/units.yaml`` on first edit here; reads fall back to the seed until
then (see :mod:`pathwise.units`).

* ``GET  /api/units`` — the parsed config plus a per-allowed-unit factor table so
  the frontend can convert / check compatibility locally.
* ``PUT  /api/units`` — overwrite the config; every ``custom_units`` entry must
  parse with pint before the file is written, then the cached registry is reset.
"""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from pathwise import units
from pathwise.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api")


def _bundle() -> dict[str, Any]:
    """The config plus the derived per-unit factor table (for the picker)."""
    return {"config": units.load_units_config(), "factors": units.unit_factors()}


@router.get("/units")
def get_units() -> dict[str, Any]:
    """The current unit system (writable copy if present, else the bundled seed)."""
    return _bundle()


@router.put("/units")
def put_units(config: dict[str, Any]) -> dict[str, Any]:
    """Overwrite the unit system after validating every custom unit parses.

    The whole config is validated first, so a single bad ``custom_units`` line is
    rejected with a 422 rather than half-written.
    """
    if (error := units.validate_custom_units(config.get("custom_units", []))) is not None:
        raise HTTPException(status_code=422, detail=error)

    path = units.ensure_writable_config()
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    units.reload()  # drop cached config + registry so the edit takes effect now
    logger.info("saved units config -> %s", path)
    return _bundle()
