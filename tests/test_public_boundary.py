from __future__ import annotations

from pathlib import Path
import unittest


class PublicBoundaryTests(unittest.TestCase):
    def test_repository_has_no_fixed_minute_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        forbidden = ("14" + ":40", "14" + ":45", "snapshot_" + "hhmm")
        for scan_root in [root / "public_runner", root / "scripts", root / ".github" / "workflows"]:
            for path in scan_root.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".json", ".yml", ".yaml"}:
                    text = path.read_text(encoding="utf-8")
                    for marker in forbidden:
                        self.assertNotIn(marker, text, f"forbidden marker in {path}")


if __name__ == "__main__":
    unittest.main()
