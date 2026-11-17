from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class StrictModel(BaseModel):
    """Request base: unknown fields are rejected (prevents mass assignment) and strings trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
