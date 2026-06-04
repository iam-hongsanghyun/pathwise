"""Process domain pack — registers :class:`ProcessDomain`."""

from __future__ import annotations

from pathwise.domains.base import register_domain
from pathwise.domains.process.pack import ProcessDomain

register_domain(ProcessDomain())

__all__ = ["ProcessDomain"]
