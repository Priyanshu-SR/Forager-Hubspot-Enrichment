import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FORAGER_API_KEY")
ACCOUNT_ID = os.getenv("FORAGER_ACCOUNT_ID")
BASE_FORAGER = f"https://api-v2.forager.ai/api/{ACCOUNT_ID}/datastorage"

if not API_KEY or not ACCOUNT_ID:
    raise RuntimeError("Missing FORAGER_API_KEY or FORAGER_ACCOUNT_ID in .env")

headers = {
    "X-API-KEY": API_KEY,
    "Content-Type": "application/json",
}


def lookup_personal_email(person_id: int) -> str | None:
    """Costs 5 credits ONLY if a non-empty list is returned (0 credits if empty)."""
    url = f"{BASE_FORAGER}/person_contacts_lookup/personal_emails/"
    resp = requests.post(url, headers=headers, json={"person_id": person_id}, timeout=30)
    if not resp.ok:
        print(f"  [Email Lookup HTTP {resp.status_code}]: {resp.text[:200]}")
        return None
    if not resp.content:
        return None
    data = resp.json()
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first.get("email") or first.get("email_address") or first.get("value")
        if isinstance(first, str):
            return first
    elif isinstance(data, dict):
        items = data.get("results") or data.get("emails") or []
        if items and isinstance(items[0], dict):
            return items[0].get("email") or items[0].get("email_address")
    return None


def lookup_phone_number(person_id: int) -> str | None:
    """Costs 15 credits ONLY if a phone number is returned (0 credits if empty)."""
    url = f"{BASE_FORAGER}/person_contacts_lookup/phone_numbers/"
    resp = requests.post(url, headers=headers, json={"person_id": person_id}, timeout=30)
    if not resp.ok:
        print(f"  [Phone Lookup HTTP {resp.status_code}]: {resp.text[:200]}")
        return None
    if not resp.content:
        return None
    data = resp.json()
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first.get("phone_number") or first.get("phone") or first.get("value")
        if isinstance(first, str):
            return first
    elif isinstance(data, dict):
        items = data.get("results") or data.get("phone_numbers") or []
        if items and isinstance(items[0], dict):
            return items[0].get("phone_number") or items[0].get("phone")
    return None


def main():
    with open("prepared_contacts.json", "r", encoding="utf-8") as f:
        contacts = json.load(f)

    # Prioritize the 6 contacts that have complete City, State, Country
    complete_loc_contacts = [
        c for c in contacts
        if c.get("city") and c.get("state") and c.get("country")
    ]

    # Budget tracker so we never exceed 41 credits
    credits_remaining = 41

    print("=== Step 1: Checking Personal Emails for Top 5 Complete Contacts (5 credits only on hit) ===")
    for c in complete_loc_contacts[:5]:
        if c.get("email"):
            print(f"- {c['full_name']}: already cached ({c['email']})")
            continue
        if credits_remaining < 5:
            print("Stopping email lookups to preserve credits.")
            break
        email = lookup_personal_email(c["person_id"])
        if email:
            c["email"] = email
            credits_remaining -= 5
            print(f"- {c['full_name']}: FOUND email -> {email} (~{credits_remaining} credits left)")
        else:
            print(f"- {c['full_name']}: No personal email on file (0 credits charged)")

    print("\n=== Step 2: Checking Phone Numbers Where Budget Allows (15 credits only on hit) ===")
    for c in complete_loc_contacts[:5]:
        if c.get("phone"):
            print(f"- {c['full_name']}: already cached ({c['phone']})")
            continue
        # Keep at least 5 credits in reserve for any emergency test
        if credits_remaining < 20:
            print(f"Stopping phone lookups with ~{credits_remaining} credits in reserve.")
            break
        phone = lookup_phone_number(c["person_id"])
        if phone:
            c["phone"] = phone
            credits_remaining -= 15
            print(f"- {c['full_name']}: FOUND phone -> {phone} (~{credits_remaining} credits left)")
        else:
            print(f"- {c['full_name']}: No phone number on file (0 credits charged)")

    # Save immediately to prepared_contacts.json so we never have to call the API again
    with open("prepared_contacts.json", "w", encoding="utf-8") as f:
        json.dump(contacts, f, indent=2, ensure_ascii=False)

    print("\nSaved updated email/phone data to prepared_contacts.json!")


if __name__ == "__main__":
    main()