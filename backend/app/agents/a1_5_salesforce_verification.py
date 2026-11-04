"""
A1.5 Salesforce Account Verification Agent.

Runs internally between A1 (Prospect Discovery) and A2 (Signal Intelligence).
Determines whether a target company/account has credible evidence of Salesforce adoption.

Pipeline:
  A1 Prospect Discovery → A1.5 Salesforce Account Verification → A2 Signal Intelligence → A3 Outreach

Verification Sources in Priority Order:
  1. Apollo Technographic Data (checks company technology stack for Salesforce)
  2. Official Company Website Technology Detection (Web-to-Lead, Pardot forms, embedded scripts, Experience Cloud)
  3. Company Career Pages & Adzuna (internal Salesforce Administrator, Developer, Architect roles)
  4. Official Announcements, Press Releases & Salesforce Customer Stories
  5. DNS / Email Configuration (optional supporting only)

Evidence Rules:
  - 'verified': ≥1 strong evidence (direct form/script endpoint, customer story, announcement, verified Apollo tech)
                OR ≥2 independent supporting evidence items (internal Salesforce hiring).
  - 'not_verified': checks completed, but no sufficient credible evidence found.
  - 'unable_to_verify': official domain missing, website blocked/inaccessible, or external checks failed.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

import httpx
import structlog
from html.parser import HTMLParser
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.models import (
    Contact, CompanySalesforceVerification, SalesforceVerificationEvidence, FunnelEvent
)

logger = structlog.get_logger(__name__)


# ── SSRF Prevention Constants ───────────────────────────────────────────────

PRIVATE_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918 Class A
    ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918 Class B
    ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918 Class C
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / Cloud metadata (AWS, Azure, GCP)
    ipaddress.ip_network("0.0.0.0/8"),         # Broadcast / current network
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 Unique Local Address
    ipaddress.ip_network("fe80::/10"),         # IPv6 Link-local
]


def is_safe_external_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a URL is safe to fetch:
    - HTTP or HTTPS scheme only
    - Valid host (not localhost, not an internal/private IP, not cloud metadata)
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, "Unsupported protocol scheme"

        host = parsed.hostname
        if not host:
            return False, "Missing hostname"

        clean_host = host.strip().lower()
        if clean_host in ("localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal"):
            return False, "Prohibited local/metadata host"

        # Resolve host to IP addresses and verify none are in private ranges
        addr_info = socket.getaddrinfo(clean_host, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            for priv_net in PRIVATE_IP_NETWORKS:
                if ip_obj in priv_net:
                    return False, f"Resolved IP {ip_str} is within private/prohibited network"

        return True, None
    except Exception as exc:
        return False, f"DNS resolution or URL parsing error: {exc}"


def clean_company_domain(raw_domain: Optional[str]) -> str:
    """Normalize raw domain or website URL to bare domain (e.g. 'company.com')."""
    if not raw_domain:
        return ""
    d = str(raw_domain).strip().lower()
    # Strip protocols
    d = re.sub(r"^https?://", "", d)
    # Strip path, query params, port
    d = d.split("/")[0].split(":")[0].split("?")[0].strip()
    # Remove leading 'www.'
    if d.startswith("www."):
        d = d[4:]
    return d


import unicodedata


def clean_company_name(name: Optional[str]) -> str:
    if not name:
        return ""
    # Normalize unicode (e.g. Vālenz -> Valenz, ™ -> stripped)
    n = unicodedata.normalize('NFKD', str(name))
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.replace("™", "").replace("®", "").replace("©", "")
    # Remove parenthetical details e.g. Acme Health (AH) -> Acme Health
    n = re.sub(r"\(.*?\)", "", n)
    for delim in [" | ", " - ", " — ", " , "]:
        if delim in n:
            n = n.split(delim)[0]
    if ", " in n:
        n = n.split(", ")[0]

    suffixes = [
        "corporation", "corp.", "corp", "incorporated", "inc.", "inc",
        "limited", "ltd.", "ltd", "llc", "l.l.c.", "holdings", "group",
        "technologies", "technology", "tech", "services", "systems", "solutions"
    ]
    name_lower = n.lower().strip()
    for s in suffixes:
        for sep in [" ", "-"]:
            if name_lower.endswith(sep + s):
                n = n[:len(n) - len(sep + s)].strip()
                name_lower = n.lower().strip()
                break
    return n.strip()


class SalesforceHTMLParser(HTMLParser):
    """Safe, standard-library HTML parser for Salesforce fingerprint detection."""
    def __init__(self):
        super().__init__()
        self.forms: List[Dict[str, Any]] = []
        self._curr_form: Optional[Dict[str, Any]] = None
        self.scripts: List[str] = []
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k.lower(): v for k, v in attrs if v is not None}
        if tag == "form":
            self._curr_form = {"action": attr_dict.get("action", ""), "inputs": {}}
            self.forms.append(self._curr_form)
        elif tag == "input" and self._curr_form is not None:
            name = attr_dict.get("name", "").lower()
            val = attr_dict.get("value", "")
            if name:
                self._curr_form["inputs"][name] = val
        elif tag == "script":
            src = attr_dict.get("src")
            if src:
                self.scripts.append(src)
        elif tag == "a":
            href = attr_dict.get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str):
        if tag == "form":
            self._curr_form = None


class SalesforceVerificationAgent:
    """
    A1.5 Salesforce Account Verification Agent.
    Evaluates whether accounts discovered by A1 have verifiable Salesforce CRM adoption.
    """

    # Configurable cache freshness intervals (days)
    CACHE_FRESHNESS_DAYS = 30
    CAREER_FRESHNESS_DAYS = 14

    SALESFORCE_JOB_TITLES = [
        "salesforce administrator",
        "salesforce developer",
        "salesforce architect",
        "salesforce technical lead",
        "salesforce crm manager",
        "salesforce business analyst",
        "salesforce cpq specialist",
        "sales cloud developer",
        "service cloud developer",
        "crm operations manager",
    ]

    CONSULTING_AGENCY_KEYWORDS = [
        "consulting", "implementation partner", "partner", "agency", "staffing",
        "recruitment", "for our client", "client project", "offshore", "services company"
    ]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def verify_prospect_accounts(
        self,
        contacts: List[Union[Contact, Dict[str, Any]]],
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Main pipeline entry point for A1.5.
        Receives contacts discovered by A1, groups them by unique company/account,
        verifies each unique account once, and persists verification and evidence records.
        """
        if not contacts:
            return []

        # Step 1: Deduplicate accounts
        account_groups: Dict[str, Dict[str, Any]] = {}

        for c in contacts:
            if isinstance(c, Contact):
                c_name = c.company or ""
                c_domain = c.company_domain or ""
                c_email = c.email or ""
                c_tech = c.tech_stack or []
                c_apollo_id = c.apollo_id or ""
            else:
                c_name = c.get("company") or ""
                c_domain = c.get("company_domain") or ""
                c_email = c.get("email") or ""
                c_tech = c.get("tech_stack") or []
                c_apollo_id = c.get("apollo_id") or c.get("_org_id") or ""

            clean_domain = clean_company_domain(c_domain)
            if not clean_domain and "@" in c_email:
                clean_domain = clean_company_domain(c_email.split("@")[1])

            comp_key = clean_domain or clean_company_name(c_name).lower()
            if not comp_key:
                continue

            if comp_key not in account_groups:
                account_groups[comp_key] = {
                    "company_name": clean_company_name(c_name) or c_name,
                    "company_domain": clean_domain,
                    "apollo_organization_id": c_apollo_id,
                    "cached_tech_stack": list(c_tech) if isinstance(c_tech, list) else [],
                }
            else:
                # Merge tech stack
                if isinstance(c_tech, list):
                    for t in c_tech:
                        if t not in account_groups[comp_key]["cached_tech_stack"]:
                            account_groups[comp_key]["cached_tech_stack"].append(t)
                if not account_groups[comp_key]["company_domain"] and clean_domain:
                    account_groups[comp_key]["company_domain"] = clean_domain

        logger.info(
            "A1.5: Verifying unique accounts discovered by A1",
            contact_count=len(contacts),
            unique_account_count=len(account_groups),
        )

        results = []
        for key, acc in account_groups.items():
            try:
                res = await self.verify_company(
                    company_name=acc["company_name"],
                    domain=acc["company_domain"],
                    apollo_org_id=acc["apollo_organization_id"],
                    cached_tech_stack=acc["cached_tech_stack"],
                    force_refresh=force_refresh,
                )
                results.append(res)
            except Exception as exc:
                logger.error(
                    "A1.5: Unexpected error verifying company",
                    company=acc["company_name"],
                    domain=acc["company_domain"],
                    error=str(exc),
                )
                results.append({
                    "company_name": acc["company_name"],
                    "company_domain": acc["company_domain"],
                    "verification_status": "unable_to_verify",
                    "verification_summary": f"Verification encountered an unexpected error: {exc}",
                    "evidence": [],
                })

        return results

    async def verify_company(
        self,
        company_name: str,
        domain: Optional[str] = None,
        apollo_org_id: Optional[str] = None,
        cached_tech_stack: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Verify Salesforce adoption for a single unique company/domain.
        Checks cache first, runs methods in priority order, evaluates evidence,
        and saves records to PostgreSQL.
        """
        clean_name = clean_company_name(company_name) or company_name
        clean_dom = clean_company_domain(domain)

        # ── Step 0: Check existing cached record ──
        if not force_refresh:
            cached_ver = await self._get_cached_verification(clean_name, clean_dom)
            if cached_ver:
                age_days = (datetime.utcnow() - cached_ver.last_checked_at).days
                if age_days < self.CACHE_FRESHNESS_DAYS:
                    logger.info(
                        "A1.5: Reusing cached verification result",
                        company=clean_name,
                        domain=clean_dom,
                        status=cached_ver.verification_status,
                        age_days=age_days,
                    )
                    return self._format_verification_result(cached_ver)

        evidence_items: List[Dict[str, Any]] = []
        sources_attempted = []
        source_failures = []

        # ── Method 1: Apollo Technographic Data (Priority: First) ──
        sources_attempted.append("apollo_technographic")
        try:
            apollo_ev = await self._check_apollo_technographic(
                clean_name, clean_dom, apollo_org_id, cached_tech_stack
            )
            if apollo_ev:
                evidence_items.extend(apollo_ev)
        except Exception as exc:
            logger.warning("A1.5: Apollo technographic check failed", error=str(exc))
            source_failures.append("apollo_technographic")

        # ── Method 2: Official Company Website Technology Detection (Priority: High) ──
        if clean_dom:
            sources_attempted.append("website_fingerprint")
            try:
                web_ev = await self._check_company_website(clean_dom, clean_name)
                if web_ev:
                    evidence_items.extend(web_ev)
            except Exception as exc:
                logger.warning("A1.5: Website fingerprint check failed", domain=clean_dom, error=str(exc))
                source_failures.append("website_fingerprint")
        else:
            source_failures.append("website_fingerprint_no_domain")

        # ── Method 3: Company Career Pages and Adzuna (Priority: High) ──
        sources_attempted.append("adzuna_job")
        try:
            job_ev = await self._check_adzuna_salesforce_jobs(clean_name, clean_dom)
            if job_ev:
                evidence_items.extend(job_ev)
        except Exception as exc:
            logger.warning("A1.5: Adzuna career check failed", company=clean_name, error=str(exc))
            source_failures.append("adzuna_job")

        # ── Method 4: Official Announcements & Customer Stories (Priority: High) ──
        sources_attempted.append("official_announcement")
        try:
            news_ev = await self._check_announcements_and_stories(clean_name, clean_dom)
            if news_ev:
                evidence_items.extend(news_ev)
        except Exception as exc:
            logger.warning("A1.5: Announcements check failed", company=clean_name, error=str(exc))
            source_failures.append("official_announcement")

        # ── Step 5: Evidence Evaluation Rules ──
        status, summary = self._evaluate_evidence(
            company_name=clean_name,
            domain=clean_dom,
            evidence=evidence_items,
            sources_attempted=sources_attempted,
            source_failures=source_failures,
        )

        # ── Step 6: Persist in PostgreSQL ──
        record = await self._save_verification(
            company_name=clean_name,
            domain=clean_dom,
            apollo_org_id=apollo_org_id,
            status=status,
            summary=summary,
            evidence_items=evidence_items,
        )

        logger.info(
            "A1.5: Verification complete",
            company=clean_name,
            domain=clean_dom,
            status=status,
            evidence_count=len(evidence_items),
        )

        return self._format_verification_result(record)

    # ------------------------------------------------------------------
    # Method 1: Apollo Technographic Data
    # ------------------------------------------------------------------

    async def _check_apollo_technographic(
        self,
        company_name: str,
        domain: str,
        apollo_org_id: Optional[str],
        cached_tech_stack: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """
        Inspect Apollo technology stack metadata for Salesforce adoption.
        Checks cached tech stack and queries Apollo organization enrich by domain/id.
        Does not fabricate source URLs; records Apollo Technographic Data as source.
        """
        detected_sf: Set[str] = set()

        def _check_tech_item(item: Any):
            if not item:
                return
            if isinstance(item, dict):
                name = item.get("name") or item.get("uid") or ""
            else:
                name = str(item)
            n_lower = name.strip().lower()
            if any(term in n_lower for term in [
                "salesforce", "sales cloud", "service cloud", "marketing cloud",
                "force.com", "pardot", "salesforce crm", "salesforce flow",
                "salesforce platform", "salesforce cpq", "salesforce crm analytics"
            ]):
                clean_t = item.get("name") if isinstance(item, dict) and item.get("name") else name.strip()
                detected_sf.add(clean_t)

        for t in (cached_tech_stack or []):
            _check_tech_item(t)

        # If Salesforce not detected in cached tech stack, query Apollo organization enrich
        if not detected_sf and (domain or apollo_org_id) and settings.APOLLO_API_KEY:
            try:
                headers = {
                    "Cache-Control": "no-cache",
                    "Content-Type": "application/json",
                    "X-Api-Key": settings.APOLLO_API_KEY,
                }
                params: Dict[str, Any] = {}
                if domain:
                    params["domain"] = domain
                elif apollo_org_id:
                    params["id"] = apollo_org_id

                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://api.apollo.io/v1/organizations/enrich",
                        headers=headers,
                        params=params,
                    )
                    if resp.status_code == 200:
                        org_data = resp.json().get("organization") or {}
                        # Check technology_names
                        for t in (org_data.get("technology_names") or []):
                            _check_tech_item(t)
                        # Check current_technologies
                        for t in (org_data.get("current_technologies") or []):
                            _check_tech_item(t)
                        # Check technologies
                        for t in (org_data.get("technologies") or []):
                            _check_tech_item(t)
            except Exception as e:
                logger.debug("A1.5: Apollo org enrich error", error=str(e))

        if not detected_sf:
            return []

        sorted_sf = sorted(list(detected_sf), key=lambda x: (not x.startswith("Salesforce"), x))
        friendly_sf = []
        for s in sorted_sf:
            if "_" in s and any(s.replace("_", " ").lower() in f.lower() for f in sorted_sf if "_" not in f):
                continue
            friendly_sf.append(s)

        sf_display = ", ".join(friendly_sf[:6])
        return [{
            "evidence_type": "apollo_technographic",
            "source_name": "Apollo Technographic Data",
            "evidence_description": (
                f"Apollo technographic profile identifies active Salesforce adoption in {company_name}'s "
                f"technology stack: {sf_display}."
            ),
            "source_url": None,
            "evidence_excerpt": f"Verified technologies: {sf_display}",
            "evidence_date": None,
            "is_strong": True,
            "is_valid": True,
        }]

    # ------------------------------------------------------------------
    # Method 2: Official Company Website Technology Detection
    # ------------------------------------------------------------------

    async def _check_company_website(self, domain: str, company_name: str) -> List[Dict[str, Any]]:
        """
        Lightweight Python inspection of company homepage and contact/about pages.
        Detects Web-to-Lead forms, Salesforce-hosted forms, embedded scripts, and Experience Cloud portals.
        Strictly enforces SSRF protection and timeout bounds.
        """
        evidence: List[Dict[str, Any]] = []
        target_url = f"https://{domain}"

        # 1. SSRF and Domain Safety Check
        is_safe, error_reason = is_safe_external_url(target_url)
        if not is_safe:
            logger.warning("A1.5: Prohibited or unsafe target URL", url=target_url, reason=error_reason)
            return []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        urls_to_scan = [f"https://{domain}", f"https://{domain}/contact", f"https://{domain}/careers"]

        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True, max_redirects=3, verify=False) as client:
                for scan_url in urls_to_scan:
                    try:
                        resp = await client.get(scan_url, headers=headers)
                        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "").lower():
                            html_text = resp.text[:1_500_000]
                            page_ev = self._parse_html_for_salesforce(html_text, str(resp.url), company_name)
                            if page_ev:
                                evidence.extend(page_ev)
                                break
                    except Exception as sub_err:
                        logger.debug("A1.5: Subpath scan skipped", url=scan_url, error=str(sub_err))
        except Exception as exc:
            logger.debug("A1.5: Website HTTP scan failed", domain=domain, error=str(exc))

        return evidence

    def _parse_html_for_salesforce(self, html_text: str, resolved_url: str, company_name: str) -> List[Dict[str, Any]]:
        if not html_text:
            return []

        parser = SalesforceHTMLParser()
        try:
            parser.feed(html_text)
        except Exception as p_err:
            logger.debug("A1.5: HTML parser error", error=str(p_err))

        evidence: List[Dict[str, Any]] = []

        # A. Detect Salesforce Web-to-Lead or Web-to-Case Form Endpoints
        for form in parser.forms:
            action = (form.get("action") or "").strip()
            action_lower = action.lower()

            is_web_to_lead = any(
                endpoint in action_lower for endpoint in [
                    "webto.salesforce.com",
                    "salesforce.com/servlet/servlet.webtolead",
                    "salesforce.com/servlet/servlet.webtocase",
                    "go.pardot.com",
                    "pi.pardot.com",
                ]
            )

            # Check hidden inputs for oid (Salesforce Organization ID)
            inputs = form.get("inputs") or {}
            has_oid = bool(inputs.get("oid"))

            if is_web_to_lead or (has_oid and "salesforce" in action_lower):
                evidence_url = action if action.startswith("http") else urllib.parse.urljoin(resolved_url, action)
                evidence.append({
                    "evidence_type": "website_fingerprint",
                    "source_name": "Official company website",
                    "evidence_description": (
                        f"Salesforce Web-to-Lead endpoint detected in a form associated with {company_name}'s website "
                        f"(action endpoint: {action[:80]})."
                    ),
                    "source_url": evidence_url,
                    "evidence_excerpt": f"Form action: {action[:150]}, inputs: {list(inputs.keys())[:5]}",
                    "evidence_date": None,
                    "is_strong": True,
                    "is_valid": True,
                })
                break

        # B. Detect Salesforce JavaScript Assets and Chat Integrations
        for src in parser.scripts:
            src_clean = src.strip()
            src_lower = src_clean.lower()

            is_sf_script = any(
                sig in src_lower for sig in [
                    "salesforceliveagent.com",
                    "embeddedservice",
                    "embedded_svc",
                    "service.force.com",
                    "c.site.force.com",
                    "web-chat.salesforce.com",
                ]
            )
            if is_sf_script:
                script_full_url = src_clean if src_clean.startswith("http") else urllib.parse.urljoin(resolved_url, src_clean)
                evidence.append({
                    "evidence_type": "website_fingerprint",
                    "source_name": "Official company website",
                    "evidence_description": (
                        f"Salesforce service or chat integration script detected on {company_name}'s website."
                    ),
                    "source_url": script_full_url,
                    "evidence_excerpt": f"Script source: {src_clean[:200]}",
                    "evidence_date": None,
                    "is_strong": True,
                    "is_valid": True,
                })
                break

        # C. Detect Salesforce Experience Cloud / force.com Portals
        for href in parser.links:
            href_clean = href.strip()
            href_lower = href_clean.lower()

            if any(p in href_lower for p in [".my.site.com", ".lightning.force.com", ".secure.force.com"]):
                if not href_lower.startswith("https://salesforce.com") and not href_lower.startswith("https://www.salesforce.com"):
                    evidence.append({
                        "evidence_type": "website_fingerprint",
                        "source_name": "Official company website",
                        "evidence_description": (
                            f"Salesforce Experience Cloud portal link detected on {company_name}'s website."
                        ),
                        "source_url": href_clean,
                        "evidence_excerpt": f"Portal link: {href_clean[:200]}",
                        "evidence_date": None,
                        "is_strong": True,
                        "is_valid": True,
                    })
                    break

        return evidence

    # ------------------------------------------------------------------
    # Method 3: Company Career Pages & Adzuna
    # ------------------------------------------------------------------

    async def _check_adzuna_salesforce_jobs(self, company_name: str, domain: str) -> List[Dict[str, Any]]:
        """
        Query Adzuna job listings for internal Salesforce administrator, developer, or architect roles.
        Distinguishes internal adoption from consulting agency client roles.
        """
        if not settings.ADZUNA_APP_ID or not settings.ADZUNA_API_KEY or not company_name:
            return []

        try:
            target_name = clean_company_name(company_name) or company_name
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params={
                        "app_id": settings.ADZUNA_APP_ID,
                        "app_key": settings.ADZUNA_API_KEY,
                        "what": f'"{target_name}" salesforce',
                        "results_per_page": 10,
                        "sort_by": "date",
                    },
                )
                raw_jobs = []
                if resp.status_code == 200:
                    raw_jobs = resp.json().get("results", [])

                if not raw_jobs:
                    resp2 = await client.get(
                        "https://api.adzuna.com/v1/api/jobs/us/search/1",
                        params={
                            "app_id": settings.ADZUNA_APP_ID,
                            "app_key": settings.ADZUNA_API_KEY,
                            "what": f'"{target_name}"',
                            "results_per_page": 15,
                            "sort_by": "date",
                        },
                    )
                    if resp2.status_code == 200:
                        raw_jobs = resp2.json().get("results", [])

            evidence: List[Dict[str, Any]] = []

            for job in raw_jobs:
                job_comp = (job.get("company", {}).get("display_name") or "").strip()
                if not self._is_company_match(job_comp, company_name):
                    continue

                title = (job.get("title") or "").strip()
                title_lower = title.lower()
                desc = (job.get("description") or "").lower()

                # Check if title matches target internal roles or description mentions Salesforce internal usage
                is_internal_sf_role = any(sf_title in title_lower for sf_title in self.SALESFORCE_JOB_TITLES)
                has_sf_in_title = "salesforce" in title_lower
                has_sf_in_desc = "salesforce" in desc or "sales force" in desc

                if not (is_internal_sf_role or has_sf_in_title or has_sf_in_desc):
                    continue

                # Exclude staffing/consulting agency client postings
                is_consulting = any(kw in desc for kw in self.CONSULTING_AGENCY_KEYWORDS)
                if is_consulting:
                    continue

                job_url = job.get("redirect_url") or job.get("url")
                created_str = job.get("created")
                posting_dt = None
                if created_str:
                    try:
                        posting_dt = datetime.fromisoformat(str(created_str).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
                    except Exception:
                        posting_dt = None

                evidence.append({
                    "evidence_type": "adzuna_job",
                    "source_name": "Adzuna Job Posting",
                    "evidence_description": (
                        f"Active job posting for internal '{title}' detected for {company_name}."
                    ),
                    "source_url": job_url,
                    "evidence_excerpt": job.get("description", "")[:250],
                    "evidence_date": posting_dt,
                    "is_strong": False,  # Job postings are Supporting evidence per spec
                    "is_valid": True,
                })
                break  # 1 confirmed job evidence per company is sufficient

            return evidence
        except Exception as exc:
            logger.debug("A1.5: Adzuna check failed", company=company_name, error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Method 4: Official Announcements & Customer Stories
    # ------------------------------------------------------------------

    async def _check_announcements_and_stories(self, company_name: str, domain: str) -> List[Dict[str, Any]]:
        """
        Scan Google News RSS for explicit Salesforce implementation announcements or customer stories.
        Rejects generic vendor or partner press releases.
        """
        if not company_name:
            return []

        clean_name = clean_company_name(company_name) or company_name
        try:
            query = f'"{clean_name}" ("Salesforce" OR "Salesforce CRM" OR "Sales Cloud" OR "Service Cloud")'
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                resp = await client.get(
                    "https://news.google.com/rss/search",
                    params={
                        "q": query,
                        "hl": "en-US",
                        "gl": "US",
                        "ceid": "US:en",
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                if resp.status_code != 200:
                    return []

            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            items = root.findall(".//item")
            evidence: List[Dict[str, Any]] = []

            for item in items[:5]:
                title_elem = item.find("title")
                title = title_elem.text if title_elem is not None and title_elem.text else ""
                if not self._is_announcement_relevant(title, clean_name):
                    continue

                link_elem = item.find("link")
                link = link_elem.text if link_elem is not None and link_elem.text else ""

                desc_elem = item.find("description")
                raw_desc = desc_elem.text if desc_elem is not None and desc_elem.text else ""
                clean_desc = re.sub(r"<[^>]+>", "", raw_desc).strip()

                evidence.append({
                    "evidence_type": "official_announcement",
                    "source_name": "Official announcement / Press release",
                    "evidence_description": f"Public announcement describes Salesforce implementation: {title}",
                    "source_url": link,
                    "evidence_excerpt": clean_desc[:250],
                    "evidence_date": None,
                    "is_strong": True,
                    "is_valid": True,
                })
                break

            return evidence
        except Exception as exc:
            logger.debug("A1.5: News/announcements check failed", company=company_name, error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Evidence Evaluation Logic
    # ------------------------------------------------------------------

    def _evaluate_evidence(
        self,
        company_name: str,
        domain: str,
        evidence: List[Dict[str, Any]],
        sources_attempted: List[str],
        source_failures: List[str],
    ) -> Tuple[str, str]:
        """
        Evaluate evidence according to Phase 2.5 Evidence Evaluation Rules:
        - Strong evidence: Web-to-Lead endpoint, Experience Cloud, announcement, customer story, Apollo tech.
        - Supporting evidence: Internal Salesforce Administrator / Developer job posting.
        - Weak / insufficient: generic mentions, consulting company hiring developers for clients.
        """
        # Deduplicate evidence by source_url and evidence_type
        deduped: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()

        for ev in evidence:
            url_part = (ev.get("source_url") or "").strip().lower()
            key = f"{ev['evidence_type']}_{url_part}_{ev.get('source_name')}"
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(ev)

        strong_count = sum(1 for e in deduped if e.get("is_strong", False) and e.get("is_valid", True))
        supporting_count = sum(1 for e in deduped if not e.get("is_strong", False) and e.get("is_valid", True))

        if strong_count >= 1:
            status = "verified"
            first_strong = next(e for e in deduped if e.get("is_strong", False))
            summary = (
                f"Salesforce adoption verified for {company_name}. Direct evidence: "
                f"{first_strong['evidence_description']}"
            )
        elif supporting_count >= 2:
            status = "verified"
            summary = (
                f"Salesforce adoption verified for {company_name} based on multiple independent "
                f"internal Salesforce operational and engineering indicators."
            )
        elif not domain and len(deduped) == 0:
            status = "unable_to_verify"
            summary = (
                f"Verification could not be completed for {company_name}. Official company domain was missing "
                f"and external sources were inaccessible."
            )
        elif len(source_failures) == len(sources_attempted) and len(deduped) == 0:
            status = "unable_to_verify"
            summary = (
                f"Verification could not be completed for {company_name}. One or more required sources were unavailable "
                f"or the target website blocked requests."
            )
        else:
            status = "not_verified"
            summary = (
                f"No reliable Salesforce adoption evidence was found for {company_name} during the verification process. "
                f"This does not establish that the company does not use Salesforce."
            )

        return status, summary

    # ------------------------------------------------------------------
    # Database Persistence & Helpers
    # ------------------------------------------------------------------

    async def _get_cached_verification(
        self, company_name: str, domain: str
    ) -> Optional[CompanySalesforceVerification]:
        stmt = select(CompanySalesforceVerification).options(
            selectinload(CompanySalesforceVerification.evidence_items)
        )
        if domain:
            stmt = stmt.where(CompanySalesforceVerification.company_domain == domain)
        else:
            stmt = stmt.where(func.lower(CompanySalesforceVerification.company_name) == company_name.lower())

        stmt = stmt.order_by(CompanySalesforceVerification.last_checked_at.desc()).limit(1)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def _save_verification(
        self,
        company_name: str,
        domain: str,
        apollo_org_id: Optional[str],
        status: str,
        summary: str,
        evidence_items: List[Dict[str, Any]],
    ) -> CompanySalesforceVerification:
        # Check if record already exists
        existing = await self._get_cached_verification(company_name, domain)
        now = datetime.utcnow()

        if existing:
            existing.company_name = company_name
            if domain:
                existing.company_domain = domain
            if apollo_org_id:
                existing.apollo_organization_id = apollo_org_id
            existing.verification_status = status
            existing.verification_summary = summary
            existing.last_checked_at = now
            existing.updated_at = now
            ver_record = existing
            # Clear old evidence records in DB so re-verification replaces stale evidence
            from sqlalchemy import delete as sql_delete
            await self.db.execute(
                sql_delete(SalesforceVerificationEvidence).where(
                    SalesforceVerificationEvidence.verification_id == ver_record.id
                )
            )
            await self.db.flush()
        else:
            ver_record = CompanySalesforceVerification(
                id=str(uuid.uuid4()),
                company_name=company_name,
                company_domain=domain or None,
                apollo_organization_id=apollo_org_id or None,
                verification_status=status,
                verification_summary=summary,
                last_checked_at=now,
                created_at=now,
                updated_at=now,
            )
            self.db.add(ver_record)
            await self.db.flush()

        # Insert new evidence items
        for ev in evidence_items:
            ev_id = str(uuid.uuid4())
            ev_record = SalesforceVerificationEvidence(
                id=ev_id,
                verification_id=ver_record.id,
                evidence_type=ev["evidence_type"],
                evidence_description=ev["evidence_description"],
                source_name=ev["source_name"],
                source_url=ev.get("source_url"),
                evidence_excerpt=ev.get("evidence_excerpt"),
                evidence_date=ev.get("evidence_date"),
                checked_at=now,
                is_valid=ev.get("is_valid", True),
                created_at=now,
                updated_at=now,
            )
            self.db.add(ev_record)

        await self.db.commit()
        # Eagerly load relationship so evidence_items is immediately accessible in async session
        refreshed_stmt = select(CompanySalesforceVerification).options(
            selectinload(CompanySalesforceVerification.evidence_items)
        ).where(CompanySalesforceVerification.id == ver_record.id).execution_options(populate_existing=True)
        refreshed_res = await self.db.execute(refreshed_stmt)
        return refreshed_res.scalar_one()

    def _format_verification_result(self, record: CompanySalesforceVerification) -> Dict[str, Any]:
        evidence = []
        items = getattr(record, "evidence_items", None) or []
        for e in items:
            evidence.append({
                "id": str(e.id),
                "evidence_type": e.evidence_type,
                "source_name": e.source_name,
                "evidence_description": e.evidence_description,
                "source_url": e.source_url,
                "evidence_excerpt": e.evidence_excerpt,
                "evidence_date": e.evidence_date.isoformat() if e.evidence_date else None,
                "checked_at": e.checked_at.isoformat() if e.checked_at else None,
                "is_valid": e.is_valid,
            })

        return {
            "company_id": str(record.id),
            "company_name": record.company_name,
            "company_domain": record.company_domain,
            "apollo_organization_id": record.apollo_organization_id,
            "verification_status": record.verification_status,
            "verification_summary": record.verification_summary,
            "last_checked_at": record.last_checked_at.isoformat() if record.last_checked_at else None,
            "evidence": evidence,
        }

    @staticmethod
    def _is_company_match(job_comp: str, target_comp: str) -> bool:
        if not job_comp or not target_comp:
            return False
        clean_j = clean_company_name(job_comp).lower()
        clean_t = clean_company_name(target_comp).lower()
        return clean_j == clean_t or clean_t in clean_j or clean_j in clean_t

    @staticmethod
    def _is_announcement_relevant(headline: str, company: str) -> bool:
        if not headline or not company:
            return False
        h_lower = headline.lower()
        c_lower = clean_company_name(company).lower()
        if c_lower not in h_lower:
            return False
        # Reject generic consulting partner announcements
        if any(w in h_lower for w in ["becomes salesforce partner", "named salesforce partner", "salesforce consulting partner"]):
            return False
        return True
