"""Request/response models for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunPayload(BaseModel):
    """Body for ``POST /api/run``.

    Attributes:
        model: The in-memory workbook (``{sheet: rows[]}``).
        scenario: The run definition (a ``ScenarioConfig`` as a dict).
        options: Run metadata (``domain``, ``backend``, verbosity).
    """

    model: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    scenario: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
