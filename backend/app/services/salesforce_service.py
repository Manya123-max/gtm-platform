"""
Salesforce CRM Service & Lead Sync Integration for GTM Platform.
- SalesforceService: Interacts with Salesforce REST API (v60.0) for Opportunity synchronization,
  Contact/Lead resolution, and Activity/Task logging (Sole CRM Source of Truth).
- SalesforceSyncService: Upserts enriched GTM prospect data into Salesforce Lead objects using
  simple-salesforce or direct REST calls with custom field mapping.
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional
import httpx
import requests
import structlog
from app.core.config import settings

logger = structlog.get_logger(__name__)

try:
    from simple_salesforce import Salesforce
    from simple_salesforce.exceptions import SalesforceMalformedRequest, SalesforceResourceNotFound
    HAS_SIMPLE_SALESFORCE = True
except Exception:
    HAS_SIMPLE_SALESFORCE = False
    class SalesforceMalformedRequest(Exception): pass
    class SalesforceResourceNotFound(Exception): pass


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


class SalesforceSyncService:
    """Salesforce Lead Upsert & Synchronization Service."""

    def __init__(self):
        self.username = getattr(settings, "SF_USERNAME", "") or getattr(settings, "SALESFORCE_USERNAME", "")
        self.password = getattr(settings, "SALESFORCE_PASSWORD", "")
        self.client_id = getattr(settings, "SF_CLIENT_ID", "") or getattr(settings, "SALESFORCE_CLIENT_ID", "")
        self.client_secret = getattr(settings, "SF_CLIENT_SECRET", "") or getattr(settings, "SALESFORCE_CLIENT_SECRET", "")
        self.security_token = getattr(settings, "SALESFORCE_SECURITY_TOKEN", "")
        self.refresh_token = getattr(settings, "SALESFORCE_REFRESH_TOKEN", "")
        self.domain = getattr(settings, "SF_DOMAIN", "") or getattr(settings, "SALESFORCE_DOMAIN", "login") or "login"
        self._sf = None

    def _get_client(self):
        if self._sf is not None:
            return self._sf

        if not HAS_SIMPLE_SALESFORCE:
            raise RuntimeError("simple-salesforce package is not installed.")

        # Token endpoint always routes through the auth server (login.salesforce.com or test.salesforce.com)
        auth_domain = "test" if "test" in self.domain.lower() else "login"
        token_url = f"https://{auth_domain}.salesforce.com/services/oauth2/token"

        # Option 1: Client Credentials Flow (Modern Salesforce External Client App Flow — No Password Needed!)
        if self.client_id and self.client_secret:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            try:
                resp = requests.post(token_url, data=data, timeout=15)
                if resp.status_code == 200:
                    res_data = resp.json()
                    access_token = res_data.get("access_token")
                    instance_url = res_data.get("instance_url")
                    if access_token and instance_url:
                        self._sf = Salesforce(instance_url=instance_url, session_id=access_token)
                        logger.info("Authenticated to Salesforce via Client Credentials Flow", instance_url=instance_url)
                        return self._sf
                else:
                    logger.warning("Salesforce Client Credentials flow returned non-200", status=resp.status_code, text=resp.text)
            except Exception as e_cc:
                logger.warning("Salesforce Client Credentials flow attempt failed", error=str(e_cc))

        # Option 2: Username-Password Grant
        if self.username and self.password:
            kwargs = {
                "username": self.username,
                "password": self.password,
                "security_token": self.security_token,
                "domain": self.domain,
            }
            if self.client_id and self.client_secret:
                kwargs["consumer_key"] = self.client_id
                kwargs["consumer_secret"] = self.client_secret

            self._sf = Salesforce(**kwargs)
            logger.info("Authenticated to Salesforce via Direct Password grant", username=self.username)
            return self._sf

        # Option 3: Refresh Token Grant (Fallback if configured)
        if self.refresh_token and self.client_id and self.client_secret:
            token_domain = self.domain if self.domain in ("login", "test") else "login"
            token_url = f"https://{token_domain}.salesforce.com/services/oauth2/token"
            data = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            }
            resp = requests.post(token_url, data=data, timeout=15)
            if resp.status_code == 200:
                res_data = resp.json()
                access_token = res_data.get("access_token")
                instance_url = res_data.get("instance_url")
                if access_token and instance_url:
                    self._sf = Salesforce(instance_url=instance_url, session_id=access_token)
                    logger.info("Authenticated to Salesforce via Refresh Token grant", instance_url=instance_url)
                    return self._sf

        raise ValueError("Salesforce credentials not configured. Please enable 'Client Credentials Flow' on your External Client App in Salesforce Settings.")

    def sync_agent_prospect(self, prospect_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Converts agent prospect dictionary into Salesforce Lead format
        and upserts it into Salesforce.
        """
        email = prospect_data.get("email")
        if not email:
            return {
                "success": False,
                "error": "Cannot sync prospect to Salesforce without a valid email address.",
            }

        tech_stack = prospect_data.get("tech_stack")
        if isinstance(tech_stack, list):
            tech_stack_str = ", ".join(tech_stack)
        else:
            tech_stack_str = str(tech_stack or "")

        apollo_id = prospect_data.get("apollo_id") or prospect_data.get("id") or ""

        # Map Payload to Salesforce Lead Fields
        sf_lead_payload = {
            "FirstName": prospect_data.get("first_name", ""),
            "LastName": prospect_data.get("last_name") or "Unknown",
            "Company": prospect_data.get("company") or "Unknown",
            "Email": email,
            "Title": prospect_data.get("title", ""),
            "Website": prospect_data.get("company_domain", "") or prospect_data.get("website", ""),
            "Industry": prospect_data.get("industry", ""),
            "NumberOfEmployees": prospect_data.get("employee_count") or prospect_data.get("company_size"),
            "City": prospect_data.get("city", ""),
            "Country": prospect_data.get("country", "") or prospect_data.get("geography", ""),
            "LeadSource": prospect_data.get("source", "GTM Agent Engine"),
            # Custom Fields (Created in Salesforce Org Setup & Lead Layout)
            "LinkedIn_Profile__c": prospect_data.get("linkedin_url", ""),
            "Tech_Stack__c": tech_stack_str,
            "Funding_Stage__c": prospect_data.get("funding_stage", "Unknown"),
            "Apollo_ID__c": str(apollo_id),
            "Email_Verified__c": bool(prospect_data.get("email_verified", True)),
        }

        # Remove None values to avoid overwriting existing data with NULLs
        sf_lead_payload = {k: v for k, v in sf_lead_payload.items() if v is not None}

        try:
            sf = self._get_client()

            # Attempt 1: Try upsert with Apollo_ID__c if present
            if apollo_id:
                try:
                    result = sf.Lead.upsert(f"Apollo_ID__c/{apollo_id}", sf_lead_payload)
                    status = "created" if result == 201 else "updated"
                    logger.info("Successfully synced lead to Salesforce via Apollo_ID__c", email=email, status=status)
                    return {"success": True, "status": status, "email": email, "salesforce_result": result}
                except Exception as e_upsert:
                    logger.warning("Upsert via Apollo_ID__c failed, falling back to Email lookup", error=str(e_upsert))

            # Attempt 2: Search by Email and Update or Create (filtering out any unmapped __c fields if necessary)
            query_res = sf.query(f"SELECT Id FROM Lead WHERE Email = '{email}' LIMIT 1")
            records = query_res.get("records", [])

            def execute_lead_write(payload):
                cur_payload = dict(payload)
                for attempt in range(3):
                    try:
                        if records:
                            lead_id = records[0]["Id"]
                            res = sf.Lead.update(lead_id, cur_payload)
                            return "updated", res
                        else:
                            res = sf.Lead.create(cur_payload)
                            return "created", res
                    except Exception as ex:
                        err_str = str(ex)
                        # If error mentions a custom field does not exist, strip custom fields (__c) and retry
                        custom_fields = [k for k in cur_payload.keys() if k.endswith("__c")]
                        if custom_fields and ("INVALID_FIELD" in err_str or "NOT_FOUND" in err_str or "No such column" in err_str or "Provided external ID" in err_str):
                            logger.warning(f"Stripping unmapped custom fields {custom_fields} and retrying lead sync", error=err_str)
                            for cf in custom_fields:
                                cur_payload.pop(cf, None)
                            continue
                        raise ex

            status, result = execute_lead_write(sf_lead_payload)
            logger.info("Successfully synced lead to Salesforce", email=email, status=status)
            return {
                "success": True,
                "status": status,
                "email": email,
                "salesforce_result": result,
            }
        except SalesforceMalformedRequest as e:
            err_msg = str(getattr(e, "content", e))
            logger.error("Salesforce validation error", email=email, error=err_msg)
            return {"success": False, "error": err_msg}
        except Exception as e:
            err_msg = str(e)
            logger.error("Error syncing to Salesforce", email=email, error=err_msg)
            return {"success": False, "error": err_msg}

    def sync_contact_model(self, contact) -> Dict[str, Any]:
        """
        Syncs a database Contact model instance to Salesforce Lead.
        """
        tech_stack = getattr(contact, "tech_stack", None)
        if isinstance(tech_stack, list):
            tech_stack_list = tech_stack
        elif isinstance(tech_stack, str) and tech_stack:
            tech_stack_list = [t.strip() for t in tech_stack.split(",") if t.strip()]
        else:
            tech_stack_list = []

        prospect_data = {
            "first_name": getattr(contact, "first_name", "") or "",
            "last_name": getattr(contact, "last_name", "") or "Unknown",
            "company": getattr(contact, "company", "") or "Unknown",
            "email": getattr(contact, "email", "") or "",
            "title": getattr(contact, "title", "") or "",
            "company_domain": getattr(contact, "company_domain", "") or "",
            "industry": getattr(contact, "industry", "") or "",
            "employee_count": getattr(contact, "company_size", None),
            "geography": getattr(contact, "geography", "") or "",
            "source": "GTM Platform Contact",
            "linkedin_url": getattr(contact, "linkedin_url", "") or "",
            "tech_stack": tech_stack_list,
            "funding_stage": getattr(contact, "funding_stage", "") or "Unknown",
            "apollo_id": getattr(contact, "apollo_id", "") or str(getattr(contact, "id", "")),
            "email_verified": True if not getattr(contact, "do_not_contact", False) else False,
        }
        return self.sync_agent_prospect(prospect_data)


__all__ = ["SalesforceService", "SalesforceSyncService", "SALESFORCE_STAGE_MAP"]
