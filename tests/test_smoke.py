"""Phase 0 smoke tests: package imports and configuration load cleanly."""

from __future__ import annotations

import importlib


def test_package_version() -> None:
    import pathwise

    assert pathwise.__version__


def test_subpackages_import() -> None:
    for name in (
        "pathwise.core",
        "pathwise.domains",
        "pathwise.data",
        "pathwise.results",
        "pathwise.backends",
        "pathwise.api",
    ):
        assert importlib.import_module(name) is not None


def test_settings_are_server_side_only() -> None:
    from pathwise.config import get_settings

    settings = get_settings()
    assert settings.solver_name == "highs"
    assert settings.max_solver_time_limit_s > 0
    assert settings.max_jobs >= 1
    assert settings.schema_version
    # Model parameters must NOT live in server config (they belong to the frontend).
    for forbidden in ("default_discount_rate", "default_carbon_price", "currency", "base_period"):
        assert not hasattr(settings, forbidden), f"{forbidden} should not be server-side config"


def test_logger_is_namespaced() -> None:
    from pathwise.logger import get_logger

    logger = get_logger(__name__)
    assert logger.name.startswith("pathwise")


def test_unit_registry_roundtrip() -> None:
    from pathwise.units import Q_

    assert Q_(10.0, "GJ").to("MJ").magnitude == 10000.0
