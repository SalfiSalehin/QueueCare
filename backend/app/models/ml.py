"""Model registry and prediction log (tables from migration 0001)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Model, TimestampMixin


class ModelVersion(Model, TimestampMixin):
    """A trained model known to the system. Global (not clinic-scoped); at most one is active."""

    __tablename__ = "model_versions"

    version: Mapped[str] = mapped_column(Text, unique=True)
    algorithm: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    feature_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    artifact_ref: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PredictionLog(Model, TimestampMixin):
    """One prediction made when a patient joined a queue, later completed with the actual wait."""

    __tablename__ = "prediction_logs"

    clinic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("clinics.id"))
    token_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    model_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("model_versions.id"))
    pred_lower: Mapped[float] = mapped_column(Float)
    pred_median: Mapped[float] = mapped_column(Float)
    pred_upper: Mapped[float] = mapped_column(Float)
    actual_wait: Mapped[float | None] = mapped_column(Float)
    abs_error: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
