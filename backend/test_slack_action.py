import httpx
import json

payload = {
    "type": "block_actions",
    "user": {"username": "surya", "email": "suriya.krishnan@forcecloudlabs.com"},
    "actions": [{"action_id": "approve_draft", "value": "9963eec3-53fd-4c2c-8397-90253a0b7621"}]
}

resp1 = httpx.post("http://localhost:8000/webhook/slack/actions", data={"payload": json.dumps(payload)})
print("webhook status:", resp1.status_code, resp1.text)

resp2 = httpx.post("http://localhost:8000/api/v1/slack/actions", data={"payload": json.dumps(payload)})
print("api/v1 status:", resp2.status_code, resp2.text)
