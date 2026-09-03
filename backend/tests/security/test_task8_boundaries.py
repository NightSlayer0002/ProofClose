from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.storage.schema import (
    AuditRecord,
    CloseApprovalRecord,
    ClosePackRecord,
    ExceptionRecord,
    ProofRecord,
    ReconciliationRecord,
    RunRecord,
    SourceRecord,
    SourceSnapshot,
)
from scripts.scan_secrets import scan


EXPECTED_HEADERS = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "x-frame-options": "DENY",
}


def make_client(tmp_path: Path, **env: object) -> tuple[TestClient, object]:
    settings = Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path, **env)
    app = create_app(settings)
    return TestClient(app, raise_server_exceptions=False), app


def assert_security_headers(response) -> None:
    for key, value in EXPECTED_HEADERS.items():
        assert response.headers.get(key) == value


def counts(app, model) -> int:
    with app.state.database.session() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_seed_is_idempotent_and_reset_is_denied_by_default(tmp_path: Path) -> None:
    client, app = make_client(tmp_path)
    with client:
        seeded = client.post("/api/demo/seed")
        assert seeded.status_code == 200
        first = seeded.json()
        counts_before = {model: counts(app, model) for model in (SourceRecord, SourceSnapshot, RunRecord, ProofRecord)}

        repeated = client.post("/api/demo/seed")
        assert repeated.status_code == 200
        assert repeated.json() == first
        assert {model: counts(app, model) for model in counts_before} == counts_before

        denied = client.post("/api/demo/reset")
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "DEMO_RESET_DISABLED"
        assert {model: counts(app, model) for model in counts_before} == counts_before
    app.state.database.dispose()
    app.state.observability.dispose()


def test_seed_preserves_existing_run_and_pack(tmp_path: Path) -> None:
    client, app = make_client(tmp_path)
    with client:
        first = client.post("/api/demo/seed").json()
        run = client.post("/api/runs", json={}).json()
        client.post("/api/close/approve", json={"run_id": run["run_id"], "reason": "Reviewed"})
        before = {
            model: counts(app, model)
            for model in (SourceRecord, SourceSnapshot, RunRecord, ReconciliationRecord, ProofRecord, ExceptionRecord, AuditRecord, CloseApprovalRecord, ClosePackRecord)
        }
        repeat = client.post("/api/demo/seed")
        assert repeat.status_code == 200
        assert repeat.json()["snapshot_id"] == first["snapshot_id"]
        assert client.get("/api/runs/latest").json()["run_id"] == run["run_id"]
        assert {model: counts(app, model) for model in before} == before
    app.state.database.dispose()
    app.state.observability.dispose()


def test_reset_requires_explicit_flag_and_only_clears_local_demo_state(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, PROOFCLOSE_ALLOW_DESTRUCTIVE_DEMO_RESET=True)
    with client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        assert client.get(f"/api/runs/{run['run_id']}").status_code == 200

        reset = client.post("/api/demo/reset")
        assert reset.status_code == 200
        assert client.get(f"/api/runs/{run['run_id']}").status_code == 404
        reseeded = reset.json()
        assert reseeded["record_count"] > 0
        assert client.get("/api/runs/latest").status_code == 404
    app.state.database.dispose()
    app.state.observability.dispose()


def test_production_rejects_seed_reset_and_demo_headers(tmp_path: Path) -> None:
    settings = Settings(PROOFCLOSE_ENV="production", PROOFCLOSE_DATA_DIR=tmp_path)
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        for path in ("/api/demo/seed", "/api/demo/reset"):
            response = client.post(path)
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "PRODUCTION_AUTH_REQUIRED"
            assert_security_headers(response)
        response = client.get("/api/health", headers={"X-Tenant-ID": "demo_merchant"})
        assert response.status_code == 401
        assert_security_headers(response)
    app.state.database.dispose()
    app.state.observability.dispose()


def test_headers_are_present_on_success_validation_and_404(tmp_path: Path) -> None:
    client, app = make_client(tmp_path)
    with client:
        for response in (
            client.get("/api/health"),
            client.post("/api/runs", json={"unexpected": True}),
            client.get("/api/not-found"),
        ):
            assert_security_headers(response)
    app.state.database.dispose()
    app.state.observability.dispose()


