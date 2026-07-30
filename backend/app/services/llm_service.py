"""Claude-only LLM wrapper used by all agents.

If Claude is not configured or returns an error, the caller receives that error
and can report a clear reason instead of falling back to another provider.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = structlog.get_logger()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
HAIKU_MODEL = "claude-3-haiku-20240307"
SONNET_MODEL = "claude-3-5-sonnet-latest"


def _anthropic_headers() -> Dict[str, str]:
    return {
        "x-api-key":         settings.ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type":      "application/json",
    }


async def _call_anthropic(
    system: str,
    user: str,
    model: str,
    max_tokens: int,
) -> str:
    payload = {
        "model":      model,
        "max_tokens": max_tokens,
        "system":     system,
        "messages":   [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            ANTHROPIC_URL,
            headers=_anthropic_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


async def _call_groq(
    system: str,
    user: str,
    max_tokens: int,
    force_json: bool = False,
) -> str:
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":      "llama-3.3-70b-versatile",
        "max_tokens": max_tokens,
        "messages":   [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
    }
    if force_json:
        payload["response_format"] = {"type": "json_object"}
        
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            GROQ_URL,
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def _clean_json(content: str, model: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON."""
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed", model=model, preview=content[:200])
        return {"raw": content}


class LLMService:
    def __init__(self) -> None:
        if not getattr(settings, "USE_GROQ", False) and not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to backend/.env and restart the backend."
            )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def complete(
        self,
        system: str,
        user: str,
        use_sonnet: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: int = 1000,
    ) -> Dict[str, Any]:
        """Return a parsed JSON dict.

        Pass use_sonnet=True for tasks that need deeper reasoning
        (content generation, deal analysis, forecast narrative).
        Default is Haiku for cost efficiency.
        """
        if getattr(settings, "USE_GROQ", False):
            content = await _call_groq(system, user, max_tokens, force_json=True)
            logger.info("LLM complete (Groq)", model="llama-3.3-70b-versatile", tokens=max_tokens)
            return _clean_json(content, "llama-3.3-70b-versatile")

        json_instruction = (
            "\n\nReturn ONLY valid JSON matching this schema, no markdown fences: "
            + json.dumps(response_format)
            if response_format
            else "\n\nReturn ONLY valid JSON. No markdown fences, no preamble."
        )
        model   = SONNET_MODEL if use_sonnet else HAIKU_MODEL
        content = await _call_anthropic(
            system + json_instruction, user, model, max_tokens
        )
        logger.info("LLM complete", model=model, tokens=max_tokens)
        return _clean_json(content, model)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def complete_raw(
        self,
        system_or_prompt: str,
        user_prompt: Optional[str] = None,
        use_haiku: bool = False,
        use_sonnet: bool = False,
        max_tokens: int = 2000,
    ) -> str:
        """Return a plain-text completion.

        - use_sonnet=True  → Sonnet 4.6 (email drafting, content generation)
        - use_haiku=True   → Haiku (fast single-line answers)
        - neither          → Haiku (safe default for cost)
        """
        if user_prompt:
            system = system_or_prompt
            user   = user_prompt
        else:
            system = "You are a helpful GTM AI assistant."
            user   = system_or_prompt

        if getattr(settings, "USE_GROQ", False):
            content = await _call_groq(system, user, max_tokens)
            logger.info("LLM raw (Groq)", model="llama-3.3-70b-versatile", tokens=max_tokens)
            return content

        model   = SONNET_MODEL if use_sonnet else HAIKU_MODEL
        content = await _call_anthropic(system, user, model, max_tokens)
        logger.info("LLM raw", model=model, tokens=max_tokens)
        return content