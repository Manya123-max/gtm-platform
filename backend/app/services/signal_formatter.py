"""
Signal Data Quality and Formatting Service.

Provides robust utilities to:
1. Strip HTML tags, unclosed tags, and decode HTML entities from descriptions/summaries.
2. Unpack stringified JSON/Python dictionaries (e.g. {'s1': '...', 's2': '...'})
   into clean, human-readable text without internal keys or braces.
3. Decode Google News RSS tracking URLs to their real canonical article URLs.
4. Cleanly format signal source display labels.
5. Generate deterministic, strictly factual signal explanations when source articles
   only provide a headline or snippet.
"""
from typing import Any, Dict, List, Optional
import html
import json
import ast
import re
import structlog

logger = structlog.get_logger()


def clean_html_text(text: Optional[str]) -> str:
    """
    Safely strips HTML tags, unclosed tags, decodes HTML entities, and normalizes whitespace.
    Never returns raw html tags, hrefs, or unclosed HTML tags.
    """
    if not text:
        return ""
    s = str(text)
    # 1. Strip complete HTML tags
    s = re.sub(r"<[^>]+>", " ", s)
    # 2. Strip unclosed opening tags (e.g., sliced '<a href="...')
    s = re.sub(r"<[a-zA-Z/][^>]*$", "", s)
    # 3. Strip any residual raw href attributes or tags
    s = re.sub(r"<a\s+href=[^\s>]*", "", s, flags=re.IGNORECASE)
    # 4. Unescape HTML entities
    s = html.unescape(s)
    # 5. Clean repeating boilerplate like 'Job Description Job Description'
    s = re.sub(r"^(job description\s*)+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(job description\s*){2,}", "Job Description: ", s, flags=re.IGNORECASE)
    # 6. Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def format_clean_signal_summary(raw: Any) -> str:
    """
    Ensures signal summaries are returned as clean, natural human-readable text.
    Properly unwraps stringified JSON or Python dictionaries (e.g. {'s1': '...', 's2': '...'}).
    Never exposes internal dict keys ('s1', 's2') or braces to the user.
    """
    if not raw:
        return ""

    data = raw
    if isinstance(data, str):
        data_clean = data.strip()
        # Remove code blocks if present
        if data_clean.startswith("```") and data_clean.endswith("```"):
            lines = data_clean.splitlines()
            data_clean = "\n".join(lines[1:-1]).strip()

        # Try to parse if it looks like a dict/JSON
        if (data_clean.startswith("{") and data_clean.endswith("}")) or (data_clean.startswith("[") and data_clean.endswith("]")):
            parsed = False
            try:
                data = json.loads(data_clean)
                parsed = True
            except Exception:
                pass

            if not parsed:
                try:
                    data = ast.literal_eval(data_clean)
                    parsed = True
                except Exception:
                    pass

    if isinstance(data, dict):
        # 1. Check for sentence keys: s1, s2, sentence1, etc.
        sentence_keys = sorted(
            [k for k in data.keys() if re.match(r"^(s\d+|sentence\d+|line\d+|point\d+)$", str(k).lower())]
        )
        if sentence_keys:
            parts = [clean_html_text(str(data[k])) for k in sentence_keys if data[k]]
            return " ".join(parts).strip()

        # 2. Check for common text keys
        for key in ["summary", "signal_summary", "response", "result", "analysis", "content", "text", "message"]:
            if key in data and data[key] and isinstance(data[key], (str, dict, list)):
                return format_clean_signal_summary(data[key])

        # 3. If there are other string values, join all non-meta values
        valid_vals = []
        for k, v in data.items():
            k_lower = str(k).lower()
            if k_lower in ("status", "code", "error", "invalid_encoding_attempt", "model", "provider"):
                continue
            if isinstance(v, str) and v.strip():
                valid_vals.append(clean_html_text(v.strip()))
        if valid_vals:
            return " ".join(valid_vals).strip()
        return ""

    if isinstance(data, list):
        return " ".join(format_clean_signal_summary(item) for item in data if item).strip()

    text_res = clean_html_text(str(data))
    # Strip any accidental leftover dictionary artifacts
    text_res = re.sub(r"^\{['\"]s\d+['\"]\s*:\s*['\"]", "", text_res)
    text_res = re.sub(r"['\"]\s*,\s*['\"]s\d+['\"]\s*:\s*['\"]", " ", text_res)
    text_res = re.sub(r"['\"]\s*\}$", "", text_res)
    return text_res.strip()


