from pydantic import ValidationError
import pytest

from app.domain.enums import Decision, SubjectType
from app.domain.models import ConfigurationBundle, MatchEvidence, ProofSubject, ReconRow


def test_canonical_record_is_immutable() -> None:
    """Mutation would break snapshot and proof reproducibility."""
    row = ReconRow(
        tenant_id="demo",
        source_id="src_1",
        raw_record_id="raw_1",
        entity_id="pay_1",
        type="payment",
        credit_paise=100,
    )
    with pytest.raises(ValidationError):
        row.credit_paise = 200


def test_auto_verified_evidence_requires_unique_candidate() -> None:
    """A duplicate exact UTR-and-amount bank row must prevent automatic verification."""
    evidence = MatchEvidence(
        utr_exact=True,
        amount_exact=True,
        settlement_ledger_consistent=True,
        temporal_consistency=True,
        candidate_count=2,
        amount_delta_paise=0,
    )
    assert evidence.supports_auto_verification is False


def test_decision_vocabulary_is_bounded() -> None:
    """An unrecognized state could bypass the close policy."""
    assert {item.value for item in Decision} == {
        "AUTO_VERIFIED",
        "REVIEW_REQUIRED",
        "REFUSED",
        "UNRESOLVED",
        "PENDING",
        "SYSTEM_ERROR",
    }


def test_proof_subject_and_configuration_are_immutable_typed_value_objects() -> None:
    """Replacing the subject type or policy values would change what a proof means."""
    subject = ProofSubject(subject_type=SubjectType.SETTLEMENT, subject_id="setl_1")
    configuration = ConfigurationBundle(version="2.0", values={"pending_hours": 3})

    assert subject.model_dump(mode="json") == {"subject_type": "SETTLEMENT", "subject_id": "setl_1"}
    assert configuration.model_dump(mode="json") == {"version": "2.0", "values": {"pending_hours": 3}}
    with pytest.raises(ValidationError):
        subject.subject_id = "setl_2"
