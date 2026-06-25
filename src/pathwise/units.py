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

A unit here is the physical *measure* (``t``, ``GJ``, ``MWh``); the *flow*
supplies the substance, so the real unit is the pair — ``t``+hydrogen is
``t-H2``, distinct and non-interchangeable from ``t``+steel (``t-steel``) even
though both are mass. Conversion is therefore only ever **within one flow**
(change the measure: ``t-H2 <-> kg-H2``, or ``t-H2 <-> GJ`` via H2's own LHV);
``t-steel -> t-H2`` is never valid.

Two kinds of conversion exist in pathwise:

* **dimension-universal** (``MWh<->GJ``, ``kg<->t``, ``KRW<->USD``) — one factor
  for everyone, resolved here against the canonical base per dimension. These
  helpers handle this kind; callers apply them within a single flow.
* **flow-specific** (``1 t`` of gas and of coal hold different ``GJ``;
  ``1 t`` of steel is worth some currency) — those factors belong on the
  flow and are layered on in a later phase, not here.
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


def _build_registry(custom_units: list[Any]) -> UnitRegistry:
    """A fresh registry with ``custom_units`` defined (bad entries logged + skipped)."""
    ureg: UnitRegistry = UnitRegistry()
    for definition in custom_units:
        try:
            ureg.define(str(definition))
        except Exception as exc:  # one bad entry must not break every unit
            logger.warning("skipping invalid custom unit %r: %s", definition, exc)
    return ureg


def get_registry() -> UnitRegistry:
    """Return the process-wide pint :class:`UnitRegistry` (cached).

    Built from the unit system's ``custom_units``; an unparseable / duplicate
    definition is logged and skipped rather than crashing the registry.
    """
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = _build_registry(load_units_config().get("custom_units", []))
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


# ── Project-override-aware registry building ──────────────────────────────────


def _definition_name(definition: Any) -> str | None:
    """The unit name a pint definition defines — the token left of ``=``."""
    head = str(definition).split("=", 1)[0].strip()
    return head or None


def _override_definitions(unit_overrides: dict[str, Any] | list[Any] | None) -> list[Any]:
    """Pull the ``custom_units`` definition list out of a project's ``unit_overrides``.

    Accepts the list directly or a ``{"custom_units": [...]}`` mapping (mirrors
    ``units.yaml``); anything else yields an empty list.
    """
    if not unit_overrides:
        return []
    if isinstance(unit_overrides, list):
        return list(unit_overrides)
    if isinstance(unit_overrides, dict):
        return list(unit_overrides.get("custom_units", []))
    return []


def merged_custom_units(unit_overrides: dict[str, Any] | list[Any] | None) -> list[Any]:
    """Global ``custom_units`` with a project's overrides applied (override wins).

    An override that redefines a global unit REPLACES it in place — so pint never
    sees a redefinition and the existing dependency order is preserved — while a
    brand-new unit is appended after the globals it may depend on.
    """
    base = list(load_units_config().get("custom_units", []))
    extra = _override_definitions(unit_overrides)
    if not extra:
        return base
    pos_by_name = {_definition_name(d): i for i, d in enumerate(base) if _definition_name(d)}
    merged = list(base)
    for d in extra:
        name = _definition_name(d)
        if name is not None and name in pos_by_name:
            merged[pos_by_name[name]] = d  # redefine in place — the override wins
        else:
            merged.append(d)
    return merged


# ── Coefficient conversion (recipe IO → the stream's canonical unit) ──────────

#: Property-key prefixes recognised as per-flow conversion factors. Convention
#: A (no library migration): a key ``<measure>_<NUM>_per_<DEN>`` with scalar value
#: ``V`` means ``V <NUM>/<DEN>`` — e.g. ``lhv_MJ_per_kg = 45`` is 45 MJ/kg, an
#: energy-per-mass factor that bridges this flow's [mass] <-> [energy]. This
#: reads keys libraries already use (``lhv_*``) and the generalised names.
_FACTOR_PREFIXES: tuple[str, ...] = ("energy_content", "lhv", "density", "value", "price")


def _scale_to(q: Any) -> Any:
    """A pint Context transformation that multiplies its value by the factor ``q``."""

    def _t(ureg: Any, value: Any, **kwargs: Any) -> Any:
        return value * q

    return _t


def _scale_by_inverse(q: Any) -> Any:
    """A pint Context transformation that divides its value by the factor ``q``."""

    def _t(ureg: Any, value: Any, **kwargs: Any) -> Any:
        return value / q

    return _t


def _parse_factor_key(key: str) -> tuple[str, str] | None:
    """Split a recognised factor key into ``(numerator_unit, denominator_unit)``.

    ``lhv_MJ_per_kg`` -> ``("MJ", "kg")``; returns ``None`` for any key that is not
    a recognised ``<measure>_<NUM>_per_<DEN>`` factor (e.g. ``temperature_C``).
    """
    for prefix in _FACTOR_PREFIXES:
        if key == prefix or key.startswith(prefix + "_"):
            rest = key[len(prefix) :].lstrip("_")
            if "_per_" in rest:
                num, den = rest.split("_per_", 1)
                if num and den:
                    return num, den
            return None
    return None


class CoefficientConverter:
    """Convert an authored IO coefficient to its target stream's canonical unit.

    Built once per assemble from the model's flow/impact units (plus each
    flow's conversion-factor properties) and the project's optional
    ``unit_overrides``. It owns its own pint registry and per-flow Contexts,
    so nothing leaks onto the process-wide registry and editing ``units.yaml`` can
    never collide with it.

    **Degrade-never-raise.** Anything that cannot be converted — missing factor,
    unparseable unit, incompatible dimensions — is recorded in :attr:`issues` and
    the coefficient is returned UNCHANGED, so a model always assembles (existing
    libraries keep loading). An absent/empty row unit is a no-op: the coefficient
    is already in the stream's unit. That is the invariance guarantee — a library
    with no declared IO units converts every coefficient by a factor of exactly 1.

    Two conversion lanes, selected automatically by ``(row_unit, canonical_unit)``:

    * **universal** (same dimension, e.g. ``MWh -> GJ``): the registry factor.
    * **flow-specific** (cross dimension, e.g. ``t -> GJ``): that flow's
      own ``energy_content``/``density``/``value`` factor, via a pint Context.
      Impacts are universal-only (emissions is its own dimension with no factors).
    """

    def __init__(
        self,
        *,
        flow_units: dict[str, str],
        flow_props: dict[str, dict[str, float]] | None = None,
        impact_units: dict[str, str] | None = None,
        unit_overrides: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        self._ureg = _build_registry(merged_custom_units(unit_overrides))
        self._flow_units = flow_units
        self._flow_props = flow_props or {}
        self._impact_units = impact_units or {}
        self._ctx_cache: dict[str, Any] = {}  # flow_id -> pint.Context | None
        self.issues: list[str] = []

    def to_canonical(
        self, coefficient: float, row_unit: str | None, target_id: str, role: str
    ) -> float:
        """``coefficient`` (authored in ``row_unit``) in ``target_id``'s canonical unit.

        Returns the coefficient unchanged — recording an issue — whenever the
        conversion can't be done; an absent ``row_unit`` is a no-op (factor 1).
        """
        row_unit = row_unit.strip() if row_unit else row_unit
        if not row_unit:  # absent/blank — already the stream's unit (invariance, no pint)
            return coefficient
        canonical = self._canonical_unit(target_id, role)
        if canonical is None:
            self._note(
                f"{target_id!r} ({role}) has no canonical unit; left {row_unit!r} as authored"
            )
            return coefficient
        if not self._parseable(row_unit) or not self._parseable(canonical):
            self._note(
                f"unparseable unit ({row_unit!r} -> {canonical!r}) on "
                f"{target_id!r}; left as authored"
            )
            return coefficient
        if self._same_dimension(row_unit, canonical):
            return self._convert(coefficient, row_unit, canonical, target_id)
        if role == "impact":
            self._note(
                f"cannot convert impact {target_id!r} across dimensions "
                f"({row_unit!r} -> {canonical!r}); left as authored"
            )
            return coefficient
        ctx = self._flow_context(target_id)
        if ctx is None:
            self._note(
                f"no conversion factor on {target_id!r} for {row_unit!r} -> {canonical!r}; "
                "set its energy_content / density / value to convert"
            )
            return coefficient
        try:
            with self._ureg.context(ctx):
                return float((coefficient * self._ureg(row_unit)).to(canonical).magnitude)
        except Exception as exc:  # degrade-never-raise
            self._note(f"conversion {row_unit!r} -> {canonical!r} for {target_id!r} failed: {exc}")
            return coefficient

    # -- internals -------------------------------------------------------------

    def _note(self, message: str) -> None:
        if message in self.issues:  # dedup — io_t replays the same (target, unit) per year
            return
        self.issues.append(message)
        logger.warning("unit conversion: %s", message)

    def _canonical_unit(self, target_id: str, role: str) -> str | None:
        unit = (
            self._impact_units.get(target_id)
            if role == "impact"
            else self._flow_units.get(target_id)
        )
        return unit or None

    def _parseable(self, unit: str) -> bool:
        try:
            self._ureg.Unit(unit)
            return True
        except Exception:
            return False

    def _same_dimension(self, a: str, b: str) -> bool:
        try:
            return bool(self._ureg.Unit(a).dimensionality == self._ureg.Unit(b).dimensionality)
        except Exception:
            return False

    def _convert(self, coef: float, from_unit: str, to_unit: str, target_id: str) -> float:
        try:
            return float((coef * self._ureg(from_unit)).to(to_unit).magnitude)
        except Exception as exc:  # degrade-never-raise
            self._note(f"conversion {from_unit!r} -> {to_unit!r} for {target_id!r} failed: {exc}")
            return coef

    def _flow_context(self, flow_id: str) -> Any:
        if flow_id not in self._ctx_cache:
            self._ctx_cache[flow_id] = self._build_context(flow_id)
        return self._ctx_cache[flow_id]

    def _build_context(self, flow_id: str) -> Any:
        from pint import Context

        ctx = Context(f"cmdty_{flow_id}")
        added = False
        for key, value in self._flow_props.get(flow_id, {}).items():
            parsed = _parse_factor_key(str(key))
            if parsed is None:
                continue
            num, den = parsed
            if not (self._parseable(num) and self._parseable(den)):
                continue
            try:
                q = float(value) * self._ureg(num) / self._ureg(den)
                num_dim = self._ureg.Unit(num).dimensionality
                den_dim = self._ureg.Unit(den).dimensionality
            except Exception:
                continue
            if num_dim == den_dim:  # not a cross-dimension bridge — skip
                continue
            # q has dimensionality [num]/[den]: bridge this flow's measures.
            ctx.add_transformation(den_dim, num_dim, _scale_to(q))
            ctx.add_transformation(num_dim, den_dim, _scale_by_inverse(q))
            added = True
        return ctx if added else None
