"""User-facing branding contract; no source data, DB or network required."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class BrandUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.page = (ROOT / "web" / "index.html").read_text(encoding="utf-8-sig")

    def test_research_title_and_explicit_navigation(self) -> None:
        self.assertIn("<title>NEO JIZO ATLAS｜競馬AI研究室</title>", self.page)
        self.assertEqual(self.page.count('id="research-lab"'), 1)
        self.assertIn('<h1>NEO JIZO ATLAS｜競馬AI研究室</h1>', self.page)
        self.assertIn('href="#research-lab">ATLAS｜研究・評価</a>', self.page)
        self.assertIn('href="#personal-weekend">FORWARD｜予測・検証</a>', self.page)
        self.assertIn('aria-label="プロジェクト内の移動"', self.page)

    def test_existing_prediction_section_has_forward_name(self) -> None:
        self.assertIn('id="personal-weekend"', self.page)
        self.assertIn('<h2>NEO JIZO FORWARD｜JRA 個人用予想 · jockey-25</h2>', self.page)
        self.assertIn('<h2>NEO JIZO FORWARD｜週末JRAの準備</h2>', self.page)

    def test_annual_research_section_has_atlas_name(self) -> None:
        self.assertIn('<h2>NEO JIZO ATLAS｜2025年・年間一括評価</h2>', self.page)

    def test_safety_disclosures_not_removed(self) -> None:
        self.assertIn('本番未採用', self.page)
        self.assertIn('確定出馬表の到着待ち', self.page)
        self.assertIn('自動購入は行いません', self.page)
        self.assertIn('当時の配信を証明するものではありません', self.page)

    def test_existing_marker_boundaries_still_unique(self) -> None:
        for marker in ("PERSONAL_WEEKEND", "WEEKEND_STATUS", "KEIBA_ANNUAL"):
            with self.subTest(marker=marker):
                self.assertEqual(self.page.count(f"<!-- {marker}_START -->"), 1)
                self.assertEqual(self.page.count(f"<!-- {marker}_END -->"), 1)

    def test_weekend_publisher_keeps_brand_on_regeneration(self) -> None:
        import publish_weekend_ui

        personal = {"captured_at": "2026-10-08T08:00:00+09:00", "predictions": []}
        replay = {"predictions": []}
        section = publish_weekend_ui.render(personal, replay)
        self.assertIn("NEO JIZO FORWARD｜JRA 個人用予想 · jockey-25", section)
        self.assertIn("当時の配信を証明するものではありません", section)
        self.assertIn("captured_at", section)
        self.assertIn("jockey_25", section)

    def test_other_publishers_preserve_section_brand(self) -> None:
        publishers = {
            "src/weekend_run.py": "NEO JIZO FORWARD｜週末JRAの準備",
            "src/publish_prospective_forecast.py": "NEO JIZO FORWARD｜将来レースの研究予測",
            "src/publish_training_oos_2026.py": "NEO JIZO ATLAS｜2026年・固定調教候補の評価",
            "src/publish_training_diagnostics_2026.py": "NEO JIZO ATLAS｜2026年診断：的中率と確率誤差の違い",
        }
        for file, brand in publishers.items():
            with self.subTest(file=file):
                self.assertIn(brand, (ROOT / file).read_text(encoding="utf-8-sig"))

    def test_game_not_claimed_to_be_available(self) -> None:
        self.assertNotIn('href="#the-jockey-game"', self.page)
        self.assertNotIn('id="the-jockey-game"', self.page)


if __name__ == "__main__":
    unittest.main()
