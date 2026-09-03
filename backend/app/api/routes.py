import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from app.api.context import RequestContext, demo_context
from app.api.schemas import (
    ChallengeRequest,
    CloseApprovalRequest,
    InvestigationRequest,
    ReviewRequest,
    RunRequest,
    SnapshotRequest,
)
from app.ingestion.security import UploadValidationError
from app.proofs.fingerprint import ProofIntegrityError
from app.proofs.legacy import LegacyProofSchemaUnavailable
from app.proofs.service import ProofOperationResult
from app.close.integrity import ClosePackIntegrityError
from app.storage.schema import Base, ProofRecord, SourceRecord
from scripts.generate_demo import build_demo_files


router = APIRouter(prefix="/api")

DEMO_SOURCE_TYPES = frozenset(build_demo_files())


def _seed_demo(request: Request, context: RequestContext) -> dict:
    """Seed only an empty demo, or reuse accepted evidence already on disk."""
    sources = request.app.state.sources.list(context.tenant_id)
    accepted = [source for source in sources if source.state == "ACCEPTED"]
    if not accepted:
        for source_type, (filename, content) in build_demo_files().items():
            result = request.app.state.ingestion.ingest_csv(
                context.tenant_id, source_type, filename, content
            )
            if result.state != "ACCEPTED":
                raise HTTPException(
                    status_code=500,
                    detail={"code": "DEMO_INGESTION_FAILED", "message": "Synthetic demo evidence could not be loaded."},
                )
        accepted = [source for source in request.app.state.sources.list(context.tenant_id) if source.state == "ACCEPTED"]

    snapshot = request.app.state.snapshots.latest(context.tenant_id)
    if snapshot is None:
        # Choose at most one accepted source of each type, newest first, so a
        # partially uploaded merchant dataset is never silently overwritten.
        selected_by_type: dict[str, SourceRecord] = {}
        for source in sorted(accepted, key=lambda item: item.created_at, reverse=True):
            selected_by_type.setdefault(source.source_type, source)
        snapshot = request.app.state.snapshots.create(
            context.tenant_id, [source.id for source in selected_by_type.values()]
        )
    source_ids = json.loads(snapshot.source_ids_json)
    source_by_id = {source.id: source for source in accepted}
    record_count = sum(source_by_id[source_id].row_count for source_id in source_ids if source_id in source_by_id)
    request.app.state.latest_snapshot_id = snapshot.snapshot_id
    return {
        "identity_mode": context.identity_mode,
        "source_ids": source_ids,
        "record_count": record_count,
        "snapshot_id": snapshot.snapshot_id,
    }


@router.get("/health")
def health(request: Request) -> dict:
    settings = request.app.state.settings
    provider = request.app.state.investigations.provider_status()
    return {
        "status": "ok",
        "deterministic_reconciliation": "available",
        "ai_assistance": "ai_assisted_evidence_mode" if provider.configuration_status == "configured" else "evidence_mode",
        "provider": provider.model_dump(mode="json"),
        "identity_mode": "INSECURE_DEMO_CONTEXT" if settings.demo_mode else "PRODUCTION_AUTH_REQUIRED",
    }


