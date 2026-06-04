"""pathwise.domains — sector packs and the domain registry.

Importing this package registers the built-in packs. A new sector adds
``pathwise/domains/<sector>/`` that calls ``register_domain`` and is imported here.
"""

from __future__ import annotations

from pathwise.domains import process  # noqa: F401  (registration side effect)
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
