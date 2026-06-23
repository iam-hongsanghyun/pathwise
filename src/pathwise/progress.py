"""Shared progress-reporting callback type.

A backend that runs many internal solves (e.g. the frontier ε-constraint sweep
or the portfolio per-asset reward pass) calls ``progress(done, total, label)``
so the job store can surface live completed / total / remaining counts to the
client. Backends that solve once simply never call it — the job stays
``running`` until it is ``done``.
"""

from __future__ import annotations

from collections.abc import Callable

#: ``progress(done, total, label)`` — units finished so far, units in total, and
#: a short human note (e.g. the current cap or asset). ``total - done`` is the
#: remaining count the UI shows.
ProgressFn = Callable[[int, int, str], None]