@router.post("/demo/seed")
def seed_demo(request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    return _seed_demo(request, context)


@router.post("/demo/reset")
def reset_demo(request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    if not request.app.state.settings.allow_destructive_demo_reset:
        raise HTTPException(
            status_code=403,
            detail={"code": "DEMO_RESET_DISABLED", "message": "Destructive demo reset is disabled."},
        )
    database = request.app.state.database
    Base.metadata.drop_all(database.engine)
    Base.metadata.create_all(database.engine)
    request.app.state.observability.reset()
    request.app.state.proof_service.clear()
    return _seed_demo(request, context)


@router.get("/sources")
def list_sources(request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    items = request.app.state.sources.list(context.tenant_id)
    return {
        "identity_mode": context.identity_mode,
        "items": [
            {
                "source_id": item.id,
                "source_type": item.source_type,
                "filename": item.filename,
                "state": item.state,
                "row_count": item.row_count,
                "content_hash": item.content_hash,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
    }


@router.post("/sources/upload")
async def upload_source(
    request: Request,
    source_type: str = Form(...),
    file: UploadFile = File(...),
    context: RequestContext = Depends(demo_context),
) -> dict:
    if source_type not in DEMO_SOURCE_TYPES:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SOURCE_TYPE", "message": "Unsupported source type."})
    if file.content_type not in {"text/csv", "application/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=400, detail={"code": "UPLOAD_REJECTED", "message": "Only CSV uploads are accepted."})
    content = await file.read(request.app.state.ingestion.limits.max_bytes + 1)
    try:
        result = request.app.state.ingestion.ingest_csv(
            context.tenant_id, source_type, file.filename or "", content
        )
    except (UploadValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "UPLOAD_REJECTED", "message": str(exc)}) from exc
    if result.state == "QUARANTINED":
        raise HTTPException(status_code=422, detail={"code": "SOURCE_QUARANTINED", "message": result.error})
    return {
        "source_id": result.source_id,
        "state": result.state,
        "accepted_rows": result.accepted_rows,
        "inserted_rows": result.inserted_rows,
        "duplicate_rows": result.duplicate_rows,
    }


@router.post("/runs")
def create_run(body: RunRequest, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    snapshot_id = body.snapshot_id or getattr(request.app.state, "latest_snapshot_id", None)
    if snapshot_id is None:
        latest = request.app.state.snapshots.latest(context.tenant_id)
        snapshot_id = latest.snapshot_id if latest else None
    if snapshot_id is None:
        raise HTTPException(status_code=409, detail={"code": "NO_SOURCE_SNAPSHOT", "message": "Load sources before running reconciliation."})
    return request.app.state.run_service.run_snapshot(context.tenant_id, snapshot_id)


@router.post("/snapshots")
def create_snapshot(
    body: SnapshotRequest,
    request: Request,
    context: RequestContext = Depends(demo_context),
) -> dict:
    if not body.source_ids:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_SOURCE_SELECTION", "message": "Select at least one accepted source."},
        )
    try:
        snapshot = request.app.state.snapshots.create(context.tenant_id, body.source_ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_SOURCE_SELECTION", "message": str(exc)},
        ) from exc
    request.app.state.latest_snapshot_id = snapshot.snapshot_id
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "source_ids": body.source_ids,
    }


@router.get("/runs/latest")
def get_latest_run(request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    try:
        return request.app.state.run_service.latest_run(context.tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND"}) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    try:
        return request.app.state.run_service.get_run(context.tenant_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND"}) from exc


@router.get("/runs/{run_id}/settlements")
def list_settlements(run_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    return {"items": request.app.state.run_service.list_results(context.tenant_id, run_id)}


@router.get("/exceptions")
def list_exceptions(run_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    return {"items": request.app.state.review_service.list_exceptions(context.tenant_id, run_id)}


@router.post("/exceptions/{exception_id}/review")
def review_exception(
    exception_id: str,
    body: ReviewRequest,
    request: Request,
    context: RequestContext = Depends(demo_context),
) -> dict:
    try:
        return request.app.state.review_service.review_exception(
            context.tenant_id, exception_id, body.action, context.actor_id, body.reason
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "EXCEPTION_NOT_FOUND"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_REVIEW", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "REVIEW_FROZEN", "message": str(exc)}) from exc


@router.get("/audit")
def list_audit(run_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    return {"items": request.app.state.review_service.list_audit(context.tenant_id, run_id)}


@router.get("/proofs/{proof_id}")
def get_proof(proof_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    try:
        proof = request.app.state.proof_service.get(proof_id, context.tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PROOF_NOT_FOUND"}) from exc
    except ProofIntegrityError as exc:
        raise HTTPException(status_code=409, detail={"code": "PROOF_INTEGRITY_FAILURE"}) from exc
    except LegacyProofSchemaUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "LEGACY_PROOF_SCHEMA_UNAVAILABLE"}) from exc
    if proof.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "PROOF_NOT_FOUND"})
    return proof.model_dump(mode="json")


@router.post("/proofs/{proof_id}/reproduce")
def reproduce_proof(proof_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    try:
        result = request.app.state.proof_service.reproduce(proof_id, context.tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PROOF_NOT_FOUND"}) from exc
    except (ProofIntegrityError, LegacyProofSchemaUnavailable) as exc:
        # The service normally converts these into stable failures. Keep the
        # route defensive for custom stores and never expose parser details.
        code = (
            "PROOF_INTEGRITY_FAILURE"
            if isinstance(exc, ProofIntegrityError)
            else "LEGACY_PROOF_SCHEMA_UNAVAILABLE"
        )
        raise HTTPException(status_code=409, detail={"code": code}) from exc
    except Exception:
        result = ProofOperationResult(status="FAILED", failure_type="PROOF_REPRODUCIBILITY_FAILURE")
    return {"operation": "HISTORICAL_REPRODUCTION", **result.model_dump(mode="json")}


@router.post("/proofs/{proof_id}/reevaluate")
def reevaluate_proof(proof_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    try:
        result = request.app.state.proof_service.reevaluate(proof_id, tenant_id=context.tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PROOF_NOT_FOUND"}) from exc
    except (ProofIntegrityError, LegacyProofSchemaUnavailable) as exc:
        code = (
            "PROOF_INTEGRITY_FAILURE"
            if isinstance(exc, ProofIntegrityError)
            else "LEGACY_PROOF_SCHEMA_UNAVAILABLE"
        )
        raise HTTPException(status_code=409, detail={"code": code}) from exc
    except Exception:
        result = ProofOperationResult(status="FAILED", failure_type="PROOF_REPRODUCIBILITY_FAILURE")
    return {"operation": "CURRENT_RULE_REEVALUATION", **result.model_dump(mode="json")}


@router.post("/proofs/{proof_id}/challenge")
def challenge_proof(
    proof_id: str,
    body: ChallengeRequest,
    request: Request,
    context: RequestContext = Depends(demo_context),
) -> dict:
    try:
        proof = request.app.state.proof_service.get(proof_id, context.tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "PROOF_NOT_FOUND"}) from exc
    return request.app.state.review_service.challenge_proof(
        context.tenant_id, proof.run_id, proof_id, context.actor_id, body.feedback_type, body.comment
    )


@router.post("/investigations/query")
def investigate(
    body: InvestigationRequest,
    request: Request,
    context: RequestContext = Depends(demo_context),
) -> dict:
    return request.app.state.investigations.answer(
        context.tenant_id,
        body.run_id,
        body.question,
        settlement_id=body.settlement_id,
        proof_id=body.proof_id,
        page=body.page,
        history=body.history,
    )


@router.get("/close")
def get_close(run_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> dict:
    return request.app.state.close_service.get_state(context.tenant_id, run_id)


@router.post("/close/approve")
def approve_close(
    body: CloseApprovalRequest,
    request: Request,
    context: RequestContext = Depends(demo_context),
) -> dict:
    try:
        return request.app.state.close_service.approve(
            context.tenant_id, body.run_id, context.actor_id, body.reason
        )
    except ClosePackIntegrityError:
        raise HTTPException(status_code=409, detail={"code": "CLOSE_PACK_INTEGRITY_FAILURE"}) from None
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail={"code": "CLOSE_POLICY_BLOCKED", "message": str(exc)}) from exc


@router.get("/close/export")
def export_close(run_id: str, request: Request, context: RequestContext = Depends(demo_context)) -> Response:
    try:
        content, pack_state = request.app.state.close_service.export_pack(context.tenant_id, run_id)
    except ClosePackIntegrityError:
        raise HTTPException(status_code=409, detail={"code": "CLOSE_PACK_INTEGRITY_FAILURE"}) from None
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "CLOSE_POLICY_BLOCKED", "message": str(exc)}) from exc
    return Response(
        content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="proofclose-{run_id}-{pack_state.lower()}-close-pack.json"'},
    )


@router.get("/ops/diagnostics")
def diagnostics(request: Request, run_id: str, context: RequestContext = Depends(demo_context)) -> dict:
    run = request.app.state.run_service.get_run(context.tenant_id, run_id)
    timeline = request.app.state.observability.timings_for_run(context.tenant_id, run_id)
    slowest = max(timeline, key=lambda item: item["duration_ms"], default={"stage": "none", "duration_ms": 0})
    proof_failure_count = request.app.state.proof_artifacts.count_failed_operations(context.tenant_id, run_id)
    assistant = request.app.state.observability.assistant_summary(context.tenant_id, run_id)
    return {
        "run": run,
        "timeline": timeline,
        "slowest_stage": slowest,
        **assistant,
        "provider": request.app.state.investigations.provider_status().model_dump(mode="json"),
        "proof_reproducibility_failures": proof_failure_count,
        "identity_mode": context.identity_mode,
    }
