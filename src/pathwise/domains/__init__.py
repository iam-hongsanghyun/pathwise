"""pathwise.domains — sector packs and the domain registry.

Importing this package registers the built-in packs (currently shipping). A new
sector is added by creating ``pathwise/domains/<sector>/`` that calls
``register_domain`` and importing it here.

Public API: register_domain, get_domain, available_domains, DomainPack, DomainError.
"""

from __future__ import annotations

# Register built-in packs (side-effecting imports).
from pathwise.domains import shipping  # noqa: F401  (import for registration side effect)
from pathwise.domains.base import (
    DomainError,
    DomainPack,
    available_domains,
    get_domain,
    register_domain,
)

__all__ = [
    "DomainError",
    "DomainPack",
    "available_domains",
    "get_domain",
    "register_domain",
]
