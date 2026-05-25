# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access
"""Tests for build_site.py markdown conversion and report loading."""

import unittest

import build_site


class TestInline(unittest.TestCase):
    def test_bold(self):
        self.assertEqual(build_site._inline("**hello**"), "<strong>hello</strong>")

    def test_italic(self):
        self.assertEqual(build_site._inline("*hello*"), "<em>hello</em>")

    def test_html_escaped(self):
        result = build_site._inline("<script>")
        self.assertIn("&lt;script&gt;", result)
        self.assertNotIn("<script>", result)

    def test_no_markup_unchanged(self):
        self.assertEqual(build_site._inline("plain text"), "plain text")


class TestMdToHtml(unittest.TestCase):
    def test_h1(self):
        self.assertIn("<h1>", build_site.md_to_html("# Heading"))

    def test_h2(self):
        self.assertIn("<h2>", build_site.md_to_html("## Section"))

    def test_hr(self):
        self.assertIn("<hr>", build_site.md_to_html("---"))

    def test_paragraph(self):
        html = build_site.md_to_html("Some text here")
        self.assertIn("<p>", html)
        self.assertIn("Some text here", html)

    def test_blank_lines_flush_paragraph(self):
        html = build_site.md_to_html("First\n\nSecond")
        self.assertEqual(html.count("<p>"), 2)

    def test_empty_string(self):
        self.assertEqual(build_site.md_to_html(""), "")


class TestExtractSummary(unittest.TestCase):
    def test_finds_executive_summary_line(self):
        text = "## EXECUTIVE SUMMARY: Quiet day over the area."
        result = build_site.extract_summary(text)
        self.assertIn("Quiet day", result)

    def test_strips_markdown_bold(self):
        text = "**EXECUTIVE SUMMARY:** Some **important** note."
        result = build_site.extract_summary(text)
        self.assertNotIn("**", result)

    def test_strips_heading_prefix(self):
        text = "## EXECUTIVE SUMMARY: Content here."
        result = build_site.extract_summary(text)
        self.assertFalse(result.startswith("#"))

    def test_no_summary_returns_fallback(self):
        result = build_site.extract_summary("No summary in this text.")
        self.assertEqual(result, "No summary available.")


if __name__ == "__main__":
    unittest.main()
