import os
import requests

env_vars = {}
with open("c:/Users/manya/gtm-platform/backend/.env", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip().strip("'\"")

domain = env_vars.get("SF_DOMAIN") or env_vars.get("SALESFORCE_DOMAIN") or "4cecloudlab7-dev-ed.trailblaze.my.salesforce.com"
client_id = env_vars.get("SF_CLIENT_ID") or env_vars.get("SALESFORCE_CLIENT_ID")
client_secret = env_vars.get("SF_CLIENT_SECRET") or env_vars.get("SALESFORCE_CLIENT_SECRET")

print(f"Connecting to Salesforce Org ({domain})...")
token_url = f"https://{domain}/services/oauth2/token"
res = requests.post(token_url, data={
    "grant_type": "client_credentials",
    "client_id": client_id,
    "client_secret": client_secret
})

if res.status_code == 200:
    data = res.json()
    access_token = data["access_token"]
    instance_url = data["instance_url"]
    
    from simple_salesforce import Salesforce
    sf = Salesforce(instance_url=instance_url, session_id=access_token)
    
    leads = sf.query("SELECT Id, FirstName, LastName, Company, Email, Title, CreatedDate FROM Lead ORDER BY CreatedDate DESC LIMIT 10")
    print(f"\nFound {len(leads['records'])} Recent Leads in Salesforce:\n" + "="*70)
    for r in leads["records"]:
        print(f"Name:         {r.get('FirstName', '')} {r.get('LastName', '')}")
        print(f"Email:        {r.get('Email')}")
        print(f"Company:      {r.get('Company')}")
        print(f"Lead ID:      {r.get('Id')}")
        print(f"Created Date: {r.get('CreatedDate')}")
        print("-" * 70)
else:
    print("Error authenticating:", res.status_code, res.text)
