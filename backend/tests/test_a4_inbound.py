import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.a4_inbound import InboundAgent, READINESS_DELTAS, REPLY_INTENT_CLASSES
from app.models.models import Contact


@pytest.fixture
def mock_db():
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def sample_contact():
    contact = MagicMock(spec=Contact)
    contact.id = "contact-uuid-123"
    contact.email = "prospect@example.com"
    contact.first_name = "Jane"
    contact.last_name = "Doe"
    contact.company = "Acme Corp"
    contact.do_not_contact = False
    contact.email_valid = True
    contact.readiness_score = 10.0
    return contact


@pytest.mark.asyncio
async def test_reply_intent_classes_coverage():
    """Verify that all 7 intent classes are defined in REPLY_INTENT_CLASSES."""
    expected_classes = [
        "interested",
        "not_interested",
        "out_of_office",
        "bounce",
        "referral",
        "unsubscribe",
        "unknown",
    ]
    assert sorted(REPLY_INTENT_CLASSES) == sorted(expected_classes)


@pytest.mark.asyncio
@pytest.mark.parametrize("intent, expected_delta", [
    ("interested", 25),
    ("referral", 20),
    ("not_interested", -20),
    ("unsubscribe", -100),
    ("out_of_office", 0),
    ("bounce", 0),
    ("unknown", 0),
])
@patch("app.core.celery_app.celery_app.send_task")
async def test_readiness_score_delta_per_intent(
    mock_send_task, intent, expected_delta, mock_db, sample_contact
):
    """Test one test per intent class in REPLY_INTENT_CLASSES verifying the correct readiness_score delta is applied."""
    agent = InboundAgent(mock_db)

    agent._find_contact = AsyncMock(return_value=sample_contact)
    agent._load_thread = AsyncMock(return_value=[])
    agent._classify_intent = AsyncMock(return_value=(intent, 0.95))
    agent._generate_draft = AsyncMock(return_value="AI Draft Response")
    agent._record_thread_event = AsyncMock(return_value=MagicMock(id="thread-123"))
    agent._log_funnel_event = AsyncMock()

    payload = {"from_address": sample_contact.email, "reply_text": "Hello there"}
    initial_score = sample_contact.readiness_score

    result = await agent.handle_reply(payload)

    if intent == "out_of_office":
        assert result["status"] == "auto_handled"
        assert sample_contact.readiness_score == initial_score
    elif intent == "bounce":
        assert result["status"] == "bounced"
        assert sample_contact.readiness_score == initial_score
    elif intent == "unknown":
        assert result["status"] == "unknown_intent"
        assert sample_contact.readiness_score == initial_score
    else:
        expected_score = max(0.0, min(100.0, initial_score + expected_delta))
        assert sample_contact.readiness_score == expected_score


@pytest.mark.asyncio
@patch("app.core.celery_app.celery_app.send_task")
async def test_unsubscribe_intent_sets_do_not_contact(
    mock_send_task, mock_db, sample_contact
):
    """Test that unsubscribe intent sets contact.do_not_contact = True and subtracts unsubscribe delta."""
    agent = InboundAgent(mock_db)

    agent._find_contact = AsyncMock(return_value=sample_contact)
    agent._load_thread = AsyncMock(return_value=[])
    agent._classify_intent = AsyncMock(return_value=("unsubscribe", 0.99))
    agent._record_thread_event = AsyncMock(return_value=MagicMock(id="thread-123"))

    sample_contact.do_not_contact = False
    sample_contact.readiness_score = 50.0

    payload = {"from_address": sample_contact.email, "reply_text": "Unsubscribe me please"}
    result = await agent.handle_reply(payload)

    assert result["status"] == "unsubscribed"
    assert sample_contact.do_not_contact is True
    assert sample_contact.readiness_score == 0.0  # max(0, 50 - 100) = 0


@pytest.mark.asyncio
@pytest.mark.parametrize("intent, should_send_slack", [
    ("interested", True),
    ("referral", True),
    ("out_of_office", False),
    ("bounce", False),
    ("not_interested", False),
    ("unsubscribe", False),
    ("unknown", False),
])
@patch("app.core.config.settings.ENABLE_SLACK_APPROVALS", True)
@patch("app.core.celery_app.celery_app.send_task")
async def test_slack_approval_sent_only_for_interested_and_referral(
    mock_send_task, intent, should_send_slack, mock_db, sample_contact
):
    """Test verifying Slack approval request is only sent for interested/referral intents."""
    agent = InboundAgent(mock_db)

    agent._find_contact = AsyncMock(return_value=sample_contact)
    agent._load_thread = AsyncMock(return_value=[])
    agent._classify_intent = AsyncMock(return_value=(intent, 0.9))
    agent._generate_draft = AsyncMock(return_value="Draft reply")
    agent._record_thread_event = AsyncMock(return_value=MagicMock(id="thread-123"))
    agent._log_funnel_event = AsyncMock()
    agent.slack.send_approval_request = AsyncMock(return_value="123456789.000100")

    payload = {"from_address": sample_contact.email, "reply_text": "Sample reply"}
    await agent.handle_reply(payload)

    if should_send_slack:
        agent.slack.send_approval_request.assert_called_once()
    else:
        agent.slack.send_approval_request.assert_not_called()


