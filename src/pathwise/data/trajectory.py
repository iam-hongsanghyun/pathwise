"""Year-indexed trajectory interpolation.

Many inputs are sparse year→value mappings (carbon-price path, target limits,
cost multipliers). At parse time we densify them across every modelled year so
the model-building code can look up a value for any period without special
cases. This mirrors the trajectory-interpolation step in the reference ``ets``
config pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def interpolate(points: Mapping[int, float], years: Iterable[int]) -> dict[int, float]:
    r"""Linearly interpolate a sparse year→value mapping onto ``years``.

    Between two known years the value is linearly interpolated; before the
    first / after the last known year it is held flat (constant extrapolation).

    Algorithm:
        For a target year ``y`` bracketed by known years ``y0 < y < y1``::

            v(y) = v0 + (v1 - v0) * (y - y0) / (y1 - y0)

        Flat outside the known range: ``v(y) = v[min]`` for ``y <= min`` and
        ``v(y) = v[max]`` for ``y >= max``.

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
            # Find the bracketing known years.
            left = max(yk for yk in known_years if yk < y)
            right = min(yk for yk in known_years if yk > y)
            v0, v1 = points[left], points[right]
            out[y] = float(v0 + (v1 - v0) * (y - left) / (right - left))
    return out
