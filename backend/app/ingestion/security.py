from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath
import re


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class UploadLimits:
    max_bytes: int = 5 * 1024 * 1024
    max_rows: int = 5_000


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    content: bytes
    content_hash: str


def validate_upload(filename: str, content: bytes, limits: UploadLimits) -> ValidatedUpload:
    if not filename or PurePath(filename).name != filename or ".." in filename:
        raise UploadValidationError("unsafe filename")
    if not filename.lower().endswith(".csv"):
        raise UploadValidationError("only CSV files are supported in the demo")
    if len(content) > limits.max_bytes:
        raise UploadValidationError(f"file exceeds {limits.max_bytes} byte limit")
    if not content:
        raise UploadValidationError("empty files are not accepted")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return ValidatedUpload(safe_name, content, sha256(content).hexdigest())

