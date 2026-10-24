import json
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path

from document_agent.core import (AgentError, format_date, package, parse_header, parse_request,
                                 parse_tab_count, report_text, row_meta, safe_name)
from document_agent.mailbox import build_reply


def it(text, x, y, w=120, h=20):
    return {"text": text, "x": x, "y": y, "w": w, "h": h}


TABS_Y = 432
VALUES = [
    it("M12205", 43, 297), it("Closed", 43, 337),
    it("Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project - $69,275,000", 215, 295, 420, 60),
    it("Water", 692, 297), it("Capital Expenditure", 692, 337),
    it("04/07/2025", 926, 297), it("10/23/2025", 1064, 297), it("Directions given", 1197, 297),
    it("Back to Search Results", 1410, 393), it("Nova Scotia Energy Board", 150, 160),
    it("Public Documents Database", 30, 100),
]
LABELS_COMBINED = [it("Matter No Status", 37, 240), it("Title - Description", 211, 240),
                   it("Type Category", 689, 240), it("Date Received", 906, 240),
                   it("Date Final Submissions", 1061, 240), it("Outcome", 1200, 240)]
LABELS_SPLIT = [it("Matter No", 37, 240), it("Status", 37, 257), it("Title - Description", 211, 240),
                it("Type", 689, 240), it("Category", 689, 257), it("Date Received", 906, 240),
                it("Date Final", 1061, 240), it("Submissions", 1061, 257), it("Outcome", 1200, 240)]


class Parsing(unittest.TestCase):
    def test_requests(self):
        self.assertEqual(parse_request("Hi Agent, Can you give me Other Documents files from M12205? Thanks!"), ("M12205", "Other Documents"))
        self.assertEqual(parse_request("m 12383 audio please"), ("M12383", "Recordings"))
        self.assertEqual(parse_request("M12205 exhibits\n> M12383 transcripts"), ("M12205", "Exhibits"))

    def test_bad_requests(self):
        for text in ("M1220 exhibits", "M122050 exhibits", "M12205 exhibits transcripts", "M12205 M12383 exhibits", "hello"):
            with self.assertRaises(ValueError):
                parse_request(text)

    def test_tab_count(self):
        self.assertEqual(parse_tab_count("Other Documents - 43"), ("Other Documents", 43))
        self.assertEqual(parse_tab_count("Recordings - 0"), ("Recordings", 0))
        self.assertEqual(parse_tab_count("Hearings"), (None, None))

    def test_header_combined_and_split_labels(self):
        for labels in (LABELS_COMBINED, LABELS_SPLIT):
            h, raw = parse_header(labels + VALUES, TABS_Y)
            self.assertEqual(h["matter_no"], "M12205")
            self.assertEqual(h["status"], "Closed")
            self.assertTrue(h["title"].endswith("$69,275,000"))
            self.assertEqual((h["type"], h["category"]), ("Water", "Capital Expenditure"))
            self.assertEqual((h["received"], h["final"]), ("04/07/2025", "10/23/2025"))
            self.assertEqual(h["outcome"], "Directions given")
            self.assertNotIn("Back to Search Results", h.values())

    def test_header_unknown_layout_returns_nothing_not_guesses(self):
        h, raw = parse_header([it("random", 10, 10)], TABS_Y)
        self.assertEqual(h, {})

    def test_dates(self):
        self.assertEqual(format_date("04/07/2025"), "April 7, 2025")
        self.assertEqual(format_date("garbage"), "garbage")

    def test_filenames(self):
        self.assertEqual(safe_name("../../evil.pdf"), "evil.pdf")
        self.assertEqual(safe_name("C:\\tmp\\a.pdf"), "a.pdf")
        self.assertEqual(safe_name(""), "document.bin")


def rows(n=3, base=585, pitch=85):
    items = []
    for r in range(n):
        b = base + pitch * r
        items += [it(str(102329 + r), 40, b - 40), it(f"Title number {r}", 185, b - 40, 600), it(".pdf", 1360, b - 40),
                  it("06/10/2026", 1490, b - 40), it("Public", 40, b + 4), it("GO GET IT", 1360, b, 120, 32), it("Preview", 1490, b, 120, 32)]
    return items


