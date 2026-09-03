from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security.export import safe_csv_cell


def test_prompt_injection_in_bank_narration_cannot_authorize_match(tmp_path: Path) -> None:
    """Untrusted text that commands verification must remain inert financial data."""
    with TestClient(create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        rows = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]
        ambiguous = next(item for item in rows if item["settlement_id"] == "setl_PC010")
        assert ambiguous["decision"] == "REFUSED"
        assert ambiguous["exception_type"] == "AMBIGUOUS_MATCH"
        assert ambiguous["evidence"]["candidate_count"] == 2


def test_csv_formula_prefixes_are_escaped() -> None:
    """Opening exported untrusted narration must not execute a spreadsheet formula."""
    assert safe_csv_cell("=HYPERLINK('bad')") == "'=HYPERLINK('bad')"
    assert safe_csv_cell("+1+1") == "'+1+1"
    assert safe_csv_cell("-2+3") == "'-2+3"
    assert safe_csv_cell("@SUM(A1:A2)") == "'@SUM(A1:A2)"
    assert safe_csv_cell("RAZORPAY SETTLEMENT") == "RAZORPAY SETTLEMENT"
