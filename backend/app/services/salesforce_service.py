"""
salesforce_service.py — Salesforce REST API Lead Sync Integration.

Upserts enriched GTM prospect data into Salesforce Lead objects using
simple-salesforce (or direct REST calls). Maps both Standard Lead fields
and GTM Custom Fields (Apollo_ID__c, Tech_Stack__c, Funding_Stage__c, etc.).
"""
from __future__ import annotations

import structlog
from typing import Dict, Any, Optional
from app.core.config import settings

logger = structlog.get_logger()

try:
    from simple_salesforce import Salesforce
    from simple_salesforce.exceptions import SalesforceMalformedRequest, SalesforceResourceNotFound
    HAS_SIMPLE_SALESFORCE = True
except Exception:
    HAS_SIMPLE_SALESFORCE = False
    class SalesforceMalformedRequest(Exception): pass
    class SalesforceResourceNotFound(Exception): pass


import requests


class SalesforceSyncService:
    """Salesforce Lead Upsert & Synchronization Service."""

    def __init__(self):
        self.username = getattr(settings, "SALESFORCE_USERNAME", "")
        self.password = getattr(settings, "SALESFORCE_PASSWORD", "")
        self.client_id = getattr(settings, "SALESFORCE_CLIENT_ID", "")
        self.client_secret = getattr(settings, "SALESFORCE_CLIENT_SECRET", "")
        self.security_token = getattr(settings, "SALESFORCE_SECURITY_TOKEN", "")
        self.refresh_token = getattr(settings, "SALESFORCE_REFRESH_TOKEN", "")
        self.domain = getattr(settings, "SALESFORCE_DOMAIN", "login") or "login"
        self._sf = None

    def _get_client(self):
        if self._sf is not None:
            return self._sf

        if not HAS_SIMPLE_SALESFORCE:
            raise RuntimeError("simple-salesforce package is not installed.")

        # Option 1: Direct Login with Username + Password (Primary & Persistent)
        if self.username and self.password:
            kwargs = {
                "username": self.username,
                "password": self.password,
                "domain": self.domain,
            }
            if self.client_id and self.client_secret:
                kwargs["consumer_key"] = self.client_id
                kwargs["consumer_secret"] = self.client_secret
            elif self.security_token:
                kwargs["security_token"] = self.security_token

            self._sf = Salesforce(**kwargs)
            logger.info("Authenticated to Salesforce via Direct Password grant", username=self.username)
            return self._sf

        # Option 2: Refresh Token Grant (Fallback if configured)
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

        raise ValueError("Salesforce credentials not configured. Please set SALESFORCE_USERNAME and SALESFORCE_PASSWORD in backend/.env.")

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