def resolve_signal_article_url(url: Optional[str]) -> Optional[str]:
    """
    Decodes Google News RSS tracking URLs (news.google.com/rss/articles/...)
    into the actual destination publisher URL (e.g. simplywall.st, bloomberg.com).
    For other URLs, validates and returns them directly.
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return None

    if "news.google.com/rss/articles/" in url or "news.google.com/articles/" in url:
        try:
            from googlenewsdecoder import gnewsdecoder
            res = gnewsdecoder(url)
            if isinstance(res, dict) and res.get("success") and res.get("decoded_url"):
                decoded = res["decoded_url"].strip()
                if decoded.startswith("http"):
                    return decoded
        except Exception as exc:
            logger.debug("Failed to decode Google News URL; keeping original", url=url[:60], error=str(exc))

    return url


def generate_factual_signal_summary(
    signal_type: str,
    headline: str,
    company: str,
    raw_description: Optional[str] = None
) -> str:
    clean_desc = clean_html_text(raw_description)
    clean_head = clean_html_text(headline).strip("\"' ")
    comp = company.strip() if company else "The company"

    # Reject descriptions that are raw html, urls, fragments, or simply duplicate headline
    if (
        clean_desc
        and len(clean_desc) > 30
        and not clean_desc.startswith("http")
        and "href=" not in clean_desc
        and clean_desc.lower() != clean_head.lower()
    ):
        if clean_desc.startswith("Job Description"):
            cleaned_job = re.sub(r"^(Job Description\s*)+", "", clean_desc).strip()
            if cleaned_job:
                return cleaned_job[:350]
        return clean_desc[:350]

    st = signal_type.lower().replace(" ", "_")
    if "expansion" in st or "news_expansion" in st:
        if clean_head:
            return f"{comp} is showing expansion activity through recent commercial developments: {clean_head}."
        return f"{comp} is showing commercial growth and geographic expansion activity."

    if "funding" in st:
        if clean_head:
            return f"{comp} announced new investment and funding activity: {clean_head}."
        return f"{comp} announced a new funding round to accelerate operations."

    if "hire" in st or "new_hire" in st:
        if clean_head:
            return f"{comp} announced key leadership additions: {clean_head}."
        return f"{comp} is actively expanding leadership and executive personnel."

    if "job" in st or "posting" in st:
        if clean_head:
            return f"Active hiring demand detected for {comp}: {clean_head}."
        return f"Active hiring demand detected for {comp}."

    if "earnings" in st:
        if clean_head:
            return f"{comp} reported financial performance updates: {clean_head}."
        return f"{comp} reported quarterly earnings and financial results."

    if "tech" in st or "stack" in st:
        if clean_head:
            return f"Technical infrastructure update detected: {clean_head}."
        return f"Technical infrastructure update detected for {comp}."

    if clean_head:
        return f"Signal event detected for {comp}: {clean_head}."
    return f"Active buying signal detected for {comp}."


def humanize_signal_source(source: Optional[str]) -> str:
    if not source:
        return "Verified Source"
    s = source.lower().strip()
    mapping = {
        "google_news_rss": "Google News",
        "adzuna": "Adzuna Job Board",
        "website_fingerprint": "Company Website",
        "predictleads": "PredictLeads",
        "currents": "Currents News",
        "newsapi": "News API",
        "newsapi_funding": "News API",
        "newsapi_general": "News API",
        "reddit": "Community Discussions",
    }
    return mapping.get(s, source.replace("_", " ").title())
