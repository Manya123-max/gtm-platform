"""
Standalone Unit tests for Prospect Interest & Engagement Detection Engine (InterestScorer).
"""

import sys
import unittest
import importlib.util
from unittest.mock import MagicMock
from datetime import datetime, timedelta

# Mock LLMService
class MockLLMService:
    async def generate_response(self, system_prompt, user_prompt, max_tokens=150, temperature=0.3):
        return "Prospect is highly engaged and requested a pricing call for next week."

# Load interest_scoring_service directly without package __init__ dependencies
spec = importlib.util.spec_from_file_location("interest_scoring_service", "app/services/interest_scoring_service.py")
service_mod = importlib.util.module_from_spec(spec)
sys.modules["app.services.interest_scoring_service"] = service_mod

# Provide mock LLM inside module before execution
service_mod.LLMService = MockLLMService
service_mod.structlog = MagicMock()

spec.loader.exec_module(service_mod)

InterestScorer = service_mod.InterestScorer
InterestStatus = service_mod.InterestStatus


class TestInterestScorer(unittest.TestCase):

    def setUp(self):
        self.scorer = InterestScorer()

    def test_explicit_rejection_unsubscribe(self):
        contact = {"do_not_contact": False}
        threads = [
            {"direction": "inbound", "intent": "unsubscribe", "occurred_at": datetime.now()}
        ]
        outreaches = [{"sent_at": datetime.now() - timedelta(days=2)}]

        score, status, breakdown = self.scorer.score(contact, threads, outreaches)
        self.assertEqual(score, 0.0)
        self.assertEqual(status, InterestStatus.REJECTED)
        self.assertTrue(breakdown["rejection_override"])

    def test_explicit_rejection_not_interested(self):
        contact = {"do_not_contact": False}
        threads = [
            {"direction": "inbound", "intent": "not_interested", "occurred_at": datetime.now()}
        ]
        outreaches = [{"sent_at": datetime.now() - timedelta(days=2)}]

        score, status, breakdown = self.scorer.score(contact, threads, outreaches)
        self.assertEqual(score, 0.0)
        self.assertEqual(status, InterestStatus.REJECTED)

    def test_high_interest_meeting_request(self):
        now = datetime.now()
        contact = {
            "do_not_contact": False,
            "last_response_at": now - timedelta(hours=5),
            "last_outreach_at": now - timedelta(days=1),
            "response_count": 2,
            "outreach_count": 2,
        }
        threads = [
            {"direction": "inbound", "intent": "interested", "occurred_at": now - timedelta(days=2)},
            {"direction": "inbound", "intent": "meeting_request", "occurred_at": now - timedelta(hours=5)},
        ]
        outreaches = [
            {"sent_at": now - timedelta(days=3)},
            {"sent_at": now - timedelta(days=1)},
        ]

        score, status, breakdown = self.scorer.score(contact, threads, outreaches)
        self.assertGreaterEqual(score, 80.0)
        self.assertEqual(status, InterestStatus.HIGH_INTEREST)
        self.assertEqual(breakdown["intent_score"], 35)
        self.assertEqual(breakdown["recency_score"], 25)
        self.assertEqual(breakdown["frequency_score"], 14)

    def test_inactivity_decay_penalty(self):
        now = datetime.now()
        thirty_two_days_ago = now - timedelta(days=32)
        contact = {
            "do_not_contact": False,
            "last_response_at": thirty_two_days_ago,
            "last_outreach_at": thirty_two_days_ago,
            "response_count": 1,
            "outreach_count": 4,
        }
        threads = [
            {"direction": "inbound", "intent": "technical_question", "occurred_at": thirty_two_days_ago}
        ]
        outreaches = [{"sent_at": thirty_two_days_ago}]

        score, status, breakdown = self.scorer.score(contact, threads, outreaches)
        self.assertLess(score, 50.0)
        self.assertEqual(breakdown["inactivity_decay"], -30)


if __name__ == "__main__":
    unittest.main()
