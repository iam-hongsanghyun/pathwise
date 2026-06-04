"""pathwise — general-purpose multi-period process/asset transition optimiser.

A domain-agnostic optimisation engine (assets, technologies, measures,
periods, costs, targets) with pluggable *sector packs*. Shipping is the first
pack; new sectors (e.g. steel) are added under :mod:`pathwise.domains` without
touching the generic core.

Subpackages:
    core      Generic optimisation model (no I/O, no domain vocabulary).
    domains   Sector packs (shipping, …) + the DomainPack registry.
    data      Workbook / scenario loading, validation, imputation.
    results   Solution extraction, post-calculation, Excel export.
    backends  Pluggable solver backends (linopy + HiGHS).
    api       FastAPI web application.
"""

from __future__ import annotations

__version__ = "0.1.0"
