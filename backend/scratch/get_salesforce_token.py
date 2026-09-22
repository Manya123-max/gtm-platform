import os
import sys
import secrets
import hashlib
import base64
import requests
import urllib.parse

def load_env():
    env_vars = {}
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("'\"")
    return env_vars

def generate_pkce():
    code_verifier = secrets.token_urlsafe(64)
    hashed = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(hashed).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge

def main():
    env = load_env()
    client_id = env.get("SALESFORCE_CLIENT_ID", "")
    client_secret = env.get("SALESFORCE_CLIENT_SECRET", "")
    domain = env.get("SALESFORCE_DOMAIN", "login") or "login"
    redirect_uri = "https://login.salesforce.com/services/oauth2/success"

    print("\n" + "="*70)
    print("SALESFORCE OAUTH REFRESH TOKEN GENERATOR (PKCE Enabled)")
    print("="*70)
    if client_id:
        print(f"Loaded Client ID: {client_id[:10]}...")
    else:
        client_id = input("Enter Salesforce Client ID: ").strip()

    if client_secret:
        print(f"Loaded Client Secret: {client_secret[:6]}...")
    else:
        client_secret = input("Enter Salesforce Client Secret: ").strip()

    code_verifier, code_challenge = generate_pkce()

    print("\n--- STEP 1: Open this URL in your web browser ---")
    auth_url = (
        f"https://{domain}.salesforce.com/services/oauth2/authorize?"
        f"response_type=code&client_id={client_id}&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&code_challenge={code_challenge}&code_challenge_method=S256"
    )
    print(auth_url)
    print("="*70)

    code = input("\n--- STEP 2: Paste the full URL (or code) from your browser address bar: ").strip()

    if not code:
        print("No code provided. Exiting.")
        return

    if "code=" in code:
        code = code.split("code=")[1].split("&")[0]

    code = urllib.parse.unquote(code)

    token_url = f"https://{domain}.salesforce.com/services/oauth2/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": code_verifier,
    }

    print("\nExchanging code for Refresh Token...")
    res = requests.post(token_url, data=payload)
    print(f"Status Code: {res.status_code}")
    try:
        data = res.json()
        if "refresh_token" in data:
            print("\n" + "="*70)
            print("SUCCESS! Refresh Token obtained:")
            print("="*70)
            print(f"\nSALESFORCE_REFRESH_TOKEN={data['refresh_token']}\n")
            
            # Automatically write into backend/.env
            env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "SALESFORCE_REFRESH_TOKEN=" in content:
                    import re
                    content = re.sub(r"SALESFORCE_REFRESH_TOKEN=.*", f"SALESFORCE_REFRESH_TOKEN={data['refresh_token']}", content)
                else:
                    content += f"\nSALESFORCE_REFRESH_TOKEN={data['refresh_token']}\n"
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print("Updated backend/.env automatically with your new Refresh Token!")
        else:
            print("\nError Response from Salesforce:")
            print(data)
    except Exception:
        print(res.text)

if __name__ == "__main__":
    main()