@pytest.mark.asyncio
async def test_reject_reply_marks_state(mock_db):
    """Test that reject_reply marks rejected_by and rejected_at and returns True."""
    agent = InboundAgent(mock_db)
    mock_thread = MagicMock(approved_at=None, rejected_at=None, contact_id="contact-123")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_thread
    mock_db.execute.return_value = mock_result
    agent._log_funnel_event = AsyncMock()

    res = await agent.reject_reply("thread-123", "user_slack_id_456")

    assert res is True
    assert mock_thread.rejected_by == "user_slack_id_456"
    assert mock_thread.rejected_at is not None


@pytest.mark.asyncio
@patch("app.core.celery_app.celery_app.send_task")
async def test_handle_timeout_skips_if_rejected(mock_send_task, mock_db):
    """Test that handle_timeout skips auto-send if rejected_at is populated."""
    agent = InboundAgent(mock_db)
    from datetime import datetime
    mock_thread = MagicMock(approved_at=None, rejected_at=datetime.utcnow())
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_thread
    mock_db.execute.return_value = mock_result
    agent._send_reply_via_resend = AsyncMock()

    await agent.handle_timeout("thread-123")

    agent._send_reply_via_resend.assert_not_called()
    mock_send_task.assert_not_called()


@pytest.mark.asyncio
@patch("app.core.config.settings.REQUIRE_HUMAN_APPROVAL", True)
@patch("app.core.celery_app.celery_app.send_task")
async def test_handle_timeout_suppresses_autosend_when_require_human_approval_true(
    mock_send_task, mock_db, sample_contact
):
    """Test that handle_timeout suppresses auto-send when REQUIRE_HUMAN_APPROVAL is True."""
    agent = InboundAgent(mock_db)
    mock_thread = MagicMock(approved_at=None, rejected_at=None, contact_id=sample_contact.id)
    mock_result_thread = MagicMock()
    mock_result_thread.scalar_one_or_none.return_value = mock_thread
    mock_result_contact = MagicMock()
    mock_result_contact.scalar_one_or_none.return_value = sample_contact

    mock_db.execute.side_effect = [mock_result_thread, mock_result_contact]
    agent._send_reply_via_resend = AsyncMock()
    agent._log_funnel_event = AsyncMock()

    await agent.handle_timeout("thread-123")

    agent._send_reply_via_resend.assert_not_called()
    mock_send_task.assert_not_called()
    agent._log_funnel_event.assert_called_once_with(
        "timeout_approval_required", sample_contact.id, {"thread_event_id": "thread-123"}
    )


@pytest.mark.asyncio
@patch("app.main._reject_reply", new_callable=AsyncMock)
@patch("app.core.config.settings.SLACK_SIGNING_SECRET", "test_secret_123")
async def test_slack_webhook_actions_signature_verification(mock_reject_reply):
    """Test /webhook/slack/actions signature verification with valid and invalid signatures."""
    import hmac
    import hashlib
    import time
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    payload_body = "payload=%7B%22actions%22%3A%5B%7B%22action_id%22%3A%22reject_reply%22%2C%22value%22%3A%22t123%22%7D%5D%2C%22user%22%3A%7B%22email%22%3A%22u1%22%7D%7D"
    timestamp = str(int(time.time()))

    sig_base = f"v0:{timestamp}:{payload_body}"
    valid_sig = "v0=" + hmac.new(
        b"test_secret_123", sig_base.encode(), hashlib.sha256
    ).hexdigest()

    headers_valid = {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": valid_sig,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # 1. Valid signature
    res_valid = client.post("/webhook/slack/actions", content=payload_body, headers=headers_valid)
    assert res_valid.status_code == 200
    assert res_valid.json() == {"text": "✓ Action received"}

    # 2. Invalid signature
    headers_invalid = {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": "v0=invalid_signature_hash",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    res_invalid = client.post("/webhook/slack/actions", content=payload_body, headers=headers_invalid)
    assert res_invalid.status_code == 401
    assert res_invalid.json()["detail"] == "Invalid Slack signature"
