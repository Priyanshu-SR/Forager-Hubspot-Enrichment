import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")
BASE_URL = "https://api.hubapi.com"

if not TOKEN:
    raise RuntimeError("Missing HUBSPOT_ACCESS_TOKEN in .env")

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

with open("prepared_contacts.json", "r", encoding="utf-8") as file:
    contacts = json.load(file)

# Find the existing OpenAI company in HubSpot.
response = requests.post(
    f"{BASE_URL}/crm/v3/objects/companies/search",
    headers=headers,
    json={
        "filterGroups": [{
            "filters": [{
                "propertyName": "domain",
                "operator": "EQ",
                "value": "openai.com",
            }]
        }],
        "properties": ["name", "domain"],
        "limit": 10,
    },
    timeout=30,
)
response.raise_for_status()

companies = response.json().get("results", [])
if not companies:
    raise RuntimeError("OpenAI company not found in HubSpot.")

company_id = companies[0]["id"]
print("OpenAI company ID:", company_id)

for contact in contacts:
    properties = {
        "firstname": contact.get("first_name") or "",
        "lastname": contact.get("last_name") or "",
        "jobtitle": contact.get("job_title") or "",
        "company": contact.get("company") or "OpenAI",
        "website": f"https://{contact.get('company_domain') or 'openai.com'}",
        "hs_linkedin_url": contact.get("linkedin_url") or "",
        "company_linkedin_url": contact.get("company_linkedin_url") or "",
        "linkedinbio": contact.get("description") or "",
        "city": contact.get("city") or "",
        "state": contact.get("state") or "",
        "country": contact.get("country") or "",
        "email": contact.get("email") or "",
        "phone": contact.get("phone") or "",
    }
    properties = {k: v for k, v in properties.items() if v}

    linkedin_url = contact.get("linkedin_url")
    existing = []

    if linkedin_url:
        search_response = requests.post(
            f"{BASE_URL}/crm/v3/objects/contacts/search",
            headers=headers,
            json={
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "hs_linkedin_url",
                        "operator": "EQ",
                        "value": linkedin_url,
                    }]
                }],
                "properties": ["firstname", "lastname", "hs_linkedin_url"],
                "limit": 1,
            },
            timeout=30,
        )
        search_response.raise_for_status()
        existing = search_response.json().get("results", [])

    if existing:
        contact_id = existing[0]["id"]
        result = requests.patch(
            f"{BASE_URL}/crm/v3/objects/contacts/{contact_id}",
            headers=headers,
            json={"properties": properties},
            timeout=30,
        )
        action = "Updated"
    else:
        result = requests.post(
            f"{BASE_URL}/crm/v3/objects/contacts",
            headers=headers,
            json={"properties": properties},
            timeout=30,
        )
        action = "Created"

    if result.ok:
        contact_id = result.json().get("id")
        association = requests.put(
            f"{BASE_URL}/crm/v4/objects/contacts/{contact_id}"
            f"/associations/default/companies/{company_id}",
            headers=headers,
            timeout=30,
        )
        if not association.ok:
            print("Association warning:", association.status_code, association.text[:300])

        print(
            f"{action}: {contact['full_name']} | ID: {contact_id} | "
            f"{contact.get('city')}, {contact.get('state')}, {contact.get('country')}"
        )
    else:
        print(f"Failed: {contact['full_name']} | {result.status_code} | {result.text[:300]}")