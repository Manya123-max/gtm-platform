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
from datetime import datetime, timezone
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

    if "tech_stack_observed" in st or "observed" in st:
        if clean_head:
            return f"Verified enterprise technology usage detected: {clean_head}."
        return f"Verified enterprise technology usage detected for {comp}."

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
        "predictleads": "PredictLeads",
        "currents": "Currents News",
        "newsapi": "News API",
        "newsapi_funding": "News API",
        "newsapi_general": "News API",
        "apify_reddit": "Reddit Community Discussions",
        "reddit": "Community Discussions",
        "website_fingerprint": "Website Fingerprint",
    }
    return mapping.get(s, source.replace("_", " ").title())

def enrich_signal_metadata(
    sig_type: str,
    raw_data: Optional[Dict[str, Any]],
    company: str,
    summary: Optional[str] = None
) -> Dict[str, Any]:
    """
    Enriches raw_data with structured, signal-specific metadata fields and a strictly
    signal-grounded company_context.
    Never injects prospect profile information, candidate experience, or ICP matching summaries.
    """
    raw = dict(raw_data or {})
    st = str(sig_type or "").lower().strip()
    headline = str(raw.get("headline") or raw.get("title") or summary or "").strip()
    description = str(raw.get("description") or summary or "").strip()
    text = f"{headline} {description}".strip()
    comp = (company or "The company").strip()

    if "job" in st and "hire" not in st:
        if not raw.get("job_title"):
            raw["job_title"] = headline.replace("Leadership Hiring Requisition:", "").replace("Leadership Requisition:", "").strip()
        if not raw.get("department"):
            t_low = text.lower()
            if any(k in t_low for k in ["clinical", "therapist", "healthcare", "medical", "physician", "nurse", "patient"]):
                raw["department"] = "Healthcare & Clinical"
            elif any(k in t_low for k in ["engineer", "software", "developer", "devops", "architect", "data science"]):
                raw["department"] = "Engineering & IT"
            elif any(k in t_low for k in ["account", "finance", "audit", "cfo", "tax", "billing"]):
                raw["department"] = "Finance & Accounting"
            elif any(k in t_low for k in ["sales", "bdr", "sdr", "account exec", "revenue", "commercial"]):
                raw["department"] = "Sales & Revenue"
            elif any(k in t_low for k in ["tech", "information technology"]):
                raw["department"] = "Engineering & IT"
            elif any(k in t_low for k in ["market", "growth", "content", "seo", "demand"]):
                raw["department"] = "Marketing & Growth"
            elif any(k in t_low for k in ["hr", "people", "talent", "recruit"]):
                raw["department"] = "People & HR"
            else:
                raw["department"] = "General Operations"
        if not raw.get("employment_type"):
            raw["employment_type"] = "Full-time"
        if not raw.get("company_context"):
            raw["company_context"] = f"{comp} published an active vacancy for {raw.get('job_title') or headline}. The position is listed within the {raw.get('department')} department to support team expansion."

    elif "hire" in st or "new_hire" in st:
        if not raw.get("new_designation"):
            desig_m = re.search(r'\b(cfo|cto|ceo|cro|coo|chief\s+financial\s+officer|chief\s+technology\s+officer|chief\s+revenue\s+officer|chief\s+executive\s+officer|vp\s+of\s+[A-Za-z\s]+|vice\s+president\s+[A-Za-z\s]+|director\s+of\s+[A-Za-z\s]+|head\s+of\s+[A-Za-z\s]+)\b', text, re.I)
            raw["new_designation"] = desig_m.group(1).title() if desig_m else "Executive Leadership"
        if not raw.get("appointed_person"):
            name_m = re.search(r'(?:names|appoints|welcomes|hires)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+(?:as|to|after)', text)
            if name_m:
                raw["appointed_person"] = name_m.group(1).strip()
        if not raw.get("department"):
            desig_lower = str(raw.get("new_designation", "")).lower()
            if "cfo" in desig_lower or "financial" in desig_lower:
                raw["department"] = "Finance & Accounting"
            elif "cto" in desig_lower or "technology" in desig_lower or "engineering" in desig_lower:
                raw["department"] = "Technology & Engineering"
            elif "cro" in desig_lower or "sales" in desig_lower or "revenue" in desig_lower:
                raw["department"] = "Sales & Revenue"
            elif "cmo" in desig_lower or "marketing" in desig_lower:
                raw["department"] = "Marketing & Growth"
            else:
                raw["department"] = "Executive Leadership"
        if not raw.get("company_context"):
            person_str = f" ({raw.get('appointed_person')})" if raw.get("appointed_person") else ""
            raw["company_context"] = f"{comp} announced the appointment of {raw.get('new_designation')}{person_str}. This executive appointment strengthens strategic direction and operations."

    elif "funding" in st:
        if not raw.get("funding_stage"):
            stage_m = re.search(r'\b(seed|series\s+[a-f]|venture\s+round|growth\s+equity|ipo|debt\s+financing)\b', text, re.I)
            raw["funding_stage"] = stage_m.group(1).title() if stage_m else "Growth"
        if not raw.get("amount"):
            amt_m = re.search(r'(\$\s*\d+(?:\.\d+)?\s*(?:billion|million|b|m|k))\b', text, re.I)
            if amt_m:
                raw["amount"] = amt_m.group(1).strip()
        if not raw.get("lead_investor"):
            inv_m = re.search(r'(?:led by|from)\s+([A-Z][A-Za-z0-9\s,&]+?)(?:\s+to|\s+along|\.|\,|$)', text)
            if inv_m and len(inv_m.group(1).strip()) < 50:
                raw["lead_investor"] = inv_m.group(1).strip()
        if not raw.get("company_context"):
            ctx = f"{comp} completed a {raw.get('funding_stage')} financing round"
            if raw.get("amount"):
                ctx += f" of {raw['amount']}"
            if raw.get("lead_investor"):
                ctx += f" led by {raw['lead_investor']}"
            ctx += " to support operations and commercial expansion."
            raw["company_context"] = ctx

    elif "expansion" in st or "news" in st:
        if not raw.get("subtype"):
            t_low = text.lower()
            if "partnership" in t_low or "collaborat" in t_low:
                raw["subtype"] = "New Partnership"
            elif "acqui" in t_low or "merger" in t_low:
                raw["subtype"] = "Merger or Acquisition"
            elif "office" in t_low:
                raw["subtype"] = "Office Expansion"
            elif "launch" in t_low or "unveil" in t_low:
                raw["subtype"] = "Product Launch"
            elif "geographic" in t_low:
                raw["subtype"] = "Geographic Expansion"
            else:
                raw["subtype"] = "Business Expansion"
        if not raw.get("company_context"):
            raw["company_context"] = f"{comp} announced commercial development: {headline}. This event represents active market expansion and business growth."

    elif "earnings" in st:
        if not raw.get("reporting_period"):
            period_m = re.search(r'\b(Q[1-4]\s*(?:20\d\d)?|FY\s*(?:20\d\d)?|fourth\s+quarter|third\s+quarter|second\s+quarter|first\s+quarter)\b', text, re.I)
            raw["reporting_period"] = period_m.group(1).upper() if period_m else "Quarterly"
        if not raw.get("company_context"):
            raw["company_context"] = f"{comp} reported financial updates and operational performance for {raw.get('reporting_period')}."

    elif "social" in st or "reddit" in st:
        if not raw.get("platform"):
            raw["platform"] = "Reddit"
        if not raw.get("company_context"):
            sub_str = f" on {raw.get('subreddit')}" if raw.get("subreddit") else ""
            raw["company_context"] = f"Public community discussions concerning {comp} were identified{sub_str} regarding product usage and technical workflows."

    elif "tech" in st or "stack" in st:
        tech_list = raw.get("technologies") or []
        tech_str = ", ".join(tech_list) if tech_list else "sales/CRM tools"
        if not raw.get("detection_method"):
            raw["detection_method"] = "HTML Inspection" if raw.get("is_html_inspection") else "Resource Detection"
        if not raw.get("company_context"):
            if "change" in st:
                raw["company_context"] = f"Technology stack update: {tech_str} was newly detected on {comp}'s website compared to previous baseline scan."
            else:
                raw["company_context"] = f"Direct website inspection observed active {tech_str} usage on {comp}'s domain. This reflects verified active usage, not a newly confirmed adoption event."

    # Date fields and freshness classification
    event_date_str = raw.get("event_date") or raw.get("funding_date") or raw.get("announced_on") or raw.get("appointment_date")
    published_at_str = raw.get("published_at") or raw.get("created")
    if event_date_str and not raw.get("event_date"):
        raw["event_date"] = event_date_str
    if published_at_str and not raw.get("published_at"):
        raw["published_at"] = published_at_str

    target_date_str = raw.get("event_date") or raw.get("published_at")
    if target_date_str:
        try:
            cleaned_d = str(target_date_str).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned_d)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            diff_days = (datetime.utcnow() - dt).days
            if diff_days <= 30:
                raw["freshness_label"] = "Recent (<30d)"
                raw["is_stale"] = False
                raw["is_recent"] = True
            elif diff_days <= 90:
                raw["freshness_label"] = f"{diff_days}d ago"
                raw["is_stale"] = False
                raw["is_recent"] = False
            else:
                raw["freshness_label"] = f"Historical ({diff_days}d ago)"
                raw["is_stale"] = True
                raw["is_recent"] = False
        except Exception:
            raw["freshness_label"] = "Date unknown"
            raw["is_stale"] = False
            raw["is_recent"] = False
    else:
        raw["freshness_label"] = "Date unknown"
        raw["is_stale"] = False
        raw["is_recent"] = False

    return raw
