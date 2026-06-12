"""Request models for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunPayload(BaseModel):
    """Body for ``POST /api/run``.

    Attributes:
        model: The in-memory workbook (``{sheet: rows[]}``). Optional when a
            ``sessionId`` is given — the backend then snapshots the session
            model, so the payload never carries the model from the browser.
        sessionId: Server-side session whose model to run.
        scenario: The run definition (a ``ScenarioConfig`` as a dict).
        options: Run metadata (``domain``, ``backend``, verbosity).
    """

    model: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    sessionId: str | None = None
    scenario: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
