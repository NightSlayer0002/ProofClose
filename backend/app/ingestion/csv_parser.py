import csv
from dataclasses import dataclass
from io import StringIO

from app.ingestion.security import UploadLimits, UploadValidationError


@dataclass(frozen=True)
class ParsedCsv:
    """A structurally validated CSV with each data record's physical row number."""

    headers: list[str]
    numbered_rows: list[tuple[int, dict[str, str]]]


def parse_csv(content: bytes, limits: UploadLimits) -> ParsedCsv:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("CSV must be UTF-8 encoded") from exc

    reader = csv.reader(StringIO(text, newline=""), strict=True)
    try:
        raw_headers = next(reader, None)
        if raw_headers is None:
            raise UploadValidationError("CSV header is missing")
        headers = [header.strip() for header in raw_headers]
        if not headers:
            raise UploadValidationError("CSV header is missing")
        if any(not header for header in headers):
            raise UploadValidationError("CSV has a blank header name")
        if len(set(headers)) != len(headers):
            raise UploadValidationError("CSV has a duplicate header")

        numbered_rows: list[tuple[int, dict[str, str]]] = []
        for row_number, cells in enumerate(reader, start=2):
            if row_number - 1 > limits.max_rows:
                raise UploadValidationError(
                    f"row {row_number} field record: CSV exceeds {limits.max_rows} row limit"
                )
            if not cells:
                continue
            if len(cells) > len(headers):
                raise UploadValidationError(f"row {row_number} field record: CSV has more cells than headers")
            row = {header: (cells[index].strip() if index < len(cells) else "") for index, header in enumerate(headers)}
            numbered_rows.append((row_number, row))
    except csv.Error as exc:
        raise UploadValidationError(
            f"row {max(reader.line_num, 1)} field record: CSV syntax is invalid"
        ) from exc

    if not numbered_rows:
        raise UploadValidationError("CSV contains no data rows")
    return ParsedCsv(headers=headers, numbered_rows=numbered_rows)
