"""LLM wrapper used by all agents.

Fallback chain (tried in order, skipped if key not set):
  1. Groq      (compound)     — fast & free, hits limits quickly
  2. Gemini    (gemini-1.5-flash)  — Google free tier, generous quota
  3. Mistral   (mistral-small)     — fast OpenAI-compatible, good quality
  4. DeepSeek  (deepseek-chat)     — OpenAI-compatible, cheap & accurate
  5. Claude    (haiku/sonnet)      — paid, always available as last resort

Each provider is tried up to MAX_ATTEMPTS times. On 429 we back off and
try the next provider rather than spinning on the same one.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()

# ── Model IDs ────────────────────────────────────────────────────────────────
HAIKU_MODEL  = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"

GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL   = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent"
MISTRAL_URL  = "https://api.mistral.ai/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

MAX_ATTEMPTS = 2   # per provider before moving to the next


# ── Individual provider callers ───────────────────────────────────────────────

async def _call_openai_compat(
    url: str, api_key: str, model: str,
    system: str, user: str, max_tokens: int,
    force_json: bool = False,
    extra_headers: Optional[Dict] = None,
) -> str:
    """Generic caller for OpenAI-compatible APIs (Groq, Mistral, DeepSeek)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    if force_json:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
]


async def _call_gemini(
    system: str, user: str, max_tokens: int, force_json: bool = False
) -> str:
    """Call Google Gemini via REST with fast multi-model fallback."""
    combined = f"{system}\n\n{user}" if system else user
    if force_json and "Return ONLY valid JSON" not in combined:
        combined += "\n\nReturn ONLY valid JSON. No markdown fences, no preamble."
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": combined}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    if force_json:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    last_err: Optional[Exception] = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url, headers={"Content-Type": "application/json"}, json=payload
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0] and "parts" in candidates[0]["content"]:
                        text = candidates[0]["content"]["parts"][0].get("text", "").strip()
                        if text:
                            return text
                elif resp.status_code in (429, 404, 503):
                    last_err = RuntimeError(f"{model} returned {resp.status_code}")
                    continue
                else:
                    resp.raise_for_status()
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"All Gemini models failed. Last error: {last_err}")


