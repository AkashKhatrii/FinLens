"""PDF page extraction and candidate-page selection. No live network."""
from __future__ import annotations

from io import BytesIO
import unittest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.providers.bank_kpi_extractor import select_candidate_pages
from app.providers.pdf_text import PdfPage, extract_pdf_pages, extract_pdf_text, format_pages_for_ai


def pdf_bytes_for_pages(texts: list[str]) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 24 Tf 72 700 Td ({escaped}) Tj ET".encode("latin-1", "replace"))
        stream_ref = writer._add_object(stream)
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        font_ref = writer._add_object(font)
        resources = DictionaryObject()
        resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font_ref})
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = stream_ref
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestPdfPageExtraction(unittest.TestCase):
    def test_invalid_pdf_returns_no_pages(self):
        self.assertEqual(extract_pdf_pages(b"not a pdf"), [])
        self.assertEqual(extract_pdf_pages(b""), [])
        self.assertEqual(extract_pdf_pages(b"<!DOCTYPE html>"), [])

    def test_page_boundaries_and_numbers_are_preserved(self):
        content = pdf_bytes_for_pages([
            "Gross NPA 1.17 percent",
            "Hello world page two",
            "CET1 capital 17.4 percent",
        ])
        pages = extract_pdf_pages(content)
        self.assertEqual([page.number for page in pages], [1, 2, 3])
        self.assertIn("Gross NPA", pages[0].text)
        self.assertIn("Hello world", pages[1].text)
        self.assertIn("CET1", pages[2].text)
        joined = extract_pdf_text(content)
        self.assertIn("Gross NPA", joined)
        self.assertIn("Hello world", joined)

    def test_format_pages_keeps_page_markers(self):
        pages = [
            PdfPage(number=2, text="GNPA ratio at 1.17%"),
            PdfPage(number=14, text="CASA ratio 32%"),
        ]
        blob = format_pages_for_ai(pages)
        self.assertIn("--- Page 2 ---", blob)
        self.assertIn("--- Page 14 ---", blob)
        self.assertIn("GNPA ratio at 1.17%", blob)
        self.assertLess(blob.find("--- Page 2 ---"), blob.find("--- Page 14 ---"))


class TestCandidatePages(unittest.TestCase):
    def test_keyword_pages_are_selected_without_choosing_values(self):
        pages = [
            PdfPage(number=1, text="Cover page and legal disclaimer"),
            PdfPage(number=3, text="Net interest margin (NIM) of 3.26%"),
            PdfPage(number=28, text="ESG score and carbon-neutral target"),
        ]
        chosen = select_candidate_pages(pages)
        self.assertEqual([page.number for page in chosen], [3])
        self.assertEqual(chosen[0].text, pages[1].text)

    def test_asset_quality_and_capital_keywords_match(self):
        pages = [
            PdfPage(number=17, text="GNPA NNPA resilient asset quality"),
            PdfPage(number=19, text="Specific PCR and credit cost"),
            PdfPage(number=5, text="Abridged balance sheet only"),
        ]
        numbers = [page.number for page in select_candidate_pages(pages)]
        self.assertIn(17, numbers)
        self.assertIn(19, numbers)

    def test_no_keyword_hits_on_a_short_pdf_returns_all_pages(self):
        pages = [PdfPage(number=i, text=f"slide {i}") for i in range(1, 5)]
        chosen = select_candidate_pages(pages)
        self.assertEqual([page.number for page in chosen], [1, 2, 3, 4])

    def test_no_keyword_hits_on_a_large_pdf_returns_all_pages(self):
        pages = [PdfPage(number=i, text=f"disclaimer {i}") for i in range(1, 12)]
        chosen = select_candidate_pages(pages)
        self.assertEqual(len(chosen), 11)


if __name__ == "__main__":
    unittest.main()
