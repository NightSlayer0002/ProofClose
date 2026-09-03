from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_demo_headers_are_rejected_outside_demo_mode(tmp_path) -> None:
    """Request headers are not authentication and must never unlock production mode."""
    settings = Settings(PROOFCLOSE_ENV="production", PROOFCLOSE_DATA_DIR=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/health",
            headers={"X-Tenant-ID": "demo_merchant", "X-Actor-ID": "demo_operator"},
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "PRODUCTION_AUTH_REQUIRED"


def test_demo_mode_rejects_arbitrary_tenant_header(tmp_path) -> None:
    """Even the local demo must not become a cross-tenant selector."""
    settings = Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/sources", headers={"X-Tenant-ID": "another_merchant"})
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "DEMO_TENANT_NOT_ALLOWED"

