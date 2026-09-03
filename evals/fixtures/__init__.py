from pathlib import Path


def assistant_fixtures_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assistant_fixtures.json"


__all__ = ["assistant_fixtures_path"]
