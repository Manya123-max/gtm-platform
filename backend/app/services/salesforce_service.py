"""
Salesforce CRM Service — Sole CRM Source of Truth for GTM Platform.
Interacts with Salesforce REST API (v60.0).
Provides Opportunity synchronization, Contact resolution, and Activity/Task logging.
"""
from typing import Dict, Any, List, Optional
import httpx
import structlog
from app.core.config import settings

logger = structlog.get_logger(__name__)


# Standard Salesforce Opportunity Stage -> GTM DealStage mapping
SALESFORCE_STAGE_MAP = {
    # Standard Salesforce B2B pipeline stages
    "Prospecting": "prospecting",
    "Qualification": "discovery",
    "Needs Analysis": "discovery",
    "Value Proposition": "demo",
    "Id. Decision Makers": "demo",
    "Perception Analysis": "demo",
    "Proposal/Price Quote": "proposal",
    "Negotiation/Review": "negotiation",
    "Closed Won": "closed_won",
    "Closed Lost": "closed_lost",
}


class SalesforceService:
    """
    Salesforce CRM REST API service (v60.0).
    Manages Opportunity synchronization, Account/Contact queries, and Activity logging.
    """

    def __init__(self):
        self.instance_url = (getattr(settings, "SALESFORCE_INSTANCE_URL", None) or "").rstrip("/")
        self.access_token = getattr(settings, "SALESFORCE_ACCESS_TOKEN", None) or ""
        self.api_version = getattr(settings, "SALESFORCE_API_VERSION", "v60.0")

    @property
    def is_configured(self) -> bool:
        return bool(self.instance_url and self.access_token)

    @property
    def base_url(self) -> str:
        return f"{self.instance_url}/services/data/{self.api_version}"

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def sync_opportunities(self) -> List[Dict[str, Any]]:
        """
        Pull active opportunities from Salesforce for A5/A7 deal intelligence.
        SOQL queries open opportunities and active pipeline deals.
        """
        if not self.is_configured:
            logger.info("SalesforceService: No SALESFORCE_INSTANCE_URL or SALESFORCE_ACCESS_TOKEN configured. Skipping sync.")
            return []

        soql = (
            "SELECT Id, Name, Amount, StageName, CloseDate, Probability, "
            "Owner.Email, Owner.Name, ContactId, AccountId, Account.Name "
            "FROM Opportunity "
            "WHERE IsClosed = false OR StageName != 'Closed Lost' "
            "LIMIT 200"
        )
        url = f"{self.base_url}/query"

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.get(url, headers=self.headers, params={"q": soql})
                resp.raise_for_status()
                data = resp.json()
                records = data.get("records", [])
                logger.info("SalesforceService: Successfully queried opportunities", count=len(records))
                return records
        except httpx.HTTPStatusError as e:
            logger.error(
                "SalesforceService: HTTP error querying opportunities",
                status_code=e.response.status_code,
                error=e.response.text,
            )
            return []
        except Exception as e:
            logger.error("SalesforceService: Unexpected error querying opportunities", error=str(e))
            return []

    async def log_activity(
        self,
        opportunity_id: Optional[str],
        subject: str,
        body: str,
    ) -> bool:
        """
        Log an activity / task note in Salesforce associated with an Opportunity.
        """
        if not self.is_configured or not opportunity_id:
            return False

        url = f"{self.base_url}/sobjects/Task"
        payload = {
            "WhatId": opportunity_id,
            "Subject": subject,
            "Description": body,
            "Status": "Completed",
            "Priority": "Normal",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, headers=self.headers, json=payload)
                resp.raise_for_status()
                task_id = resp.json().get("id")
                logger.info("SalesforceService: Logged activity task to Opportunity", task_id=task_id, opportunity_id=opportunity_id)
                return True
        except Exception as e:
            logger.error("SalesforceService: Failed to log activity to Opportunity", opportunity_id=opportunity_id, error=str(e))
            return False

    async def get_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Look up a Contact in Salesforce by email address.
        """
        if not self.is_configured or not email:
            return None

        # Sanitize single quotes in email for SOQL
        clean_email = email.replace("'", "\\'")
        soql = (
            f"SELECT Id, FirstName, LastName, Email, Title, AccountId, Account.Name "
            f"FROM Contact WHERE Email = '{clean_email}' LIMIT 1"
        )
        url = f"{self.base_url}/query"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self.headers, params={"q": soql})
                resp.raise_for_status()
                records = resp.json().get("records", [])
                return records[0] if records else None
        except Exception as e:
            logger.warning("SalesforceService: Error querying contact by email", email=email, error=str(e))
            return None


    async def get_lead_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Look up a Lead in Salesforce by email address."""
        if not self.is_configured or not email:
            return None
        clean_email = email.replace("'", "\\'")
        soql = (
            f"SELECT Id, FirstName, LastName, Email, Title, Company, IsConverted "
            f"FROM Lead WHERE Email = '{clean_email}' AND IsConverted = false LIMIT 1"
        )
        url = f"{self.base_url}/query"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self.headers, params={"q": soql})
                resp.raise_for_status()
                records = resp.json().get("records", [])
                return records[0] if records else None
        except Exception as e:
            logger.warning("SalesforceService: Error querying lead by email", email=email, error=str(e))
            return None

    async def sync_contact_to_salesforce(self, contact_data: Dict[str, Any]) -> Optional[str]:
        """
        Synchronize an enriched prospect/contact to Salesforce (Sole CRM source of truth).
        1. If salesforce_contact_id exists or record exists in Salesforce (Contact or Lead), updates it.
        2. Otherwise, creates a new Lead in Salesforce.
        3. Prevents duplicate Salesforce records via email SOQL lookup before creation.
        4. Returns the Salesforce record ID (e.g. 00Q... or 003...).
        5. Fails gracefully with warning logging if Salesforce is unavailable or unconfigured.
        """
        if not self.is_configured:
            logger.info("SalesforceService: Not configured. Skipping contact sync.")
            return None

        email = (contact_data.get("email") or "").strip()
        if not email:
            return None

        sf_id = contact_data.get("salesforce_contact_id")
        first_name = (contact_data.get("first_name") or "").strip()
        last_name = (contact_data.get("last_name") or "").strip() or (contact_data.get("company") or "Unknown").strip()
        company = (contact_data.get("company") or "Unknown Company").strip()
        title = (contact_data.get("title") or "").strip()
        city = (contact_data.get("prospect_location") or contact_data.get("geography") or "").strip()
        summary = (contact_data.get("selection_summary") or "").strip()
        icp_score = contact_data.get("icp_score")
        description_parts = []
        if summary:
            description_parts.append(summary)
        if icp_score is not None:
            description_parts.append(f"ICP Score: {icp_score}")
        description = "\n".join(description_parts) or "Enriched by GTM A1 Prospect Intelligence"

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # 1. Update existing record if sf_id is provided
                if sf_id:
                    sobject = "Lead" if sf_id.startswith("00Q") else "Contact"
                    update_url = f"{self.base_url}/sobjects/{sobject}/{sf_id}"
                    payload = {
                        "FirstName": first_name or None,
                        "LastName": last_name,
                        "Title": title or None,
                        "Description": description,
                    }
                    if sobject == "Lead":
                        payload["Company"] = company
                    clean_payload = {k: v for k, v in payload.items() if v is not None}
                    resp = await client.patch(update_url, headers=self.headers, json=clean_payload)
                    if resp.status_code in (200, 204):
                        logger.info("SalesforceService: Updated existing record", sobject=sobject, sf_id=sf_id)
                        return sf_id
                    elif resp.status_code == 404:
                        logger.warning("SalesforceService: Record ID not found in Salesforce, will re-lookup", sf_id=sf_id)
                        sf_id = None
                    else:
                        resp.raise_for_status()

                # 2. Check for duplicate Contact by email
                existing_contact = await self.get_contact_by_email(email)
                if existing_contact:
                    cid = existing_contact["Id"]
                    update_url = f"{self.base_url}/sobjects/Contact/{cid}"
                    payload = {
                        "FirstName": first_name or None,
                        "LastName": last_name,
                        "Title": title or None,
                        "Description": description,
                    }
                    clean_payload = {k: v for k, v in payload.items() if v is not None}
                    resp = await client.patch(update_url, headers=self.headers, json=clean_payload)
                    resp.raise_for_status()
                    logger.info("SalesforceService: Updated existing Contact found by email", contact_id=cid, email=email)
                    return cid

                # 3. Check for duplicate Lead by email
                existing_lead = await self.get_lead_by_email(email)
                if existing_lead:
                    lid = existing_lead["Id"]
                    update_url = f"{self.base_url}/sobjects/Lead/{lid}"
                    payload = {
                        "FirstName": first_name or None,
                        "LastName": last_name,
                        "Company": company,
                        "Title": title or None,
                        "Description": description,
                    }
                    clean_payload = {k: v for k, v in payload.items() if v is not None}
                    resp = await client.patch(update_url, headers=self.headers, json=clean_payload)
                    resp.raise_for_status()
                    logger.info("SalesforceService: Updated existing Lead found by email", lead_id=lid, email=email)
                    return lid

                # 4. Create new Lead
                create_url = f"{self.base_url}/sobjects/Lead"
                payload = {
                    "FirstName": first_name or None,
                    "LastName": last_name,
                    "Company": company,
                    "Title": title or None,
                    "Email": email,
                    "City": city or None,
                    "LeadSource": "GTM Agent Intelligence",
                    "Description": description,
                }
                clean_payload = {k: v for k, v in payload.items() if v is not None}
                resp = await client.post(create_url, headers=self.headers, json=clean_payload)
                resp.raise_for_status()
                data = resp.json()
                new_lead_id = data.get("id")
                logger.info("SalesforceService: Successfully created new Lead in Salesforce", lead_id=new_lead_id, email=email)
                return new_lead_id

        except httpx.HTTPStatusError as e:
            logger.error(
                "SalesforceService: HTTP error syncing contact/lead",
                email=email,
                status_code=e.response.status_code,
                error_body=e.response.text,
            )
            return None
        except Exception as e:
            logger.error("SalesforceService: Unexpected error syncing contact/lead", email=email, error=str(e))
            return None


__all__ = ["SalesforceService", "SALESFORCE_STAGE_MAP"]
