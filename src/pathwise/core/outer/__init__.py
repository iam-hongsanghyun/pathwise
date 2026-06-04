"""Outer (upper-level) search for bilevel optimisation.

The optimisers here drive the *upper level* of a two-level problem: they search
a bounded real vector and score each candidate via an injected callback that, in
pathwise, runs the inner cost-minimisation solve. They hold no I/O and no
pathwise data types.
"""

from __future__ import annotations

from pathwise.core.outer.search import INFEASIBLE_COST, SearchResult, anneal, sweep

__all__ = ["INFEASIBLE_COST", "SearchResult", "anneal", "sweep"]
