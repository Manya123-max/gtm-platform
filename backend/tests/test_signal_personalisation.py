import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.models import Contact, SignalEvent, SignalType, OutreachDraft
from app.agents.a3_outreach import OutreachAgent, DraftManager

def create_mock_contact(
    first_name="Jane",
    last_name="Doe",
    company="AlphaTech",
    title="VP of Sales",
    industry="B2B SaaS",
    company_size="50-200",
    icp_score=90
):
    c = Contact()
    c.id = str(uuid4())
    c.first_name = first_name
    c.last_name = last_name
    c.company = company
    c.company_domain = f"{company.lower()}.com"
    c.title = title
    c.industry = industry
    c.company_size = company_size
    c.icp_score = icp_score
    c.email = f"{first_name.lower()}@{company.lower()}.com"
    c.user_id = str(uuid4())
    c.do_not_contact = False
    return c

def create_mock_signal(
    signal_type=SignalType.JOB_POSTING,
    headline="AlphaTech is hiring Sales Engineers",
    raw_data=None,
    occurred_days_ago=10,
    confidence=0.9
):
    s = SignalEvent()
    s.id = str(uuid4())
    s.signal_type = signal_type
    s.confidence = confidence
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    s.occurred_at = now_utc - timedelta(days=occurred_days_ago)
    s.detected_at = now_utc - timedelta(days=occurred_days_ago)
    s.summary = headline
    s.raw_data = raw_data or {
        "headline": headline,
        "description": headline,
        "published_at": s.occurred_at.isoformat(),
        "event_date": s.occurred_at.isoformat(),
    }
    return s

