from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class ObsBase(DeclarativeBase):
    pass


class StageTiming(ObsBase):
    __tablename__ = "stage_timings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(48), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)


class OperationalEvent(ObsBase):
    __tablename__ = "operational_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)


class ObservabilityStore:
    def __init__(
        self,
        url: str,
        *,
        pricing_version: str | None = None,
        input_cost_per_1k: Decimal | int | float | str | None = None,
        output_cost_per_1k: Decimal | int | float | str | None = None,
    ) -> None:
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, connect_args={"check_same_thread": False})
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._pricing_version = pricing_version
        self._input_cost_per_1k = input_cost_per_1k
        self._output_cost_per_1k = output_cost_per_1k
        ObsBase.metadata.create_all(self.engine)

    def reset(self) -> None:
        ObsBase.metadata.drop_all(self.engine)
        ObsBase.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    def timing(self, tenant_id: str, run_id: str, stage: str, duration_ms: int, metadata: dict | None = None) -> None:
        with self._sessions.begin() as session:
            session.add(
                StageTiming(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    stage=stage,
                    duration_ms=duration_ms,
                    metadata_json=json.dumps(metadata or {}, sort_keys=True),
                )
            )

    def event(self, tenant_id: str, event_type: str, payload: dict[str, Any], run_id: str | None = None) -> None:
        sanitized = {key: value for key, value in payload.items() if "key" not in key.lower() and "secret" not in key.lower()}
        with self._sessions.begin() as session:
            session.add(
                OperationalEvent(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    event_type=event_type,
                    payload_json=json.dumps(sanitized, sort_keys=True),
                )
            )

    def timings_for_run(self, tenant_id: str, run_id: str) -> list[dict]:
        with self._sessions() as session:
            rows = list(
                session.scalars(
                    select(StageTiming).where(StageTiming.tenant_id == tenant_id, StageTiming.run_id == run_id)
                )
            )
        return [
            {"stage": row.stage, "duration_ms": row.duration_ms, "metadata": json.loads(row.metadata_json)}
            for row in rows
        ]

    def assistant_call(
        self,
        tenant_id: str,
        run_id: str,
        *,
        phase: str,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        model: str | None = None,
        failure_category: str | None = None,
    ) -> None:
        self.event(
            tenant_id,
            "ASSISTANT_PROVIDER_CALL",
            {
                "phase": phase,
                "status": status,
                "input_tokens": max(0, input_tokens),
                "output_tokens": max(0, output_tokens),
                "latency_ms": max(0, latency_ms),
                "model": model,
                "failure_category": failure_category,
            },
            run_id=run_id,
        )

    def assistant_summary(self, tenant_id: str, run_id: str) -> dict:
        with self._sessions() as session:
            rows = list(
                session.scalars(
                    select(OperationalEvent).where(
                        OperationalEvent.tenant_id == tenant_id,
                        OperationalEvent.run_id == run_id,
                        OperationalEvent.event_type == "ASSISTANT_PROVIDER_CALL",
                    )
                )
            )
        payloads = [json.loads(row.payload_json) for row in rows]
        cost = self._estimated_cost(payloads)
        return {
            "llm_calls": len(payloads),
            "llm_input_tokens": sum(int(item.get("input_tokens") or 0) for item in payloads),
            "llm_output_tokens": sum(int(item.get("output_tokens") or 0) for item in payloads),
            "estimated_llm_cost": cost,
            "pricing_version": self._pricing_version if cost != "unavailable" else None,
        }

    def _estimated_cost(self, payloads: list[dict]) -> str:
        """Calculate cost only with a complete, valid, versioned price card."""
        if (
            not isinstance(self._pricing_version, str)
            or not self._pricing_version.strip()
            or self._input_cost_per_1k is None
            or self._output_cost_per_1k is None
        ):
            return "unavailable"
        try:
            input_rate = Decimal(str(self._input_cost_per_1k))
            output_rate = Decimal(str(self._output_cost_per_1k))
        except (InvalidOperation, ValueError):
            return "unavailable"
        if not input_rate.is_finite() or not output_rate.is_finite() or input_rate < 0 or output_rate < 0:
            return "unavailable"
        total = sum(
            (
                (Decimal(int(item.get("input_tokens") or 0)) / Decimal(1000)) * input_rate
                + (Decimal(int(item.get("output_tokens") or 0)) / Decimal(1000)) * output_rate
            )
            for item in payloads
        )
        return format(total.normalize(), "f")
