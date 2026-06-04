"""Year-indexed trajectory interpolation.

Sparse year→value mappings (prices, caps, demand, cost paths) are densified
across every modelled year so model-building code can look up any period without
special cases.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def interpolate(points: Mapping[int, float], years: Iterable[int]) -> dict[int, float]:
    r"""Linearly interpolate a sparse year→value mapping onto ``years``.

    Between two known years the value is linearly interpolated; before the first /
    after the last known year it is held flat (constant extrapolation).

    Algorithm:
        For a target year ``y`` bracketed by known ``y0 < y < y1``::

            v(y) = v0 + (v1 - v0) * (y - y0) / (y1 - y0)

        Flat outside the known range.

    Args:
        points: Known ``{year: value}`` pairs (at least one).
        years: Target years to produce values for.

    Returns:
        A dense ``{year: value}`` mapping covering ``years``.

    Raises:
        ValueError: If ``points`` is empty.
    """
    if not points:
        raise ValueError("interpolate() requires at least one known point")
    known = sorted(points.items())
    known_years = [y for y, _ in known]
    lo_y, lo_v = known[0]
    hi_y, hi_v = known[-1]

    out: dict[int, float] = {}
    for y in years:
        if y <= lo_y:
            out[y] = lo_v
        elif y >= hi_y:
            out[y] = hi_v
        elif y in points:
            out[y] = float(points[y])
        else:
            left = max(yk for yk in known_years if yk < y)
            right = min(yk for yk in known_years if yk > y)
            v0, v1 = points[left], points[right]
            out[y] = float(v0 + (v1 - v0) * (y - left) / (right - left))
    return out