def test_cors_is_exactly_local_frontend_allowlist(tmp_path: Path) -> None:
    client, app = make_client(tmp_path)
    with client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, X-Tenant-ID",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert allowed.headers["access-control-allow-methods"] == "GET, POST"
        assert allowed.headers.get("access-control-allow-credentials") != "true"

        denied = client.options(
            "/api/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert denied.status_code == 400

        disallowed_header = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert disallowed_header.status_code == 400
    app.state.database.dispose()
    app.state.observability.dispose()


def test_request_models_forbid_unknown_and_bound_text(tmp_path: Path) -> None:
    client, app = make_client(tmp_path)
    with client:
        unknown = client.post("/api/snapshots", json={"source_ids": [], "extra": "x"})
        assert unknown.status_code == 422
        huge = client.post("/api/investigations/query", json={"run_id": "r", "question": "x" * 1001})
        assert huge.status_code == 422
        invalid_review = client.post("/api/exceptions/unknown/review", json={"action": "WAT", "reason": "r"})
        assert invalid_review.status_code == 422
    app.state.database.dispose()
    app.state.observability.dispose()


def test_secret_scanner_detects_named_families_without_revealing_values(tmp_path: Path) -> None:
    joined = "".join
    nvidia_name = "_".join(("NVIDIA", "API", "KEY"))
    razorpay_secret_name = "_".join(("RAZORPAY", "KEY", "SECRET"))
    aws_secret_name = "_".join(("AWS", "SECRET", "ACCESS", "KEY"))
    (tmp_path / "credentials.txt").write_text(
        "\n".join(
            [
                "R=" + joined(["rzp_", "live_", "A" * 20]),
                "N=" + joined(["nvapi-", "A" * 24]),
                "O=" + joined(["sk-", "A" * 24]),
                "G=" + joined(["ghp_", "A" * 24]),
                "AWS=" + "AKIA" + "A" * 16,
                "-" * 5 + "BEGIN " + "PRIVATE" + " KEY" + "-" * 5,
                nvidia_name + "=" + "realistic-secret-value",
                razorpay_secret_name + "=" + "B" * 24,
                aws_secret_name + "=" + "C" * 24,
            ]
        ),
        encoding="utf-8",
    )
    findings = scan(tmp_path)
    assert len(findings) >= 9
    assert all("A" * 12 not in finding for finding in findings)
    assert all("realistic" not in finding for finding in findings)


def test_secret_scanner_allows_empty_placeholders_and_ignores_local_env(tmp_path: Path) -> None:
    nvidia_name = "_".join(("NVIDIA", "API", "KEY"))
    openai_name = "_".join(("OPENAI", "API", "KEY"))
    token_name = "_".join(("API", "TOKEN"))
    (tmp_path / ".env").write_text(nvidia_name + "=realistic-secret-value\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        nvidia_name + "=\n" + openai_name + "=${" + openai_name + "}\n" + token_name + "=<your-token>\n",
        encoding="utf-8",
    )
    (tmp_path / "guide.txt").write_text("API_KEY=placeholder\n", encoding="utf-8")
    assert scan(tmp_path) == []


def test_secret_scanner_detects_credentials_in_extensionless_text(tmp_path: Path) -> None:
    (tmp_path / "notes").write_text("token=" + "x" * 24 + "\n", encoding="utf-8")

    findings = scan(tmp_path)

    assert findings == ["notes:1:secret assignment"]


def test_secret_scanner_does_not_read_ignored_text_files(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("token=" + "x" * 24 + "\n", encoding="utf-8")

    assert scan(tmp_path) == []


def test_ci_defines_the_fixed_verification_and_real_audits() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in (
        "python -m pytest backend/tests",
        "pip-audit==2.9.0",
        "python -m pip_audit --strict",
        "npm ci",
        "npm test -- --run",
        "npm run lint",
        "npm run typecheck",
        "npm run build",
        "npm audit --audit-level=high",
        "python scripts/scan_secrets.py",
        "python -m evals.runner",
    ):
        assert required in ci
    assert "demo/reset" not in ci
    assert "NVIDIA_API_KEY" not in ci
