import os
import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parser  # noqa: E402

# Shaped like an AO3 "Download > HTML" file, plus work-skin classes in the text.
FIC = """
<html><body>
<div id="preface"><div class="meta"><h1>Test Fic</h1>
<div class="byline">by <a rel="author" href="#">Someone</a></div></div></div>
<div id="chapters" class="userstuff">
  <div class="meta group">
    <h2 class="heading">Chapter 1: Start</h2>
    <div class="summary"><p>Summary:</p><blockquote>Chapter summary</blockquote></div>
    <p>Chapter Notes</p><blockquote class="userstuff">A note</blockquote>
  </div>
  <div class="userstuff">
    <h3 class="landmark heading">Chapter Text</h3>
    <p>Hello <em>world</em>.</p>
    <p class="subtitle">Texts from Bob</p>
    <div class="calendar"><p>Monday: the big game</p></div>
    <p> </p>
  </div>
  <div class="endnotes"><p>Chapter End Notes</p><blockquote>End note</blockquote></div>
  <div class="meta group"><h2 class="heading">Chapter 2</h2></div>
  <div class="userstuff"><p>More text.</p></div>
</div>
</body></html>
"""


def bookify(no_notes: bool):
    return parser.format_fic(BeautifulSoup(FIC, "lxml"), no_notes)


class FormatFicTest(unittest.TestCase):
    def test_no_notes_keeps_story_text(self):
        html = bookify(no_notes=True)
        text = html.get_text()
        self.assertIn("Monday: the big game", text)
        self.assertIn("Texts from Bob", text)
        self.assertNotIn("A note", text)
        self.assertNotIn("End note", text)
        self.assertEqual(
            [h.get_text() for h in html.find_all("h2")],
            ["Chapter 1: Start", "Chapter 2"],
        )

    def test_notes_kept_by_default(self):
        html = bookify(no_notes=False)
        text = html.get_text()
        self.assertIn("A note", text)
        self.assertIn("End note", text)
        self.assertNotIn("Chapter summary", text)
        self.assertNotIn("Chapter Text", text)
        self.assertEqual(len(html.find_all("h2")), 2)

    def test_metadata(self):
        meta = parser.get_fic_metadata(BeautifulSoup(FIC, "lxml"))
        self.assertEqual(meta, {"title": "Test Fic", "author": "Someone"})


class UrlTest(unittest.TestCase):
    def test_full_work_url(self):
        self.assertEqual(
            parser.full_work_url("http://archiveofourown.org/works/123/chapters/456#x"),
            "https://archiveofourown.org/works/123?view_full_work=true&view_adult=true",
        )

    def test_verify_url(self):
        self.assertTrue(parser.verify_url("https://archiveofourown.org/works/1")[0])
        self.assertFalse(parser.verify_url("https://archiveofourown.org/tags/foo")[0])
        self.assertFalse(parser.verify_url("https://example.com/works/1")[0])
        self.assertFalse(parser.verify_url("https://archiveofourown.org/works/abc")[0])


class OutputPathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_adds_pdf_suffix(self):
        self.assertEqual(
            parser.output_path(str(self.dir / "book"), "T").name, "book.pdf"
        )
        # Never the source file itself.
        self.assertEqual(
            parser.output_path(str(self.dir / "fic.html"), "T").name, "fic.html.pdf"
        )

    def test_creates_folders(self):
        path = parser.output_path(str(self.dir / "a" / "b" / "x.pdf"), "T")
        self.assertTrue(path.parent.is_dir())

    def test_default_name_does_not_overwrite(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.dir)
        Path("My_ Fic.pdf").touch()
        self.assertEqual(parser.output_path(None, "My: Fic").name, "My_ Fic (2).pdf")


if __name__ == "__main__":
    unittest.main()
