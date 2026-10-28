"""
Unit tests for Signal Formatter & URL Resolution:
1. HTML/RSS markup is removed from signal summary.
2. Signal summary is returned as human-readable text.
3. JSON/dict summaries are parsed correctly (e.g. {'s1': '...', 's2': '...'}).
4. Actual source URL is preserved.
5. Company website is not incorrectly used when an article URL exists.
6. Missing source URL is handled gracefully.
7. Prospect summary remains factual and natural.
8. Missing prospect location doesn't create fabricated location text.
9. Signal provider names are humanized.
"""
import unittest
from app.services.signal_formatter import (
    clean_html_text,
    format_clean_signal_summary,
    resolve_signal_article_url,
    generate_factual_signal_summary,
    humanize_signal_source,
)
from app.services.prospect_summary import generate_selection_summary


class TestSignalFormattingAndURLs(unittest.TestCase):

    def test_1_html_rss_markup_removed_from_signal_summary(self):
        """Test that raw HTML, unclosed tags, and <a> hrefs are stripped cleanly."""
        raw_rss_html = '<a href="https://news.google.com/rss/articles/CBMi2gFBVV95cUxNOVE1...">We Think Mach7 Technologies (ASX:M7T) Can Afford To Drive Business Growth</a>'
        cleaned = clean_html_text(raw_rss_html)
        self.assertNotIn("<a", cleaned)
        self.assertNotIn("href=", cleaned)
        self.assertNotIn("news.google.com", cleaned)
        self.assertIn("Mach7 Technologies", cleaned)

        # Test unclosed chopped tag from character slicing (e.g. description[:300])
        chopped_html = '<a href="https://news.google.com/rss/articles/CBMi2gFBVV95cUxNOVE1'
        cleaned_chopped = clean_html_text(chopped_html)
        self.assertEqual(cleaned_chopped, "")

    def test_2_signal_summary_returned_as_human_readable_text(self):
        """Test generating a factual, clean 1-2 sentence human-readable summary."""
        summary = generate_factual_signal_summary(
            signal_type="news_expansion",
            headline="We Think Mach7 Technologies Can Afford To Drive Business Growth - simplywall.st",
            company="Mach7 Technologies",
            raw_description='<a href="https://news.google.com/rss/articles/CBMi2g...">Mach7 Technologies</a> is expanding operations.',
        )
        self.assertNotIn("<a", summary)
        self.assertNotIn("href=", summary)
        self.assertIn("Mach7 Technologies", summary)
        self.assertTrue(len(summary) > 20)

    def test_3_json_dict_summaries_parsed_correctly(self):
        """Test parsing stringified Python dicts or JSON containing keys like s1, s2, summary."""
        # Python dict with single quotes as seen in Screenshot 5
        py_dict_str = "{'s1': 'Mach7 Technologies is expanding geographically while hiring sales leadership and adopting HubSpot to support its go-to-market operations.', 's2': 'This signals a prioritization of commercial scale and market expansion.'}"
        cleaned = format_clean_signal_summary(py_dict_str)
        self.assertNotIn("{'s1'", cleaned)
        self.assertNotIn("'s2'", cleaned)
        self.assertNotIn("}", cleaned)
        self.assertIn("Mach7 Technologies is expanding geographically", cleaned)
        self.assertIn("This signals a prioritization of commercial scale", cleaned)

        # Standard JSON object string
        json_str = '{"summary": "US HealthConnect announced expansion of digital health infrastructure."}'
        cleaned_json = format_clean_signal_summary(json_str)
        self.assertEqual(cleaned_json, "US HealthConnect announced expansion of digital health infrastructure.")

        # Dict input directly
        dict_obj = {"s1": "Point one.", "s2": "Point two."}
        cleaned_obj = format_clean_signal_summary(dict_obj)
        self.assertEqual(cleaned_obj, "Point one. Point two.")

    def test_4_actual_source_url_preserved(self):
        """Test that the real article URL is prioritized and preserved over generic URLs."""
        # A valid article URL is preserved directly
        article_url = "https://simplywall.st/stocks/au/healthcare/asx-m7t/mach7-technologies-shares/news/growth"
        resolved_url = resolve_signal_article_url(article_url)
        self.assertEqual(resolved_url, article_url)

    def test_5_company_website_not_incorrectly_used_when_article_exists(self):
        """Test that job posting / article URL is preserved and not overwritten with company URL."""
        job_url = "https://www.adzuna.com/land/ad/12345678"
        resolved_url = resolve_signal_article_url(job_url)
        self.assertEqual(resolved_url, job_url)
        self.assertNotIn("mach7t.com", resolved_url)

    def test_6_missing_source_url_handled_gracefully(self):
        """Test that empty or invalid URLs resolve safely to None."""
        self.assertIsNone(resolve_signal_article_url(None))
        self.assertIsNone(resolve_signal_article_url(""))
        self.assertIsNone(resolve_signal_article_url("not-a-valid-url"))

    def test_7_prospect_summary_remains_factual_and_natural(self):
        """Test natural, readable, strictly factual prospect qualification summary."""
        contact_data = {
            "first_name": "Mike",
            "last_name": "Emory",
            "title": "Chief Technology Officer",
            "company": "Radiology Associates of North Texas",
            "geography": "Fort Worth, Texas, United States",
            "industry": "medical practice",
            "company_size": "470",
            "prospect_location": "Dallas, TX, USA",
            "work_mode": "Not specified",
            "signal_type": "news_expansion",
        }
        summary = generate_selection_summary(contact_data)
        self.assertIn("Mike is the Chief Technology Officer at Radiology Associates of North Texas", summary)
        self.assertIn("medical practice", summary)
        self.assertIn("Fort Worth, Texas", summary)
        self.assertIn("Dallas, TX, USA", summary)
        self.assertIn("expansion signal", summary)
        self.assertNotIn("Likely", summary)

    def test_8_missing_prospect_location_no_fabrication(self):
        """Test that missing prospect location produces no fabricated location in summary."""
        contact_data = {
            "first_name": "Dan",
            "last_name": "Nysch",
            "title": "CTO / VP Information & Technology",
            "company": "US HealthConnect, Inc.",
            "geography": "Fort Washington, Pennsylvania, United States",
            "industry": "information technology & services",
            "company_size": "130",
            "prospect_location": None,
        }
        summary = generate_selection_summary(contact_data)
        self.assertNotIn("Prospect is located in", summary)

    def test_9_humanize_signal_source(self):
        """Test humanizing internal provider keys."""
        self.assertEqual(humanize_signal_source("google_news_rss"), "Google News")
        self.assertEqual(humanize_signal_source("adzuna"), "Adzuna Job Board")
        self.assertEqual(humanize_signal_source("website_fingerprint"), "Company Website")


if __name__ == "__main__":
    unittest.main()