class Rows(unittest.TestCase):
    def test_row_meta_isolated_per_row(self):
        items = rows()
        for r in range(3):
            m = row_meta(items, r)
            self.assertEqual(m["row_doc_id"], str(102329 + r))
            self.assertEqual(m["title"], f"Title number {r}")
            self.assertEqual(m["date"], "06/10/2026")

    def test_row_meta_out_of_range(self):
        self.assertEqual(row_meta(rows(1), 5), {})


def result(downloads, counts=None, header=None, category="Other Documents", errors=None):
    return {"matter": "M12205", "category": category,
            "counts": counts or {"Exhibits": 13, "Key Documents": 6, "Other Documents": 43, "Transcripts": 0, "Recordings": 0},
            "header": header or {}, "found_count": 43, "downloads": downloads, "errors": errors or [], "warnings": []}


class Packaging(unittest.TestCase):
    def test_zip_manifest_and_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "01_102674.pdf"
            p.write_bytes(b"test")
            r = result([{"path": str(p), "filename": p.name, "row_doc_id": "102674", "title": "Board Order", "date": "07/08/2026", "id_matches_filename": True}])
            z = package(r, d)
            with zipfile.ZipFile(z) as zf:
                self.assertEqual(set(zf.namelist()), {"01_102674.pdf", "manifest.csv", "coverage.json"})
                self.assertIn(b"9f86d081", zf.read("manifest.csv"))
                cov = json.loads(zf.read("coverage.json"))
                self.assertEqual(cov["category_entry_sum"], 62)
            self.assertIsNone(package(result([]), tempfile.mkdtemp()))


class Report(unittest.TestCase):
    HEADER = {"matter_no": "M12205", "status": "Closed", "title": "Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project - $69,275,000",
              "type": "Water", "category": "Capital Expenditure", "received": "04/07/2025", "final": "10/23/2025",
              "final_label": "Date Final Submissions", "outcome": "Directions given"}

    def test_full_report(self):
        text = report_text(result([{"path": "x"}] * 10, header=self.HEADER))
        for needle in ("Halifax Regional Water Commission", "April 7, 2025", "October 23, 2025", "13 Exhibits, 6 Key Documents, 43 Other Documents, and no Transcripts or Recordings",
                       "62 files", "10 out of the 43 Other Documents"):
            self.assertIn(needle, text)

    def test_empty_category_and_missing_header(self):
        text = report_text(result([], counts={"Exhibits": 1, "Key Documents": 0, "Other Documents": 0, "Transcripts": 0, "Recordings": 0}))
        self.assertIn("has no Other Documents", text)
        self.assertIn("could not map the matter header", text)

    def test_failure_reported(self):
        text = report_text(result([], errors=[{"index": 2, "error": "empty file"}]))
        self.assertIn("#2 empty file", text)


class Mail(unittest.TestCase):
    def _orig(self):
        o = EmailMessage()
        o["From"], o["Subject"], o["Message-ID"] = "Paula <p@example.com>", "Request", "<a@example.com>"
        return o

    def test_threaded_reply(self):
        m = build_reply(self._orig(), "agent@example.com", "hi")
        self.assertEqual((m["To"], m["In-Reply-To"], m["Subject"]), ("p@example.com", "<a@example.com>", "Re: Request"))
        self.assertEqual(m["Auto-Submitted"], "auto-replied")

    def test_no_self_reply(self):
        o = self._orig()
        with self.assertRaises(ValueError):
            build_reply(o, "p@example.com", "hi")

    def test_oversize_raises(self):
        with tempfile.TemporaryDirectory() as d:
            big = Path(d) / "big.zip"
            big.write_bytes(b"0" * 25_000_000)
            with self.assertRaises(OverflowError):
                build_reply(self._orig(), "agent@example.com", "hi", big)


if __name__ == "__main__":
    unittest.main()
