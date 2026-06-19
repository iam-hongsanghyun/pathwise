"""Shared ``pint`` unit registry and the pathwise unit system.

A single process-wide registry so quantities compare and convert correctly
across modules. Use it at I/O boundaries (parsing data, presenting results) to
attach/convert units; keep the optimisation matrix itself in consistent base
units for good numerical scaling.

The unit system (canonical base per dimension, the picker's allowed units, and
the custom unit definitions fed to pint) is data, not code: it lives in
``assets/units.yaml`` and is copied to a writable ``<data_dir>/units.yaml`` on
first edit via the API. **Reads fall back to the bundled seed** when no writable
copy exists, so importing this module never writes to disk — only an explicit
edit (:func:`ensure_writable_config` / the units router) materialises the copy.

A unit here is the physical *measure* (``t``, ``GJ``, ``MWh``); the *commodity*
supplies the substance, so the real unit is the pair — ``t``+hydrogen is
``t-H2``, distinct and non-interchangeable from ``t``+steel (``t-steel``) even
though both are mass. Conversion is therefore only ever **within one commodity**
(change the measure: ``t-H2 <-> kg-H2``, or ``t-H2 <-> GJ`` via H2's own LHV);
``t-steel -> t-H2`` is never valid.

Two kinds of conversion exist in pathwise:

* **dimension-universal** (``MWh<->GJ``, ``kg<->t``, ``KRW<->USD``) — one factor
  for everyone, resolved here against the canonical base per dimension. These
  helpers handle this kind; callers apply them within a single commodity.
* **commodity-specific** (``1 t`` of gas and of coal hold different ``GJ``;
  ``1 t`` of steel is worth some currency) — those factors belong on the
  commodity and are layered on in a later phase, not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pint import UnitRegistry

from pathwise.config import get_settings
from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Process-wide caches, reset by :func:`reload` when the config is edited.
_config_cache: dict[str, Any] | None = None
_registry_cache: UnitRegistry | None = None


def _writable_path() -> Path:
    """Where the user's editable units config lives (may not exist yet)."""
    return Path(get_settings().data_dir) / "units.yaml"


def _config_path() -> Path:
    """The config to read: the writable copy if present, else the bundled seed."""
    writable = _writable_path()
    return writable if writable.exists() else Path(get_settings().units_seed)


def ensure_writable_config() -> Path:
    """Materialise the writable ``<data_dir>/units.yaml`` from the seed if absent.

    Called only when the user views/edits the config (the units router), so plain
    reads stay side-effect-free.

    Returns:
        The writable config path (now guaranteed to exist).
    """
    writable = _writable_path()
    if not writable.exists():
        writable.parent.mkdir(parents=True, exist_ok=True)
        writable.write_text(
            Path(get_settings().units_seed).read_text(encoding="utf-8"), encoding="utf-8"
        )
        logger.info("seeded units config -> %s", writable)
    return writable


def load_units_config() -> dict[str, Any]:
    """Return the parsed unit system (cached). Reads writable copy, else the seed."""
    global _config_cache
    if _config_cache is None:
        with _config_path().open(encoding="utf-8") as fh:
            _config_cache = yaml.safe_load(fh) or {}
    return _config_cache


def get_registry() -> UnitRegistry:
    """Return the process-wide pint :class:`UnitRegistry` (cached).

    Built from the unit system's ``custom_units``; an unparseable / duplicate
    definition is logged and skipped rather than crashing the registry.
    """
    global _registry_cache
    if _registry_cache is None:
        ureg: UnitRegistry = UnitRegistry()
        for definition in load_units_config().get("custom_units", []):
            try:
                ureg.define(str(definition))
            except Exception as exc:  # one bad entry must not break every unit
                logger.warning("skipping invalid custom unit %r: %s", definition, exc)
        _registry_cache = ureg
    return _registry_cache


def reload() -> None:
    """Drop cached config + registry so an edited ``units.yaml`` takes effect."""
    global _config_cache, _registry_cache
    _config_cache = None
    _registry_cache = None


def validate_custom_units(definitions: list[Any]) -> str | None:
    """First unparseable custom-unit definition's error, or ``None`` if all parse.

    Checked in a throwaway registry so a caller (the units router) can reject a
    bad edit before it touches the live registry or the file. Keeps pint confined
    to this module.
    """
    probe: UnitRegistry = UnitRegistry()
    for definition in definitions:
        try:
            probe.define(str(definition))
        except Exception as exc:
            return f"invalid custom unit '{definition}': {exc}"
    return None


# ── Helpers (I/O-boundary use only) ───────────────────────────────────────────


def is_parseable(unit: str) -> bool:
    """Whether ``unit`` is a unit pint can parse with the current registry."""
    try:
        get_registry().Unit(unit)
        return True
    except Exception:
        return False


def base_unit(dimension: str) -> str | None:
    """Canonical base unit for a configured ``dimension`` (``None`` if unknown)."""
    spec = load_units_config().get("dimensions", {}).get(dimension)
    return str(spec["base"]) if spec and "base" in spec else None


def dimension_of(unit: str) -> str | None:
    """The configured dimension name whose base shares ``unit``'s dimensionality.

    Returns ``None`` for an unparseable unit or one not matching any configured
    dimension (e.g. a bare ``"unit"`` placeholder or an unmodelled dimension).
    """
    ureg = get_registry()
    try:
        dim = ureg.Unit(unit).dimensionality
    except Exception:
        return None
    for name, spec in load_units_config().get("dimensions", {}).items():
        base = spec.get("base")
        if base and ureg.Unit(str(base)).dimensionality == dim:
            return str(name)
    return None


def units_compatible(a: str, b: str) -> bool:
    """Whether two units share a dimensionality (so a universal factor exists)."""
    if not (is_parseable(a) and is_parseable(b)):
        return False
    ureg = get_registry()
    return bool(ureg.Unit(a).dimensionality == ureg.Unit(b).dimensionality)


def is_compatible(unit: str, dimension: str) -> bool:
    """Whether ``unit``'s dimensionality matches ``dimension``'s canonical base."""
    base = base_unit(dimension)
    return base is not None and units_compatible(unit, base)


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` from ``from_unit`` to ``to_unit`` (same dimension).

    Raises:
        ValueError: If either unit is unparseable or they are not convertible
            (different dimensionality).
    """
    ureg = get_registry()
    try:
        return float((value * ureg(from_unit)).to(to_unit).magnitude)
    except Exception as exc:
        raise ValueError(f"cannot convert {from_unit!r} -> {to_unit!r}: {exc}") from exc


def unit_factors() -> dict[str, dict[str, Any]]:
    """Per allowed unit: its dimension + factor to that dimension's base.

    Consumed by ``GET /api/units`` so the frontend can convert and check
    compatibility locally without reimplementing pint.
    """
    out: dict[str, dict[str, Any]] = {}
    for dim, spec in load_units_config().get("dimensions", {}).items():
        base = spec.get("base")
        if not base:
            continue
        for unit in spec.get("allowed", []):
            try:
                out[str(unit)] = {
                    "dimension": str(dim),
                    "factor_to_base": convert(1.0, str(unit), str(base)),
                }
            except ValueError:
                logger.warning("allowed unit %r not convertible to base %r", unit, base)
    return out
