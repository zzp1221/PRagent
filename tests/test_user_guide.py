import pathlib
import re
import unittest

from pragent.api import GUIDE_FILE, read_guide


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class UserGuideTests(unittest.TestCase):
    def test_guide_reads_as_a_real_manual(self):
        text = read_guide()
        self.assertGreater(len(text), 2000, "the guide should cover the console, not act as a stub")
        for heading in ("五分钟上手", "发起一次审查", "读懂报告", "提交反馈", "常见问题"):
            self.assertIn(heading, text)

    def test_guide_relative_links_resolve(self):
        # A guide that links to deleted files is worse than no guide.
        for target in re.findall(r"\]\((\.{0,2}/[^)\s#]+)\)", read_guide()):
            resolved = (REPO_ROOT / "docs" / target).resolve()
            self.assertTrue(resolved.exists(), "guide links to a missing file: %s" % target)

    def test_console_exposes_the_guide_view(self):
        index = (REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-view="guide"', index)
        self.assertIn('id="view-guide"', index)
        self.assertIn("function loadGuide", script)
        self.assertIn('api("/guide")', script)

    def test_guide_file_name_is_the_one_the_api_serves(self):
        self.assertEqual(GUIDE_FILE, "USER_GUIDE.md")
        self.assertTrue((REPO_ROOT / "docs" / GUIDE_FILE).is_file())


if __name__ == "__main__":
    unittest.main()
