import sys
import traceback
from app.core.config import settings
from app.services import SalesforceSyncService

def test_salesforce_connection():
    print("==================================================")
    print(" TESTING SALESFORCE CRM CONNECTION ")
    print("==================================================\n")
    
    print(f"SALESFORCE_USERNAME       : {settings.SALESFORCE_USERNAME or '(Not set)'}")
    print(f"SALESFORCE_DOMAIN         : {settings.SALESFORCE_DOMAIN or 'login'}")
    print(f"SALESFORCE_CLIENT_ID      : {'***' + settings.SALESFORCE_CLIENT_ID[-6:] if settings.SALESFORCE_CLIENT_ID else '(Not set)'}")
    print(f"SALESFORCE_CLIENT_SECRET  : {'***' + settings.SALESFORCE_CLIENT_SECRET[-4:] if settings.SALESFORCE_CLIENT_SECRET else '(Not set)'}")
    print(f"SALESFORCE_SECURITY_TOKEN : {'***' + settings.SALESFORCE_SECURITY_TOKEN[-4:] if settings.SALESFORCE_SECURITY_TOKEN else '(Not set)'}\n")
    
    if not settings.SALESFORCE_USERNAME or not settings.SALESFORCE_PASSWORD:
        print("[!] NOTICE: SALESFORCE_USERNAME or SALESFORCE_PASSWORD is not set in backend/.env!")
        print("Please paste your credentials into backend/.env and run this test script again.\n")
        return
        
    try:
        service = SalesforceSyncService()
        sf = service._get_client()
        
        # Query Organization details as a ping test
        org_res = sf.query("SELECT Id, Name, OrganizationType FROM Organization")
        records = org_res.get("records", [])
        org_name = records[0]["Name"] if records else "Unknown"
        org_type = records[0]["OrganizationType"] if records else "Unknown"
        
        print("[SUCCESS] Connected to Salesforce Org successfully!")
        print(f"  Org Name: {org_name}")
        print(f"  Org Type: {org_type}")
        print(f"  Connected User: {settings.SALESFORCE_USERNAME}\n")
        
        # Test Lead object accessibility & custom fields
        print("Checking Lead object & GTM Custom Fields...")
        lead_desc = sf.Lead.describe()
        fields = [f["name"] for f in lead_desc.get("fields", [])]
        custom_gtm_fields = ["LinkedIn_Profile__c", "Tech_Stack__c", "Funding_Stage__c", "Apollo_ID__c", "Email_Verified__c"]
        found_custom = [f for f in custom_gtm_fields if f in fields]
        
        print(f"[SUCCESS] Lead Object Accessible! Total Lead Fields: {len(fields)}")
        print(f"  GTM Custom Fields Verified ({len(found_custom)}/{len(custom_gtm_fields)}): {', '.join(found_custom)}\n")
        
    except Exception as e:
        print("[FAILED] CONNECTION ERROR:")
        print(f"  Error Message: {str(e)}\n")
        print("Troubleshooting Steps:")
        print("1. If 'invalid grant': Check your SALESFORCE_USERNAME and SALESFORCE_PASSWORD.")
        print("2. If 'IP restricted': Make sure in Connected App -> Edit Policies -> IP Relaxation is set to 'Relax IP restrictions'.")
        print("3. Allow 2-5 minutes for Salesforce Connected App propagation.")

if __name__ == "__main__":
    test_salesforce_connection()