class TestSignalPersonalisation(unittest.TestCase):

    def setUp(self):
        self.agent = OutreachAgent.__new__(OutreachAgent)

    def test_scenario_1_hiring_signal(self):
        contact = create_mock_contact(title="VP of Sales")
        signal = create_mock_signal(
            signal_type=SignalType.JOB_POSTING,
            headline="Hiring 5 Enterprise SDRs",
            raw_data={"roles": ["Enterprise SDR", "Account Executive"], "headline": "Hiring 5 Enterprise SDRs"}
        )
        persona = self.agent._classify_persona(contact.title)
        category = self.agent._categorize_signal(signal)
        details = self.agent._extract_signal_details(signal)

        self.assertEqual(persona, "sales_revenue")
        self.assertEqual(category, "hiring")

        fallback = self.agent._generate_deterministic_message(
            contact=contact,
            signal=signal,
            category=category,
            persona=persona,
            details=details,
            channel="email"
        )
        self.assertTrue("ramp" in fallback["subject"].lower() or "sales" in fallback["subject"].lower())
        self.assertNotIn("{first_name}", fallback["body"])
        self.assertTrue("Enterprise SDR" in fallback["body"] or "open roles" in fallback["body"])
        self.assertIn("sales_revenue", fallback["reasoning"])

    def test_scenario_2_funding_signal(self):
        contact = create_mock_contact(title="Chief Technology Officer")
        signal = create_mock_signal(
            signal_type=SignalType.FUNDING_ROUND,
            headline="AlphaTech Secures $15M Series A",
            raw_data={"funding_stage": "Series A", "amount": "$15M", "headline": "AlphaTech Secures $15M Series A"}
        )
        persona = self.agent._classify_persona(contact.title)
        category = self.agent._categorize_signal(signal)
        details = self.agent._extract_signal_details(signal)

        self.assertEqual(persona, "technical")
        self.assertEqual(category, "funding")

        fallback = self.agent._generate_deterministic_message(
            contact=contact,
            signal=signal,
            category=category,
            persona=persona,
            details=details,
            channel="email"
        )
        self.assertTrue("post-raise" in fallback["subject"].lower() or "scaling" in fallback["subject"].lower() or "data" in fallback["subject"].lower())
        self.assertIn("$15M", fallback["body"])
        self.assertIn("technical", fallback["reasoning"])

    def test_scenario_3_expansion_signal(self):
        contact = create_mock_contact(title="Chief Executive Officer")
        signal = create_mock_signal(
            signal_type=SignalType.NEWS_EXPANSION,
            headline="AlphaTech Expands European Operations with New London Office",
            raw_data={"subtype": "office_expansion", "location": "London", "headline": "AlphaTech Expands European Operations with New London Office"}
        )
        persona = self.agent._classify_persona(contact.title)
        category = self.agent._categorize_signal(signal)
        details = self.agent._extract_signal_details(signal)

        self.assertEqual(persona, "executive")
        self.assertEqual(category, "expansion")

        fallback = self.agent._generate_deterministic_message(
            contact=contact,
            signal=signal,
            category=category,
            persona=persona,
            details=details,
            channel="email"
        )
        self.assertTrue("expansion" in fallback["subject"].lower() or "growth" in fallback["subject"].lower())
        self.assertIn("London", fallback["body"])
        self.assertIn("executive", fallback["reasoning"])

    def test_scenario_4_tech_stack_signal(self):
        contact = create_mock_contact(title="VP of Engineering")
        signal = create_mock_signal(
            signal_type=SignalType.TECH_STACK_OBSERVED,
            headline="Salesforce and Segment Detected on AlphaTech Website",
            raw_data={"technologies": ["Salesforce", "Segment"], "headline": "Salesforce and Segment Detected on AlphaTech Website"}
        )
        persona = self.agent._classify_persona(contact.title)
        category = self.agent._categorize_signal(signal)
        details = self.agent._extract_signal_details(signal)

        self.assertEqual(persona, "technical")
        self.assertEqual(category, "tech_stack")

        fallback = self.agent._generate_deterministic_message(
            contact=contact,
            signal=signal,
            category=category,
            persona=persona,
            details=details,
            channel="email"
        )
        self.assertTrue("salesforce" in fallback["subject"].lower() or "integration" in fallback["subject"].lower() or "optimizing" in fallback["subject"].lower())
        self.assertIn("Salesforce", fallback["body"])
        self.assertIn("technical", fallback["reasoning"])

    def test_scenario_5_signal_recency_selection(self):
        stale_signal = create_mock_signal(
            signal_type=SignalType.JOB_POSTING,
            headline="Old SDR Opening",
            occurred_days_ago=120,
            confidence=0.9
        )
        recent_signal = create_mock_signal(
            signal_type=SignalType.FUNDING_ROUND,
            headline="Fresh Series B",
            occurred_days_ago=5,
            confidence=0.8
        )
        signals = [stale_signal, recent_signal]
        selected = OutreachAgent._select_primary_signal(signals)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, recent_signal.id)

    def test_scenario_6_no_signals_general_icp(self):
        contact = create_mock_contact(title="Head of Sales")
        persona = self.agent._classify_persona(contact.title)
        category = self.agent._categorize_signal(None)
        details = self.agent._extract_signal_details(None)

        self.assertEqual(category, "general_icp")
        fallback = self.agent._generate_deterministic_message(
            contact=contact,
            signal=None,
            category=category,
            persona=persona,
            details=details,
            channel="email"
        )
        self.assertIsNotNone(fallback)
        self.assertTrue("icp profile" in fallback["reasoning"].lower() or "no recent signals" in fallback["reasoning"].lower())
        self.assertNotIn("series", fallback["body"].lower())
        self.assertNotIn("$", fallback["body"])

    def test_scenario_7_two_different_roles_same_company(self):
        contact_cto = create_mock_contact(first_name="Alice", title="CTO", company="OmniCorp")
        contact_cro = create_mock_contact(first_name="Bob", title="VP of Sales", company="OmniCorp")
        signal = create_mock_signal(
            signal_type=SignalType.JOB_POSTING,
            headline="OmniCorp hiring engineers and reps",
            raw_data={"roles": ["Backend Engineer", "Sales Development Rep"]}
        )
        details = self.agent._extract_signal_details(signal)

        msg_cto = self.agent._generate_deterministic_message(
            contact=contact_cto,
            signal=signal,
            category="hiring",
            persona="technical",
            details=details,
            channel="email"
        )
        msg_cro = self.agent._generate_deterministic_message(
            contact=contact_cro,
            signal=signal,
            category="hiring",
            persona="sales_revenue",
            details=details,
            channel="email"
        )

        self.assertNotEqual(msg_cto["subject"], msg_cro["subject"])
        self.assertNotEqual(msg_cto["body"], msg_cro["body"])
        self.assertTrue("engineering" in msg_cto["subject"].lower() or "developer" in msg_cto["body"].lower())
        self.assertTrue("rep" in msg_cro["subject"].lower() or "sales" in msg_cro["subject"].lower() or "quota" in msg_cro["body"].lower())

    def test_traceability_metadata_structure(self):
        traceability = {
            "personalisation_reasoning": "Targeting VP of Sales post-funding",
            "selected_primary_signal": "funding_round",
            "signal_category": "funding",
            "signal_summary_used": "Raised $10M",
            "referenced_signal_ids": ["sig-123"],
        }
        services = ["CRM consulting"]
        meta_payload = {
            "services": services,
            "personalisation_reasoning": traceability.get("personalisation_reasoning"),
            "selected_primary_signal": traceability.get("selected_primary_signal"),
            "signal_category": traceability.get("signal_category"),
            "signal_summary_used": traceability.get("signal_summary_used"),
            "referenced_signal_ids": traceability.get("referenced_signal_ids"),
        }
        draft = OutreachDraft(
            contact_id="c-123",
            user_id="u-123",
            signal_id="sig-123",
            channel="email",
            subject="Scaling sales",
            body="Hi Bob...",
            status="pending",
            approval_state="pending",
            matched_services=meta_payload,
        )
        self.assertEqual(draft.status, "pending")
        self.assertEqual(draft.approval_state, "pending")
        self.assertIsInstance(draft.matched_services, dict)
        self.assertEqual(draft.matched_services["personalisation_reasoning"], "Targeting VP of Sales post-funding")
        self.assertEqual(draft.matched_services["services"], ["CRM consulting"])


if __name__ == "__main__":
    unittest.main()
