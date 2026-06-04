"""The shipping sector pack.

Shipping consumes the canonical generic sheets, so model building reuses the
domain-agnostic assembler. The pack adds shipping-specific *validation*
(engine↔fuel referential integrity, baseline-mix shares) on top of the generic
required-sheet check, plus the sector schema and terminology.
"""

from __future__ import annotations

from typing import Any

from pathwise.data.validation import (
    ValidationReport,
    check_foreign_key,
    check_shares_sum_to_one,
    require_sheets,
)
from pathwise.data.workbook import Workbook, workbook_to_frames
from pathwise.domains.base import DomainPack
from pathwise.domains.shipping import schema as shipping_schema


class ShippingDomain(DomainPack):
    """Shipping fleet decarbonisation pack."""

    name = "shipping"
    label = "Shipping Fleet"

    def required_sheets(self) -> list[str]:
        return list(shipping_schema.REQUIRED_SHEETS)

    def schema(self) -> dict[str, Any]:
        return shipping_schema.SCHEMA

    def terminology(self) -> dict[str, str]:
        return shipping_schema.TERMINOLOGY

    def validate(self, workbook: Workbook) -> ValidationReport:
        """Validate required sheets plus shipping referential integrity."""
        report = ValidationReport()
        frames = workbook_to_frames(workbook)
        require_sheets(frames, self.required_sheets(), report)
        if not report.ok:
            return report  # cannot do FK checks without the sheets

        tech_ids = {str(t) for t in frames["technologies"]["technology_id"]}
        carrier_ids = {str(c) for c in frames["carriers"]["carrier_id"]}

        check_foreign_key(frames["assets"], "technology_id", tech_ids, "assets", report)
        cc = frames["carrier_compatibility"]
        check_foreign_key(cc, "technology_id", tech_ids, "carrier_compatibility", report)
        check_foreign_key(cc, "carrier_id", carrier_ids, "carrier_compatibility", report)

        if "baseline_mix" in frames:
            bm = frames["baseline_mix"]
            check_foreign_key(bm, "technology_id", tech_ids, "baseline_mix", report)
            check_foreign_key(bm, "carrier_id", carrier_ids, "baseline_mix", report)
            check_shares_sum_to_one(bm, "technology_id", "share", "baseline_mix", report)

        if "transitions" in frames:
            tr = frames["transitions"]
            check_foreign_key(tr, "from_technology_id", tech_ids, "transitions", report)
            check_foreign_key(tr, "to_technology_id", tech_ids, "transitions", report)
        return report
