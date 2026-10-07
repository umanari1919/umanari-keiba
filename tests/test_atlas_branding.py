"""NEO JIZO ATLAS / FORWARD presentation boundary contract."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class BrandBoundaryTests(unittest.TestCase):
    def test_research_dashboard_identifies_atlas(self):
        dashboard = source("tools/research_dashboard/dashboard_server.py")
        self.assertIn("<title>NEO JIZO ATLAS｜競馬研究ダッシュボード</title>", dashboard)
        self.assertIn("<b>NEO JIZO ATLAS｜競馬研究ダッシュボード</b>", dashboard)
        self.assertNotIn("THE JOCKEY｜完全自律競馬研究所", dashboard)
        self.assertIn('id="splits"', dashboard)
        self.assertIn('id="population"', dashboard)

    def test_prediction_panel_identifies_forward_in_source_and_page(self):
        header = "<h2>NEO JIZO FORWARD｜JRA 個人用予想 · jockey-25</h2>"
        for path in ("src/publish_weekend_ui.py", "web/index.html"):
            panel = source(path)
            self.assertIn(header, panel)
            self.assertIn('id="personal-weekend"', panel)
            self.assertIn("1着・2着以内・3着以内", panel)
            self.assertIn("自動購入は行いません", panel)
        publisher = source("src/publish_weekend_ui.py")
        self.assertIn("PERSONAL_WEEKEND_START", publisher)
        self.assertIn("PERSONAL_WEEKEND_END", publisher)
        self.assertIn("jockey_25", publisher)

    def test_combined_page_separates_branding(self):
        page = source("web/index.html")
        self.assertIn("<title>JIZO WORKS｜競馬研究・予測支援</title>", page)
        self.assertIn("<header>JIZO WORKS｜競馬研究・予測支援</header>", page)
        self.assertIn("<main><h1>NEO JIZO ATLAS｜競馬AI研究室</h1>", page)
        self.assertEqual(page.count("<!-- PERSONAL_WEEKEND_START -->"), 1)
        self.assertEqual(page.count("<!-- PERSONAL_WEEKEND_END -->"), 1)
        self.assertIn("過去データによる試作・本番未採用", page)


if __name__ == "__main__":
    unittest.main()
