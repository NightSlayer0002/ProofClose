from __future__ import annotations

import csv
from io import StringIO
import random

from scripts.generate_demo import build_demo_files as _build_demo_files


__all__ = ["build_demo_files", "scenario_manifest"]


SETTLEMENT_SCENARIOS = (
    "unique_exact_match",
    "unique_exact_match",
    "unique_exact_match",
    "unique_exact_match",
    "unique_exact_match",
    "unique_exact_match",
    "order_excess",
    "settlement_ledger_mismatch",
    "paise_rupee_mismatch",
    "duplicate_bank_candidates",
    "missing_bank_credit",
    "pending",
)


BOUNDARY_SCENARIOS = (
    "shared_bank_row",
    "utr_mismatch",
    "amount_mismatch",
    "time_mismatch",
    "single_amount_only_candidate",
    "multiple_amount_only_candidates",
    "future_timestamp",
    "non_processable_status",
    "currency_mismatch",
    "proof_mutation",
    "unavailable_v1_rule",
)


def scenario_manifest(seed: int = 20260831) -> dict:
    """Return the deterministic, seed-specific scenario-to-ID assignment."""
    physical_numbers = list(range(1, len(SETTLEMENT_SCENARIOS) + 1))
    random.Random(seed).shuffle(physical_numbers)
    settlements = [
        {
            "scenario": scenario,
            "logical_index": logical,
            "settlement_id": f"setl_PC{physical:03d}",
            "utr": f"HDFC2608PC{physical:05d}",
        }
        for logical, (scenario, physical) in enumerate(
            zip(SETTLEMENT_SCENARIOS, physical_numbers, strict=True), start=1
        )
    ]
    return {
        "seed": seed,
        "settlements": settlements,
        "boundary_scenarios": list(BOUNDARY_SCENARIOS),
    }


def _replacement_maps(seed: int) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    manifest = scenario_manifest(seed)
    settlement_ids: dict[str, str] = {}
    utrs: dict[str, str] = {}
    bank_refs: dict[str, str] = {}
    for assignment in manifest["settlements"]:
        logical = assignment["logical_index"]
        physical_id = assignment["settlement_id"]
        physical = int(physical_id[-3:])
        settlement_ids[f"setl_PC{logical:03d}"] = physical_id
        utrs[f"HDFC2608PC{logical:05d}"] = assignment["utr"]
        bank_refs[f"bank_PC{logical:03d}"] = f"bank_PC{physical:03d}"
    return settlement_ids, utrs, bank_refs


def _rewrite_csv(content: bytes, replacements: tuple[dict[str, str], ...]) -> bytes:
    source = StringIO(content.decode("utf-8"), newline="")
    reader = csv.DictReader(source)
    if reader.fieldnames is None:
        raise ValueError("evaluation CSV is missing a header")
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\r\n")
    writer.writeheader()
    for row in reader:
        rewritten: dict[str, str] = {}
        for key, value in row.items():
            current = value
            for mapping in replacements:
                if current in mapping:
                    current = mapping[current]
                    break
                embedded = next(((old, new) for old, new in mapping.items() if old in current), None)
                if embedded is not None:
                    current = current.replace(embedded[0], embedded[1])
                    break
            rewritten[key] = current
        writer.writerow(rewritten)
    return output.getvalue().encode("utf-8")


def build_demo_files(seed: int = 20260831) -> dict[str, tuple[str, bytes]]:
    """Generate demo rows whose scenario identifiers truly vary by seed."""
    files = _build_demo_files(seed)
    replacements = _replacement_maps(seed)
    return {
        source_type: (filename, _rewrite_csv(content, replacements))
        for source_type, (filename, content) in files.items()
    }
