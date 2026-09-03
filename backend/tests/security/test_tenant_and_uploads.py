from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.storage.schema import ProofOperationRecord


def client_for(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path)))


def test_path_traversal_upload_is_rejected(tmp_path) -> None:
    """An uploaded filename must not influence a path outside the evidence boundary."""
    with client_for(tmp_path) as client:
        response = client.post(
            "/api/sources/upload",
            data={"source_type": "bank_statement"},
            files={"file": ("../../bank.csv", b"bank_ref,utr,credit_amount_paise,value_date,narration\nb1,U1,100,2026-08-26,x\n", "text/csv")},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "UPLOAD_REJECTED"


def test_invalid_upload_type_is_rejected(tmp_path) -> None:
    """Extension and MIME boundaries must reject non-CSV parser input."""
    with client_for(tmp_path) as client:
        response = client.post(
            "/api/sources/upload",
            data={"source_type": "bank_statement"},
            files={"file": ("bank.pdf", b"%PDF", "application/pdf")},
        )
        assert response.status_code == 400


def test_csv_filename_with_unsupported_mime_is_rejected(tmp_path) -> None:
    """The API boundary must not trust a CSV-looking filename over its declared media type."""
    with client_for(tmp_path) as client:
        response = client.post(
            "/api/sources/upload",
            data={"source_type": "bank_statement"},
            files={"file": ("bank.csv", b"{}", "application/json")},
        )
        assert response.status_code == 400


def test_proof_lookup_is_tenant_scoped_at_api_boundary(tmp_path) -> None:
    """A caller cannot select another tenant and then retrieve its proof."""
    with client_for(tmp_path) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        proof_id = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"][0]["proof_id"]
        response = client.get(f"/api/proofs/{proof_id}", headers={"X-Tenant-ID": "another_merchant"})
        assert response.status_code == 403


def test_cross_tenant_lifecycle_attempt_does_not_reveal_or_record_proof(tmp_path) -> None:
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        proof_id = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"][0]["proof_id"]

        reproduce = client.post(
            f"/api/proofs/{proof_id}/reproduce", headers={"X-Tenant-ID": "another_merchant"}
        )
        reevaluate = client.post(
            f"/api/proofs/{proof_id}/reevaluate", headers={"X-Tenant-ID": "another_merchant"}
        )
        missing = client.post(
            "/api/proofs/proof_missing/reproduce", headers={"X-Tenant-ID": "another_merchant"}
        )

        with app.state.database.session() as session:
            operations = list(
                session.scalars(
                    select(ProofOperationRecord).where(ProofOperationRecord.proof_id == proof_id)
                )
            )

    app.state.database.dispose()
    app.state.observability.dispose()

    assert reproduce.status_code == 403
    assert reevaluate.status_code == 403
    assert missing.status_code == 403
    assert operations == []


def test_runtime_package_does_not_import_evaluation_ground_truth() -> None:
    """Removing the eval/runtime wall would let labels leak into product decisions."""
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in Path("backend/app").rglob("*.py"))
    assert "match_ground_truth" not in runtime
    assert "exception_ground_truth" not in runtime
