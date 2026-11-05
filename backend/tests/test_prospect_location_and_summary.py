"""
Comprehensive test suite for:
1. Prospect Location Intelligence
2. Prospect Selection / Qualification Summary
Tests Scenarios 1 to 6 per specification.
"""
import unittest
from app.services.prospect_summary import generate_selection_summary
from app.agents.a1_prospect import ProspectAgent


class TestProspectLocationAndSummary(unittest.TestCase):

    def test_scenario_1_location_available(self):
        """TEST 1: Location Available."""
        contact_data = {
            "title": "VP Sales",
            "company": "Enterprise Corp",
            "geography": "United States",
            "industry": "Software",
            "company_size": "250",
            "prospect_location": "New York, United States",
            "work_mode": "Not specified",
            "tech_stack": ["Salesforce", "HubSpot"],
        }
        summary = generate_selection_summary(contact_data)
        self.assertIn("Prospect is located in New York, United States", summary)
        self.assertIn("Enterprise Corp", summary)
        self.assertIn("Software", summary)

    def test_scenario_2_location_missing(self):
        """TEST 2: Location Missing - No hallucination/guessing."""
        contact_data = {
            "title": "Director of Growth",
            "company": "NextGen AI",
            "geography": "San Francisco, CA",  # Company HQ
            "industry": "Artificial Intelligence",
            "company_size": "50",
            "prospect_location": None,  # No person location
            "work_mode": "Not specified",
        }
        summary = generate_selection_summary(contact_data)
        # The summary MUST NOT guess or infer location
        self.assertNotIn("Prospect is located in", summary)
        self.assertNotIn("Likely located in", summary)
        self.assertNotIn("Probably based", summary)
        self.assertNotIn("Appears to be", summary)

    def test_scenario_3_company_and_prospect_locations_differ(self):
        """TEST 3: Company and Prospect Locations Differ."""
        contact_data = {
            "title": "VP Sales",
            "company": "AS Software",
            "geography": "United States",                  # Company HQ
            "prospect_location": "London, United Kingdom", # Prospect Person
            "work_mode": "Not specified",
            "industry": "IT Services",
        }
        # 1. System must keep company location and prospect location distinct
        self.assertEqual(contact_data["geography"], "United States")
        self.assertEqual(contact_data["prospect_location"], "London, United Kingdom")
        self.assertNotEqual(contact_data["geography"], contact_data["prospect_location"])

        # 2. Summary correctly references both separately
        summary = generate_selection_summary(contact_data)
        self.assertTrue("United States-based" in summary or "United States" in summary)
        self.assertIn("Prospect is located in London, United Kingdom.", summary)

    def test_scenario_4_remote_explicit(self):
        """TEST 4: Remote Work Arrangement Explicitly Preserved."""
        person_apollo = {
            "title": "VP of Sales (Remote)",
            "headline": "Sales Leader | Remote",
            "city": "Denver",
            "state": "Colorado",
            "country": "United States",
            "formatted_address": "Denver, CO, USA",
            "organization": {
                "name": "CloudCo",
                "city": "New York",
                "state": "New York",
                "country": "United States",
            }
        }
        parsed = ProspectAgent._parse_apollo_contact(person_apollo)
        self.assertEqual(parsed["work_mode"], "Remote")
        self.assertEqual(parsed["prospect_location"], "Denver, CO, USA")
        self.assertIn("New York", parsed["geography"])

        summary = generate_selection_summary(parsed)
        self.assertIn("Work arrangement: Remote", summary)

    def test_scenario_5_unknown_work_mode(self):
        """TEST 5: Unknown Work Mode (Not Specified)."""
        person_apollo = {
            "title": "Chief Technology Officer",
            "headline": "CTO at HealthTech",
            "city": "Austin",
            "state": "Texas",
            "country": "United States",
            "formatted_address": "Austin, TX, USA",
            "organization": {
                "name": "HealthTech",
                "city": "Austin",
                "state": "Texas",
                "country": "United States",
            }
        }
        parsed = ProspectAgent._parse_apollo_contact(person_apollo)
        # Work mode must NOT be guessed, must be "Not specified"
        self.assertEqual(parsed["work_mode"], "Not specified")
        self.assertEqual(parsed["prospect_location"], "Austin, TX, USA")

        summary = generate_selection_summary(parsed)
        self.assertIn("Prospect is located in Austin, TX, USA.", summary)
        self.assertNotIn("Work arrangement", summary)

    def test_scenario_6_factual_summary_no_hallucination(self):
        """TEST 6: Summary Contains Only Factual Information."""
        minimal_contact = {
            "title": "Head of Partnerships",
            "company": "DataFlow",
        }
        summary = generate_selection_summary(minimal_contact)
        self.assertIn("Head of Partnerships at DataFlow", summary)
        self.assertIn("Matches the selected industry and role criteria.", summary)

        forbidden_phrases = [
            "Likely located in",
            "Probably based in",
            "Appears to be",
            "Likely a decision maker",
            "Likely interested in",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, summary)


if __name__ == "__main__":
    unittest.main()
