"""High-confidence secret scanner for tracked and untracked repository text."""

from __future__ import annotations

from pathlib import Path
import fnmatch
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git", ".venv", "node_modules", "dist", ".runtime", "results", ".superpowers",
    "__pycache__", ".pytest_cache", "coverage", "htmlcov", "build", "test-results",
    "playwright-report",
}
# Assemble token prefixes from fragments so this scanner does not flag its own
# implementation during a clean repository scan.
TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("razorpay credential", re.compile(r"\b" + "rzp_" + r"(?:live|test)_[A-Za-z0-9]{12,}\b")),
    ("NVIDIA credential", re.compile("\\b" + "nvapi-" + r"[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI credential", re.compile(r"\b" + "sk-" + r"(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("GitHub credential", re.compile(r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_\-]{20,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
)

# Match names such as AWS_SECRET_ACCESS_KEY and RAZORPAY_KEY_SECRET in
# addition to the short generic forms.  The value is intentionally captured
# only for local placeholder filtering; findings never include it.
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:[a-z0-9]+[_-])*"
    r"(?:api[_-]?key|key[_-]?(?:id|secret)|secret|token|password)"
    r"(?:[_-][a-z0-9]+)*\s*[:=]\s*(['\"]?)([^\s#,'\"]*)\1"
)
PLACEHOLDERS = (
    "example", "placeholder", "changeme", "change_me", "your_", "replace_me",
    "replace-this", "dummy", "fake", "not-a-secret", "your-key", "your-key-here",
)


def _ignored(path: Path, root: Path, gitignore_patterns: tuple[str, ...] = ()) -> bool:
    relative_parts = path.relative_to(root).parts
    if any(part in IGNORED_PARTS for part in relative_parts):
        return True
    if path.name == ".env":
        return True
    relative = path.relative_to(root).as_posix()
    for pattern in gitignore_patterns:
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern):
            return True
    return False


def _gitignore_patterns(root: Path) -> tuple[str, ...]:
    """Read the root ignore file for fixture roots that are not Git worktrees."""
    ignore_file = root / ".gitignore"
    if not ignore_file.is_file():
        return ()
    patterns: list[str] = []
    try:
        lines = ignore_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ()
    for line in lines:
        pattern = line.strip()
        if not pattern or pattern.startswith("#") or pattern.startswith("!"):
            continue
        pattern = pattern.removeprefix("/")
        if pattern.endswith("/"):
            pattern += "**"
        patterns.append(pattern)
    return tuple(patterns)


def _inventory(root: Path) -> list[Path]:
    """Return Git's tracked/untracked non-ignored inventory when available."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        result = None
    if result is not None and result.returncode == 0:
        paths = [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
        return [path for path in paths if path.is_file() and not _ignored(path, root)]

    patterns = _gitignore_patterns(root)
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not _ignored(path, root, patterns)
    ]


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    if not normalized:
        return True
    if normalized.startswith("${") and normalized.endswith("}"):
        return True
    if normalized.startswith("<") and normalized.endswith(">"):  # docs notation
        return True
    return any(marker in normalized for marker in PLACEHOLDERS)


def _high_confidence_assignment(value: str) -> bool:
    """Avoid treating typed Python annotations and references as credentials."""
    normalized = value.strip().strip("'\"")
    if len(normalized) < 16 or normalized in {"None", "False", "True"}:
        return False
    if normalized.startswith(("settings.", "Field(", "os.environ", "getenv(")):
        return False
    return not _placeholder(normalized)


def scan(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for path in _inventory(root):
        text = _read_text(path)
        if text is None:
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for category, pattern in TOKEN_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{relative}:{line_number}:{category}")
            assignment = ASSIGNMENT_PATTERN.search(line)
            if assignment and _high_confidence_assignment(assignment.group(2)):
                findings.append(f"{relative}:{line_number}:secret assignment")
    return sorted(set(findings))


if __name__ == "__main__":
    matches = scan()
    if matches:
        print("Potential secrets found:")
        print("\n".join(matches))
        sys.exit(1)
    print("Secret scan passed: no credential-shaped values found.")
