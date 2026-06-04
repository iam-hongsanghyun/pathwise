"""Shipping sector pack — registers :class:`ShippingDomain`."""

from __future__ import annotations

from pathwise.domains.base import register_domain
from pathwise.domains.shipping.pack import ShippingDomain

register_domain(ShippingDomain())

__all__ = ["ShippingDomain"]
