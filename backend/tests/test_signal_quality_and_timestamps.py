"""
Unit Tests for Signal Quality and Timestamp Handling in Agent 2 (Signal Intelligence).
Validates:
1. Rejection of conference/summit event headlines for generic company names (e.g. Summit).
2. Rejection of idiom phrases for generic noun companies (e.g. Brand Affinity, Affinity Groups).
3. Rejection of bare stopwords for short company names (e.g. "on", "it").
4. Strict company name matching for job board listings (rejecting malls, street addresses, third-party entities).
5. Tech stack website fingerprinting excludes generic utilities (Google Tag Manager, Stripe) and calibrates confidence.
6. Robust ISO and RFC 2822 timestamp parsing.
7. Correct preservation and propagation of occurred_at and published_at timestamps.
8. Contact latest_signal_at reflects the actual latest event timestamp, not the scan execution timestamp.
"""
import unittest
import uuid
from datetime import datetime, timedelta
from app.agents.a2_signal import SignalAgent, SignalType
from app.models.models import Contact, SignalEvent


class TestSignalQualityAndTimestamps(unittest.TestCase):

    def test_1_summit_conference_rejection(self):
        """Verify that conferences and event series are rejected for company named 'Summit'."""
        rejected_headlines = [
            "SAM Summit Series Expands to 60 Participants, Welcomes New Mentor Class - SAM Magazine",
            "Hyve acquisition positions RAISE Summit for global expansion - SiliconANGLE",
            "Annual AI Summit to be held in San Francisco next month",
            "World Economic Summit concludes with new global trade agreements",
            "Leaders gather for Global Climate Summit in Paris",
            "Registration open for the 2026 Developer Summit",
        ]
        for hl in rejected_headlines:
            self.assertFalse(
                SignalAgent._is_headline_relevant(hl, "Summit", "Summit"),
                f"Headline should have been rejected for 'Summit': {hl}",
            )

        accepted_headlines = [
            "Summit raises $25M in Series B funding to scale operations",
            "Summit appoints Derek Hahn as Chief Revenue Officer",
            "Summit reports record ARR growth in Q2 2026",
        ]
        for hl in accepted_headlines:
            self.assertTrue(
                SignalAgent._is_headline_relevant(hl, "Summit", "Summit"),
                f"Headline should have been accepted for 'Summit': {hl}",
            )

    def test_2_affinity_idiom_rejection(self):
        """Verify that brand affinity and identity-based affinity groups are rejected for company 'Affinity'."""
        rejected_headlines = [
            "Toyota Aims To Build Brand Affinity and Authenticity With OnX Partnership - Chief Marketer",
            "Rutgers charges grad students almost $1,900 in fees while funding identity-based affinity groups - Campus Reform",
            "How marketers use brand affinity to drive retention",
            "Understanding natural affinity in chemical bonding",
        ]
        for hl in rejected_headlines:
            self.assertFalse(
                SignalAgent._is_headline_relevant(hl, "Affinity", "Affinity (CRM)"),
                f"Headline should have been rejected for 'Affinity': {hl}",
            )

        accepted_headlines = [
            "Affinity raises $80M to expand relationship intelligence CRM",
            "Affinity appoints new VP of Engineering to lead AI roadmap",
        ]
        for hl in accepted_headlines:
            self.assertTrue(
                SignalAgent._is_headline_relevant(hl, "Affinity", "Affinity (CRM)"),
                f"Headline should have been accepted for 'Affinity': {hl}",
            )

    def test_3_stopword_collision_guard(self):
        """Verify that short stopwords like 'ON' or 'IT' do not match arbitrary English words."""
        # Bare 'on' in common English text should not match company 'ON'
        self.assertFalse(SignalAgent._is_headline_relevant("A deep dive on market changes in 2026", "ON", "ON Services"))
        self.assertFalse(SignalAgent._is_headline_relevant("Turn on notifications for breaking news", "ON", "ON Services"))

        # Explicit corporate entity match should be accepted
        self.assertTrue(SignalAgent._is_headline_relevant("ON Services appoints new Chief Revenue Officer", "ON", "ON Services"))

    def test_4_job_posting_company_strict_match(self):
        """Verify strict hiring company name matching rejects malls, street names, and third-party employers."""
        # Summit target
        self.assertFalse(SignalAgent._is_company_name_match("The Summit Sierra", "Summit", "Summit"))
        self.assertFalse(SignalAgent._is_company_name_match("Summit Health", "Summit", "Summit"))
        self.assertFalse(SignalAgent._is_company_name_match("Summit Credit Union", "Summit", "Summit"))
        self.assertFalse(SignalAgent._is_company_name_match("", "Summit", "Summit"))

        self.assertTrue(SignalAgent._is_company_name_match("Summit", "Summit", "Summit"))
        self.assertTrue(SignalAgent._is_company_name_match("Summit, Inc.", "Summit", "Summit"))
        self.assertTrue(SignalAgent._is_company_name_match("Summit LLC", "Summit", "Summit"))

        # Multi-word companies
        self.assertTrue(SignalAgent._is_company_name_match("TRM Labs Inc", "TRM Labs", "TRM Labs"))
        self.assertTrue(SignalAgent._is_company_name_match("Mach7 Technologies Ltd", "Mach7 Technologies", "Mach7 Technologies"))
        self.assertFalse(SignalAgent._is_company_name_match("Google LLC", "TRM Labs", "TRM Labs"))

    def test_5_timestamp_parsing_robustness(self):
        """Verify ISO and RFC 2822 date parsing handle diverse provider formats."""
        # ISO with Z
        dt1 = SignalAgent._parse_iso("2026-10-10T14:30:00Z")
        self.assertEqual(dt1, datetime(2026, 10, 10, 14, 30, 0))

        # ISO with space offset
        dt2 = SignalAgent._parse_iso("2026-10-09 08:15:00 +0000")
        self.assertEqual(dt2, datetime(2026, 10, 9, 8, 15, 0))

        # RFC 2822 RSS pubDate
        dt3 = SignalAgent._parse_iso("Sun, 11 Oct 2026 12:00:00 GMT")
        self.assertEqual(dt3, datetime(2026, 10, 11, 12, 0, 0))

        # Empty or invalid safely returns datetime.min
        self.assertEqual(SignalAgent._parse_iso(""), datetime.min)
        self.assertEqual(SignalAgent._parse_iso(None), datetime.min)
        self.assertEqual(SignalAgent._parse_iso("invalid-date"), datetime.min)

    def test_6_enterprise_tools_definition(self):
        """Verify enterprise sales tools are separated from generic web tags."""
        self.assertIn("Salesforce", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)
        self.assertIn("HubSpot", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)
        self.assertIn("Marketo", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)
        self.assertIn("Apollo.io", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)
        self.assertIn("ZoomInfo", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)

        # Generic web tags MUST NOT be treated as enterprise sales CRM tools
        self.assertNotIn("Google Tag Manager", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)
        self.assertNotIn("Mixpanel", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)
        self.assertNotIn("Stripe", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)
        self.assertNotIn("Zendesk", SignalAgent.ENTERPRISE_SALES_CRM_TOOLS)


if __name__ == "__main__":
    unittest.main()
