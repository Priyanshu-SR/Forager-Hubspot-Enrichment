
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FORAGER_API_KEY")
ACCOUNT_ID = os.getenv("FORAGER_ACCOUNT_ID")

if not API_KEY or not ACCOUNT_ID:
    raise RuntimeError(
        "Missing FORAGER_API_KEY or FORAGER_ACCOUNT_ID in .env"
    )

url = (
    f"https://api-v2.forager.ai/api/{ACCOUNT_ID}"
    "/datastorage/person_role_search/"
)

response = requests.post(
    url,
    headers={
        "X-API-KEY": API_KEY,
        "Content-Type": "application/json",
    },
    json={
        "role_title": "engineer",
        "organization_domains": ["openai.com"],
    },
    timeout=30,
)

print("HTTP status:", response.status_code)
response.raise_for_status()

results = response.json().get("search_results", [])

# Save immediately so we can develop without more API calls.
with open("forager_people.json", "w", encoding="utf-8") as file:
    json.dump(results, file, indent=2, ensure_ascii=False)

current_people = [
    item for item in results
    if item.get("is_current") is True
]

print("People returned:", len(results))
print("Current roles:", len(current_people))
print("Saved full response to forager_people.json")
