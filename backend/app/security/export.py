import json
from hashlib import sha256
from typing import Any


DANGEROUS_PREFIXES = ("=", "+", "-", "@")


def safe_csv_cell(value: Any) -> str:
    text = str(value)
    return f"'{text}" if text.startswith(DANGEROUS_PREFIXES) else text


def build_close_pack(payload: dict[str, Any]) -> bytes:
    evidence_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    manifest_hash = f"sha256:{sha256(evidence_json.encode('utf-8')).hexdigest()}"
    pack = {"manifest_hash": manifest_hash, "close": payload}
    return json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")

