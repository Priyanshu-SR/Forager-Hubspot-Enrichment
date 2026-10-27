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

def verify_and_setup_contact_properties():
    resp = requests.get(
        f"{BASE_URL}/crm/v3/properties/contacts",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    all_props = {p["name"]: p for p in resp.json().get("results", [])}

    # 1. Check standard properties we need for the rubric
    target_props = [
        "firstname",
        "lastname",
        "jobtitle",
        "company",
        "website",
        "email",
        "phone",
        "mobilephone",
        "city",
        "state",
        "country",
        "hs_linkedin_url",
        "linkedinbio",
    ]
    print("=== Standard Contact Properties Check ===")
    for name in target_props:
        prop = all_props.get(name)
        if prop:
            read_only = prop.get("modificationMetadata", {}).get("readOnlyValue", False)
            print(f"  [OK] {name} (label: '{prop.get('label')}', writable: {not read_only})")
        else:
            print(f"  [MISSING] {name}")

    # 2. Check if any property for company LinkedIn URL exists on Contacts
    linkedin_candidates = [
        name for name in all_props
        if "linkedin" in name.lower() and "company" in name.lower()
    ]
    print("\nExisting company-linkedin contact properties:", linkedin_candidates)

    custom_prop_name = "company_linkedin_url"
    if custom_prop_name in all_props:
        print(f"  [OK] '{custom_prop_name}' already exists on Contacts.")
    else:
        print(f"  Creating custom Contact property '{custom_prop_name}'...")
        create_resp = requests.post(
            f"{BASE_URL}/crm/v3/properties/contacts",
            headers=headers,
            json={
                "name": custom_prop_name,
                "label": "Company LinkedIn URL",
                "type": "string",
                "fieldType": "text",
                "groupName": "contactinformation",
                "description": "LinkedIn URL of the contact's employer (populated via Forager enrichment).",
            },
            timeout=30,
        )
        create_resp.raise_for_status()
        print(f"  [CREATED] '{custom_prop_name}' successfully created!")

if __name__ == "__main__":
    verify_and_setup_contact_properties()