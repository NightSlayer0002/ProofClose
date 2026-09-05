from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.close.service import CloseService
from app.config import Settings
from app.ingestion.service import IngestionService
from app.investigations.narration import InvestigationService
from app.investigations.provider import AssistantProvider, NvidiaProvider, ProviderCallBudget
from app.investigations.tools import FinanceTools
from app.observability.store import ObservabilityStore
from app.proofs.registry import RuleRegistry
from app.proofs.service import ProofService
from app.reconciliation.configuration import CONFIGURATION_BUNDLE_V2, ConfigurationRegistry
from app.reconciliation.rules import (
    ORDER_RULE_NAME,
    ORDER_RULE_VERSION_V1,
    SETTLEMENT_RULE_NAME,
    SETTLEMENT_RULE_VERSION_V1,
    SETTLEMENT_RULE_VERSION_V2,
)
from app.runs.service import RunService, evaluate_order_payment_v1, evaluate_proof_inputs_v1, evaluate_settlement_v2
from app.review.service import ReviewService
from app.storage.database import DatabaseManager
from app.storage.repositories import ProofArtifactRepository, SnapshotRepository, SourceRepository


def create_app(settings: Settings | None = None, assistant_provider: AssistantProvider | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = DatabaseManager(settings.product_database_url)
    database.create_schema()
    observability = ObservabilityStore(
        settings.observability_database_url,
        pricing_version=settings.pricing_version,
        input_cost_per_1k=settings.pricing_input_per_1k,
        output_cost_per_1k=settings.pricing_output_per_1k,
    )
    sources = SourceRepository(database)
    snapshots = SnapshotRepository(database)
    proof_artifacts = ProofArtifactRepository(database)
    ingestion = IngestionService(database, sources)
    registry = RuleRegistry()
    registry.register(SETTLEMENT_RULE_NAME, SETTLEMENT_RULE_VERSION_V1, evaluate_proof_inputs_v1)
    registry.register(SETTLEMENT_RULE_NAME, SETTLEMENT_RULE_VERSION_V2, evaluate_settlement_v2)
    registry.register(ORDER_RULE_NAME, ORDER_RULE_VERSION_V1, evaluate_order_payment_v1)
    registry.set_current(SETTLEMENT_RULE_NAME, SETTLEMENT_RULE_VERSION_V2)
    registry.set_current(ORDER_RULE_NAME, ORDER_RULE_VERSION_V1)
    configurations = ConfigurationRegistry()
    configurations.register(CONFIGURATION_BUNDLE_V2)
    configurations.set_current("2.0")
    proof_service = ProofService(registry, configurations=configurations, store=proof_artifacts)
    now = lambda: datetime.now(timezone.utc)
    run_service = RunService(database, sources, snapshots, proof_service, observability, configurations, now)
    review_service = ReviewService(database)
    close_service = CloseService(database, configuration_registry=configurations)
    provider = assistant_provider
    if provider is None and settings.nvidia_api_key:
        provider = NvidiaProvider(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            model=settings.nvidia_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    investigations = InvestigationService(
        FinanceTools(run_service, review_service, proof_service, close_service),
        provider=provider,
        observability=observability,
        budget=ProviderCallBudget(settings.provider_call_budget),
    )

    app = FastAPI(
        title="ProofClose",
        version="0.1.0",
        description="Evidence-first settlement reconciliation. Demo identity headers are not authentication.",
    )
    app.state.settings = settings
    app.state.database = database
    app.state.observability = observability
    app.state.sources = sources
    app.state.snapshots = snapshots
    app.state.proof_artifacts = proof_artifacts
    app.state.ingestion = ingestion
    app.state.configuration_registry = configurations
    app.state.proof_service = proof_service
    app.state.run_service = run_service
    app.state.review_service = review_service
    app.state.close_service = close_service
    app.state.investigations = investigations
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Tenant-ID", "X-Actor-ID"],
        allow_credentials=False,
    )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "INVALID_REQUEST", "message": "Request validation failed."}},
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(
                status_code=500,
                content={"detail": {"code": "INTERNAL_SERVER_ERROR", "message": "The request could not be completed."}},
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.middleware("http")
    async def reject_demo_identity_in_production(request: Request, call_next):
        if not settings.demo_mode and (
            request.headers.get("X-Tenant-ID") is not None or request.headers.get("X-Actor-ID") is not None
        ):
            response = JSONResponse(
                status_code=401,
                content={"detail": {"code": "PRODUCTION_AUTH_REQUIRED", "message": "Demo identity headers are not authentication."}},
            )
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                    "X-Frame-Options": "DENY",
                }
            )
            return response
        return await call_next(request)

    app.include_router(router)
    return app


app = create_app()
