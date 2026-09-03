from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
REQUIRED_SCREENSHOTS = (
    "landing.png",
    "landing-mobile.png",
    "reconciliation.png",
    "proof-drawer.png",
    "exceptions.png",
    "assistant-expanded.png",
    "close.png",
    "diagnostics.png",
    "responsive-wide.png",
    "responsive-desktop.png",
    "responsive-tablet-landscape.png",
    "responsive-tablet-portrait.png",
    "responsive-mobile.png",
)


def main() -> int:
    missing = [name for name in REQUIRED_SCREENSHOTS if not (SCREENSHOT_DIR / name).is_file()]
    empty = [
        name
        for name in REQUIRED_SCREENSHOTS
        if (SCREENSHOT_DIR / name).is_file() and (SCREENSHOT_DIR / name).stat().st_size == 0
    ]
    if missing or empty:
        if missing:
            print(f"Missing required screenshots: {', '.join(missing)}")
        if empty:
            print(f"Empty required screenshots: {', '.join(empty)}")
        return 1
    print(f"Verified {len(REQUIRED_SCREENSHOTS)} checked-in browser review screenshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