async def _call_anthropic(
    system: str, user: str, model: str, max_tokens: int
) -> str:
    """Call Anthropic Claude directly."""
    headers = {
        "x-api-key":         settings.ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type":      "application/json",
    }
    payload = {
        "model":      model,
        "max_tokens": max_tokens,
        "system":     system,
        "messages":   [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()


# ── Multi-provider fallback ───────────────────────────────────────────────────

def _build_provider_chain(
    force_json: bool = False, claude_model: str = HAIKU_MODEL
) -> List[Tuple[str, Any]]:
    """
    Build the ordered list of (name, async_callable) providers.
    Each callable accepts (system, user, max_tokens) and returns str.
    Providers without a configured key are skipped automatically.
    """
    providers: List[Tuple[str, Any]] = []

    if settings.GROQ_API_KEY:
        providers.append(("Groq-Qwen-27B", lambda s, u, t: _call_openai_compat(
            GROQ_URL, settings.GROQ_API_KEY, "qwen/qwen3.8-27b",
            s, u, t, force_json=force_json,
        )))

    if settings.GEMINI_API_KEY:
        providers.append(("Gemini", lambda s, u, t: _call_gemini(
            s, u, t, force_json=force_json,
        )))

    if settings.GROQ_API_KEY:
        providers.append(("Groq-Compound-Mini", lambda s, u, t: _call_openai_compat(
            GROQ_URL, settings.GROQ_API_KEY, "groq/compound-mini",
            s, u, t, force_json=force_json,
        )))

    if settings.MISTRAL_API_KEY:
        providers.append(("Mistral", lambda s, u, t: _call_openai_compat(
            MISTRAL_URL, settings.MISTRAL_API_KEY, "mistral-small-latest",
            s, u, t, force_json=force_json,
        )))

    if settings.DEEPSEEK_API_KEY:
        providers.append(("DeepSeek", lambda s, u, t: _call_openai_compat(
            DEEPSEEK_URL, settings.DEEPSEEK_API_KEY, "deepseek-chat",
            s, u, t, force_json=force_json,
        )))

    if settings.ANTHROPIC_API_KEY:
        providers.append(("Claude", lambda s, u, t: _call_anthropic(
            s, u, claude_model, t,
        )))

    return providers


async def _call_with_fallback(
    system: str,
    user: str,
    max_tokens: int,
    force_json: bool = False,
    claude_model: str = HAIKU_MODEL,
) -> str:
    """
    Try each provider in order. On 429 or error move to the next.
    Raises RuntimeError if ALL providers fail.
    """
    chain = _build_provider_chain(force_json=force_json, claude_model=claude_model)
    if not chain:
        raise RuntimeError("No LLM providers configured. Set at least one API key.")

    last_err: Optional[Exception] = None
    for name, caller in chain:
        for attempt in range(MAX_ATTEMPTS):
            try:
                result = await caller(system, user, max_tokens)
                logger.info("LLM success", provider=name, tokens=max_tokens)
                await asyncio.sleep(0.1)  # Spacing delay to respect 30 RPM limits on free tiers
                return result
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status == 429:
                    logger.warning("LLM provider rate limited (429), switching immediately to next provider", provider=name)
                    last_err = e
                    break
                else:
                    logger.warning("LLM HTTP error, trying next provider",
                                   provider=name, status=status)
                    last_err = e
                    break  # skip to next provider
            except Exception as e:
                logger.warning("LLM call failed, trying next provider",
                               provider=name, error=str(e))
                last_err = e
                break  # skip to next provider

    raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")


# ── JSON cleaner ──────────────────────────────────────────────────────────────

def _clean_json(content: str) -> Dict[str, Any]:
    """Strip markdown fences, isolate JSON object, and parse JSON."""
    if not content:
        return {}
    s = content.strip()
    if "```json" in s:
        s = s.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in s:
        s = s.split("```", 1)[1].split("```", 1)[0]
    first_brace = s.find("{")
    last_brace = s.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        s = s[first_brace:last_brace+1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Attempt auto-repair on truncated JSON
        if first_brace != -1:
            repaired = s.strip()
            # Trim dangling commas or unclosed quotes
            if repaired.endswith(","):
                repaired = repaired[:-1]
            open_braces = repaired.count("{") - repaired.count("}")
            open_brackets = repaired.count("[") - repaired.count("]")
            if open_braces > 0 or open_brackets > 0:
                if repaired.count('"') % 2 != 0:
                    repaired += '"'
                repaired += ("]" * max(0, open_brackets)) + ("}" * max(0, open_braces))
                try:
                    return json.loads(repaired)
                except Exception:
                    pass

        logger.warning("JSON parse failed, attempting regex extraction fallback", preview=content[:200])
        subject_match = re.search(r'"subject"\s*:\s*"(.*?)"', content, re.DOTALL)
        body_match = re.search(r'"body"\s*:\s*"(.*?)"', content, re.DOTALL)
        if subject_match or body_match:
            res = {}
            if subject_match:
                val = subject_match.group(1)
                val = val.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                res["subject"] = val
            else:
                res["subject"] = ""
            if body_match:
                val = body_match.group(1)
                val = val.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                res["body"] = val
            else:
                res["body"] = ""
            return res
        return {"raw": content}


# ── Public LLM service ────────────────────────────────────────────────────────

class LLMService:
    def __init__(self) -> None:
        has_any = any([
            settings.GROQ_API_KEY,
            settings.GEMINI_API_KEY,
            settings.MISTRAL_API_KEY,
            settings.DEEPSEEK_API_KEY,
            settings.ANTHROPIC_API_KEY,
        ])
        if not has_any:
            raise RuntimeError(
                "No LLM API keys configured. "
                "Set at least one of: GROQ_API_KEY, GEMINI_API_KEY, "
                "MISTRAL_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY in backend/.env"
            )

    async def complete(
        self,
        system: str,
        user: str,
        use_sonnet: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4000,
    ) -> Dict[str, Any]:
        """
        Return a parsed JSON dict.
        Tries all available LLM providers in order until one succeeds.
        Pass use_sonnet=True for tasks needing deeper reasoning (Claude Sonnet).
        """
        json_instruction = (
            "\n\nReturn ONLY valid JSON matching this schema, no markdown fences: "
            + json.dumps(response_format)
            if response_format
            else "\n\nReturn ONLY valid JSON. No markdown fences, no preamble."
        )
        claude_model = SONNET_MODEL if use_sonnet else HAIKU_MODEL
        content = await _call_with_fallback(
            system + json_instruction, user, max_tokens,
            force_json=True, claude_model=claude_model,
        )
        return _clean_json(content)

    async def complete_raw(
        self,
        system_or_prompt: str,
        user_prompt: Optional[str] = None,
        use_haiku: bool = False,
        use_sonnet: bool = False,
        max_tokens: int = 2000,
    ) -> str:
        """
        Return a plain-text completion.
        Tries all available LLM providers in order until one succeeds.
        """
        if user_prompt:
            system = system_or_prompt
            user   = user_prompt
        else:
            system = "You are a helpful GTM AI assistant."
            user   = system_or_prompt

        claude_model = SONNET_MODEL if use_sonnet else HAIKU_MODEL
        return await _call_with_fallback(
            system, user, max_tokens,
            force_json=False, claude_model=claude_model,
        )
