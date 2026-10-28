import json
import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Query, Request

load_dotenv()

app = FastAPI(
    title="Forager × HubSpot GTM Enrichment Service",
    description=(
        "End-to-end company and contact enrichment automation connecting "
        "Forager API v2 with HubSpot CRM webhooks."
    ),
    version="2.0.0",
)

FORAGER_API_KEY = os.getenv("FORAGER_API_KEY")
FORAGER_ACCOUNT_ID = os.getenv("FORAGER_ACCOUNT_ID")
HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")
HUBSPOT_WEBHOOK_SECRET = os.getenv("HUBSPOT_WEBHOOK_SECRET")
DEFAULT_ROLE_FILTER = os.getenv("DEFAULT_JOB_TITLE_FILTER", "Engineer")
# Set ENABLE_PAID_CONTACT_LOOKUPS=true only when you want live webhook runs to spend 5-15 credits on email/phone lookups
ENABLE_PAID_CONTACT_LOOKUPS = os.getenv("ENABLE_PAID_CONTACT_LOOKUPS", "false").lower() == "true"

FORAGER_BASE = "https://api-v2.forager.ai/api"
HUBSPOT_BASE = "https://api.hubapi.com"
TIMEOUT = 30


def hubspot_headers() -> dict:
    if not HUBSPOT_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="HUBSPOT_ACCESS_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def forager_headers() -> dict:
    if not FORAGER_API_KEY or not FORAGER_ACCOUNT_ID:
        raise HTTPException(
            status_code=500,
            detail="FORAGER_API_KEY or FORAGER_ACCOUNT_ID is not configured",
        )
    return {
        "X-API-KEY": FORAGER_API_KEY,
        "Content-Type": "application/json",
    }


def normalize_domain(raw_domain: Optional[str]) -> str:
    if not raw_domain:
        return ""
    cleaned = raw_domain.strip().lower()
    cleaned = cleaned.removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.split("/")[0].removeprefix("www.")
    return cleaned


def extract_structured_location(location_obj: Optional[dict]) -> dict:
    """Extract clean city, state, and country from Forager's osm_locations."""
    if not location_obj:
        return {"city": None, "state": None, "country": None, "raw_location": None}

    osm_locations = location_obj.get("osm_locations") or []
    city = None
    fallback_city = None
    state = None
    country = None

    for loc in osm_locations:
        place_type = (loc.get("place_type") or "").lower()
        clean_name = (loc.get("name") or "").split(",")[0].strip()
        if not clean_name:
            continue

        if place_type in ("city", "town") and not city:
            city = clean_name
        elif place_type in ("locality", "county", "administrative") and not fallback_city:
            fallback_city = clean_name
        elif place_type in ("state", "region", "province") and not state:
            state = clean_name
        elif place_type == "country" and not country:
            country = clean_name

    city = city or fallback_city
    raw_name = (location_obj.get("name") or "").strip()
    if raw_name and not (city or state or country):
        parts = [p.strip().title() for p in raw_name.split(",") if p.strip()]
        if len(parts) == 3:
            city, state, country = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            city, country = parts[0], parts[1]
        elif len(parts) == 1:
            country = parts[0]

    return {
        "city": city,
        "state": state,
        "country": country,
        "raw_location": raw_name or None,
    }


def hubspot_request(method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(
            method,
            f"{HUBSPOT_BASE}{path}",
            headers=hubspot_headers(),
            timeout=TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"HubSpot connection failed: {exc}")

    if not response.ok:
        try:
            body = response.json()
        except ValueError:
            body = response.text[:1000]
        raise HTTPException(
            status_code=502,
            detail={
                "message": "HubSpot API request failed",
                "hubspot_status": response.status_code,
                "hubspot_error": body,
            },
        )
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


def load_cached_openai_org() -> Optional[dict]:
    """Return cached OpenAI organization record from forager_people.json to save API credits."""
    path = Path("forager_people.json")
    if not path.exists():
        return None
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        for item in records:
            org = item.get("organization") or {}
            if normalize_domain(org.get("domain")) == "openai.com" and (org.get("name") or "").lower() == "openai":
                return org
    except (OSError, json.JSONDecodeError):
        return None
    return None


def load_prepared_contacts() -> list[dict]:
    path = Path("prepared_contacts.json")
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def get_forager_company(domain: str = "", linkedin_identifier: str = "", use_cache: bool = True) -> tuple[dict, bool]:
    """Fetch company details from cache (if openai.com) or live Forager organization_search API (1 credit)."""
    clean_domain = normalize_domain(domain)
    clean_slug = (linkedin_identifier or "").strip().lower()
    if not clean_slug and clean_domain:
        clean_slug = clean_domain.split(".")[0]

    if use_cache and (clean_domain == "openai.com" or clean_slug == "openai"):
        cached_org = load_cached_openai_org()
        if cached_org:
            return cached_org, False

    url = f"{FORAGER_BASE}/{FORAGER_ACCOUNT_ID}/datastorage/organization_search/"
    payload: dict = {"page": 0}
    if clean_slug:
        payload["linkedin_public_identifiers"] = [clean_slug]

    try:
        response = requests.post(url, headers=forager_headers(), json=payload, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Forager company search failed: {exc}")

    results = response.json().get("search_results", [])
    for company in results:
        comp_domain = normalize_domain(company.get("domain"))
        linkedin = company.get("linkedin_info") or {}
        comp_slug = (linkedin.get("public_identifier") or "").lower()
        if (clean_domain and comp_domain == clean_domain) or (clean_slug and comp_slug == clean_slug):
            return company, True

    if results:
        return results[0], True
    raise HTTPException(status_code=404, detail="Company match not found in Forager")


def lookup_forager_personal_email(person_id: int) -> Optional[str]:
    """Look up personal email via Forager (costs 5 credits ONLY if an email is returned)."""
    url = f"{FORAGER_BASE}/{FORAGER_ACCOUNT_ID}/datastorage/person_contacts_lookup/personal_emails/"
    try:
        resp = requests.post(url, headers=forager_headers(), json={"person_id": person_id}, timeout=TIMEOUT)
        if not resp.ok or not resp.content:
            return None
        data = resp.json()
        if isinstance(data, list) and data:
            first = data[0]
            return first.get("email") if isinstance(first, dict) else str(first)
    except requests.RequestException:
        return None
    return None


def lookup_forager_phone(person_id: int) -> Optional[str]:
    """Look up phone number via Forager (costs 15 credits ONLY if a phone is returned)."""
    url = f"{FORAGER_BASE}/{FORAGER_ACCOUNT_ID}/datastorage/person_contacts_lookup/phone_numbers/"
    try:
        resp = requests.post(url, headers=forager_headers(), json={"person_id": person_id}, timeout=TIMEOUT)
        if not resp.ok or not resp.content:
            return None
        data = resp.json()
        if isinstance(data, list) and data:
            first = data[0]
            return first.get("phone_number") if isinstance(first, dict) else str(first)
    except requests.RequestException:
        return None
    return None


def enrich_company_record(company_id: str, force_live: bool = False) -> dict:
    """Task 1: Pull full company details from Forager and update the HubSpot Company record."""
    current = hubspot_request(
        "GET",
        f"/crm/v3/objects/companies/{company_id}",
        params={"properties": "name,domain,description,linkedin_company_page"},
    )
    current_props = current.get("properties") or {}
    domain = normalize_domain(current_props.get("domain"))
    name_slug = (current_props.get("name") or "").strip().lower().replace(" ", "")

    company, forager_called = get_forager_company(
        domain=domain,
        linkedin_identifier=name_slug or (domain.split(".")[0] if domain else ""),
        use_cache=not force_live,
    )

    finance = company.get("finance_info") or {}
    linkedin = company.get("linkedin_info") or {}
    industry = linkedin.get("industry") or {}
    addresses = company.get("addresses") or []
    primary_addr = addresses[1] if len(addresses) > 1 else (addresses[0] if addresses else {})

    description = company.get("description")
    employees = company.get("employees_amount")
    revenue = finance.get("revenue")
    industry_name = (industry.get("name") or "").strip()
    industry_value = "RESEARCH" if industry_name.casefold() == "research" else None

    properties = {
        "name": company.get("name"),
        "domain": company.get("domain"),
        "website": company.get("website"),
        "description": description,
        "numberofemployees": employees,
        "industry": industry_value,
        "linkedin_company_page": linkedin.get("public_profile_url"),
        "forager_revenue": revenue,
        "city": primary_addr.get("city"),
        "state": primary_addr.get("state"),
        "country": primary_addr.get("country"),
        "zip": primary_addr.get("postcode"),
        "founded_year": (company.get("founded_date") or "")[:4] or None,
    }
    properties = {k: v for k, v in properties.items() if v is not None and v != ""}
    result = hubspot_request(
        "PATCH",
        f"/crm/v3/objects/companies/{company_id}",
        json={"properties": properties},
    )

    return {
        "status": "enriched",
        "company_id": company_id,
        "hubspot_result_id": result.get("id"),
        "company": company.get("name"),
        "domain": company.get("domain"),
        "description_updated": bool(description),
        "headcount": employees,
        "revenue_from_forager": revenue,
        "industry": industry_name or None,
        "linkedin_url": linkedin.get("public_profile_url"),
        "address": primary_addr,
        "forager_called": forager_called,
    }


def get_company_contacts(company_id: str) -> list[str]:
    data = hubspot_request(
        "GET",
        f"/crm/v4/objects/companies/{company_id}/associations/contacts",
        params={"limit": 500},
    )
    contact_ids = []
    for item in data.get("results", []):
        cid = item.get("toObjectId")
        if cid and str(cid) not in contact_ids:
            contact_ids.append(str(cid))
    return contact_ids


def find_forager_people(domain: str, role_title: str, page: int = 0) -> list[dict]:
    """Task 3: Search Forager for contacts at a company filtered by job title (1 credit)."""
    url = f"{FORAGER_BASE}/{FORAGER_ACCOUNT_ID}/datastorage/person_role_search/"
    try:
        response = requests.post(
            url,
            headers=forager_headers(),
            json={
                "page": page,
                "role_title": role_title,
                "organization_domains": [domain],
                "role_is_current": True,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Forager people search failed: {exc}")
    return response.json().get("search_results", [])


def find_and_sync_company_contacts(
    company_id: str,
    job_title: str = DEFAULT_ROLE_FILTER,
    limit: int = 5,
    force_live: bool = False,
) -> dict:
    """Task 3 & 4: Discover contacts at a company with job-title filtering and sync to HubSpot."""
    company_record = hubspot_request(
        "GET",
        f"/crm/v3/objects/companies/{company_id}",
        params={"properties": "name,domain,linkedin_company_page"},
    )
    comp_props = company_record.get("properties") or {}
    target_domain = normalize_domain(comp_props.get("domain"))
    if not target_domain:
        return {
            "status": "skipped",
            "reason": "Target HubSpot company has no domain configured",
            "created_or_updated": [],
            "forager_called": False,
        }

    candidates = []
    forager_called = False

    # Use local prepared_contacts.json cache for openai.com unless force_live=True
    if target_domain == "openai.com" and not force_live:
        for item in load_prepared_contacts():
            if normalize_domain(item.get("company_domain")) != "openai.com":
                continue
            if job_title and job_title.casefold() not in (item.get("job_title") or "").casefold():
                continue
            candidates.append(item)
    else:
        raw_roles = find_forager_people(target_domain, job_title)
        forager_called = True
        for role in raw_roles:
            if role.get("is_current") is False:
                continue
            person = role.get("person") or {}
            org = role.get("organization") or {}
            if normalize_domain(org.get("domain")) != target_domain:
                continue
            loc = extract_structured_location(person.get("location"))
            person_li = person.get("linkedin_info") or {}
            org_li = org.get("linkedin_info") or {}
            pid = person.get("id")
            email = lookup_forager_personal_email(pid) if (ENABLE_PAID_CONTACT_LOOKUPS and pid) else None
            phone = lookup_forager_phone(pid) if (ENABLE_PAID_CONTACT_LOOKUPS and pid) else None
            candidates.append({
                "person_id": pid,
                "first_name": person.get("first_name"),
                "last_name": person.get("last_name"),
                "full_name": person.get("full_name"),
                "job_title": role.get("role_title") or job_title,
                "company": org.get("name") or comp_props.get("name"),
                "company_domain": target_domain,
                "linkedin_url": person_li.get("public_profile_url"),
                "company_linkedin_url": org_li.get("public_profile_url") or comp_props.get("linkedin_company_page"),
                "city": loc["city"],
                "state": loc["state"],
                "country": loc["country"],
                "description": person.get("description") or role.get("description"),
                "email": email,
                "phone": phone,
            })

    synced = []
    for item in candidates[:limit]:
        first_name = (item.get("first_name") or "").strip()
        last_name = (item.get("last_name") or "").strip()
        full_name = (item.get("full_name") or f"{first_name} {last_name}").strip()
        if not first_name and full_name:
            parts = full_name.split()
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not first_name:
            continue

        props = {
            "firstname": first_name,
            "lastname": last_name,
            "jobtitle": item.get("job_title"),
            "company": item.get("company") or comp_props.get("name"),
            "website": f"https://{target_domain}",
            "hs_linkedin_url": item.get("linkedin_url"),
            "company_linkedin_url": item.get("company_linkedin_url"),
            "linkedinbio": item.get("description"),
            "city": item.get("city"),
            "state": item.get("state"),
            "country": item.get("country"),
            "email": item.get("email"),
            "phone": item.get("phone"),
        }
        props = {k: v for k, v in props.items() if v is not None and v != ""}

        existing_id = None
        if props.get("hs_linkedin_url"):
            search = hubspot_request(
                "POST",
                "/crm/v3/objects/contacts/search",
                json={
                    "filterGroups": [{
                        "filters": [{
                            "propertyName": "hs_linkedin_url",
                            "operator": "EQ",
                            "value": props["hs_linkedin_url"],
                        }]
                    }],
                    "properties": ["firstname", "lastname", "hs_linkedin_url"],
                    "limit": 1,
                },
            )
            if search.get("results"):
                existing_id = str(search["results"][0]["id"])

        if not existing_id and props.get("email"):
            search = hubspot_request(
                "POST",
                "/crm/v3/objects/contacts/search",
                json={
                    "filterGroups": [{
                        "filters": [{
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": props["email"],
                        }]
                    }],
                    "properties": ["email"],
                    "limit": 1,
                },
            )
            if search.get("results"):
                existing_id = str(search["results"][0]["id"])

        if existing_id:
            hubspot_request("PATCH", f"/crm/v3/objects/contacts/{existing_id}", json={"properties": props})
            contact_id = existing_id
            action = "updated"
        else:
            created_rec = hubspot_request("POST", "/crm/v3/objects/contacts", json={"properties": props})
            contact_id = str(created_rec.get("id"))
            action = "created"

        if contact_id:
            hubspot_request(
                "PUT",
                f"/crm/v4/objects/contacts/{contact_id}/associations/default/companies/{company_id}",
            )
            synced.append({"contact_id": contact_id, "name": full_name, "job_title": props.get("jobtitle"), "action": action})

    return {
        "status": "completed",
        "job_title_filter": job_title,
        "count": len(synced),
        "contacts": synced,
        "forager_called": forager_called,
    }


def enrich_contact_record(contact_id: str, force_live: bool = False) -> dict:
    """Task 2 & 5: Enrich an individual HubSpot Contact with all required Forager fields."""
    contact_record = hubspot_request(
        "GET",
        f"/crm/v3/objects/contacts/{contact_id}",
        params={
            "properties": (
                "firstname,lastname,email,phone,mobilephone,jobtitle,company,"
                "website,hs_linkedin_url,company_linkedin_url,linkedinbio,city,state,country"
            )
        },
    )
    current = contact_record.get("properties") or {}
    first_name = (current.get("firstname") or "").strip()
    last_name = (current.get("lastname") or "").strip()
    target_name = " ".join(x for x in (first_name, last_name) if x).casefold()
    linkedin_url = (current.get("hs_linkedin_url") or "").strip()
    job_title = (current.get("jobtitle") or "").strip()
    company_domain = normalize_domain(current.get("website"))

    if not company_domain:
        associations = hubspot_request(
            "GET",
            f"/crm/v4/objects/contacts/{contact_id}/associations/companies",
            params={"limit": 10},
        )
        company_ids = [str(x.get("toObjectId")) for x in associations.get("results", []) if x.get("toObjectId")]
        for cid in company_ids:
            comp_rec = hubspot_request("GET", f"/crm/v3/objects/companies/{cid}", params={"properties": "domain"})
            dom = normalize_domain((comp_rec.get("properties") or {}).get("domain"))
            if dom:
                company_domain = dom
                break

    # 1. Check local cache first (0 credits) if matching by LinkedIn URL or name in prepared_contacts.json
    if not force_live:
        for cached in load_prepared_contacts():
            cached_li = (cached.get("linkedin_url") or "").strip().rstrip("/")
            curr_li = linkedin_url.rstrip("/")
            cached_name = (cached.get("full_name") or "").strip().casefold()
            if (curr_li and cached_li and curr_li == cached_li) or (target_name and cached_name == target_name):
                props = {
                    "firstname": cached.get("first_name"),
                    "lastname": cached.get("last_name"),
                    "jobtitle": cached.get("job_title") or job_title,
                    "company": cached.get("company"),
                    "website": f"https://{cached.get('company_domain')}" if cached.get("company_domain") else None,
                    "hs_linkedin_url": cached.get("linkedin_url"),
                    "company_linkedin_url": cached.get("company_linkedin_url"),
                    "linkedinbio": cached.get("description"),
                    "city": cached.get("city"),
                    "state": cached.get("state"),
                    "country": cached.get("country"),
                    "email": cached.get("email"),
                    "phone": cached.get("phone"),
                }
                props = {k: v for k, v in props.items() if v is not None and v != ""}
                res = hubspot_request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json={"properties": props})
                return {
                    "status": "enriched",
                    "contact_id": contact_id,
                    "updated_properties": list(props.keys()),
                    "source": "local_cache",
                    "forager_called": False,
                    "hubspot_result_id": res.get("id"),
                }

    # 2. Live Forager search fallback
    if not company_domain:
        return {
            "status": "skipped",
            "contact_id": contact_id,
            "reason": "Contact requires a company domain (website or associated company) for Forager lookup",
            "forager_called": False,
        }

    search_role = job_title or DEFAULT_ROLE_FILTER
    people = find_forager_people(company_domain, search_role)
    match = None
    for role in people:
        person = role.get("person") or {}
        full_name = (person.get("full_name") or "").strip().casefold()
        person_li = ((person.get("linkedin_info") or {}).get("public_profile_url") or "").rstrip("/")
        if (linkedin_url and person_li == linkedin_url.rstrip("/")) or (target_name and full_name == target_name):
            match = role
            break

    if not match:
        return {
            "status": "no_match",
            "contact_id": contact_id,
            "company_domain": company_domain,
            "job_title_searched": search_role,
            "forager_called": True,
        }

    person = match.get("person") or {}
    org = match.get("organization") or {}
    loc = extract_structured_location(person.get("location"))
    person_li = person.get("linkedin_info") or {}
    org_li = org.get("linkedin_info") or {}
    pid = person.get("id")

    email = lookup_forager_personal_email(pid) if (ENABLE_PAID_CONTACT_LOOKUPS and pid and not current.get("email")) else None
    phone = lookup_forager_phone(pid) if (ENABLE_PAID_CONTACT_LOOKUPS and pid and not current.get("phone")) else None

    properties = {
        "firstname": person.get("first_name"),
        "lastname": person.get("last_name"),
        "jobtitle": match.get("role_title") or job_title,
        "company": org.get("name"),
        "website": f"https://{normalize_domain(org.get('domain'))}" if org.get("domain") else None,
        "hs_linkedin_url": person_li.get("public_profile_url"),
        "company_linkedin_url": org_li.get("public_profile_url"),
        "linkedinbio": person.get("description") or match.get("description"),
        "city": loc["city"],
        "state": loc["state"],
        "country": loc["country"],
        "email": email,
        "phone": phone,
    }
    properties = {k: v for k, v in properties.items() if v is not None and v != ""}
    result = hubspot_request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json={"properties": properties})
    return {
        "status": "enriched",
        "contact_id": contact_id,
        "updated_properties": list(properties.keys()),
        "forager_called": True,
        "hubspot_result_id": result.get("id"),
    }


@app.get("/")
def root():
    return {
        "service": "Forager × HubSpot GTM Enrichment API",
        "status": "running",
        "endpoints": [
            "GET /health",
            "GET /contacts/filter?job_title=Engineer",
            "POST /companies/{company_id}/enrich",
            "POST /companies/{company_id}/find-contacts?job_title=Engineer&limit=5",
            "POST /contacts/{contact_id}/enrich",
            "POST /webhooks/hubspot",
        ],
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/contacts/filter")
def filter_contacts(
    job_title: str = Query(..., min_length=2, description="Filter contacts by job title substring"),
    domain: Optional[str] = Query(None, description="Optional company domain filter (e.g. openai.com)"),
    live: bool = Query(False, description="Set true to query Forager API live (costs 1 credit)"),
):
    """Task 3: Discover / filter contacts at a company by job title."""
    if live and domain:
        raw_roles = find_forager_people(normalize_domain(domain), job_title)
        matches = []
        for r in raw_roles:
            p = r.get("person") or {}
            o = r.get("organization") or {}
            loc = extract_structured_location(p.get("location"))
            matches.append({
                "person_id": p.get("id"),
                "full_name": p.get("full_name"),
                "job_title": r.get("role_title"),
                "company": o.get("name"),
                "company_domain": o.get("domain"),
                "linkedin_url": (p.get("linkedin_info") or {}).get("public_profile_url"),
                "company_linkedin_url": (o.get("linkedin_info") or {}).get("public_profile_url"),
                "city": loc["city"],
                "state": loc["state"],
                "country": loc["country"],
            })
        return {"job_title_filter": job_title, "source": "forager_live", "count": len(matches), "contacts": matches}

    contacts = load_prepared_contacts()
    if not contacts:
        raise HTTPException(status_code=404, detail="Prepared contacts dataset not found")

    matches = [
        c for c in contacts
        if job_title.casefold() in (c.get("job_title") or "").casefold()
        and (not domain or normalize_domain(c.get("company_domain")) == normalize_domain(domain))
    ]
    return {"job_title_filter": job_title, "source": "cached_dataset", "count": len(matches), "contacts": matches}


@app.post("/companies/{company_id}/enrich")
def enrich_company(company_id: str, force_live: bool = Query(False)):
    """Task 1: Enrich a HubSpot company record with Forager firmographic details."""
    return enrich_company_record(company_id, force_live=force_live)


@app.post("/companies/{company_id}/find-contacts")
def discover_company_contacts(
    company_id: str,
    job_title: str = Query(DEFAULT_ROLE_FILTER, description="Job title filter for contact discovery"),
    limit: int = Query(5, ge=1, le=25),
    force_live: bool = Query(False),
):
    """Task 3: Discover contacts at a HubSpot company filtered by job title and sync them to HubSpot."""
    return find_and_sync_company_contacts(company_id, job_title=job_title, limit=limit, force_live=force_live)


@app.post("/contacts/{contact_id}/enrich")
def enrich_contact(contact_id: str, force_live: bool = Query(False)):
    """Task 2: Enrich a HubSpot contact record with all required Forager fields."""
    return enrich_contact_record(contact_id, force_live=force_live)


@app.post("/webhooks/hubspot")
async def hubspot_webhook(
    request: Request,
    events: list[dict] | dict = Body(
        default=[
            {
                "subscriptionType": "company.creation",
                "objectId": 357017650890,
            }
        ],
        description="HubSpot webhook event batch or single event object",
    ),
    job_title: str = Query(
        DEFAULT_ROLE_FILTER,
        description="Default job title filter when discovering new contacts",
    ),
):
    """
    Task 4 & 5: Live Webhook Receiver for HubSpot Company & Contact creation events.
    - When a company event fires: enriches the company; if contacts already exist in HubSpot,
      enriches them; if none exist, discovers and creates them using job-title filtering.
    - When a contact event fires: enriches that contact.
    """
    if HUBSPOT_WEBHOOK_SECRET:
        supplied_secret = request.headers.get("X-Webhook-Secret", "")
        if supplied_secret != HUBSPOT_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    if isinstance(events, dict):
        events = [events]
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="Expected a HubSpot event object or event list")

    outcomes = []
    for event in events:
        if not isinstance(event, dict):
            outcomes.append({"status": "skipped", "reason": "Each event must be a JSON object"})
            continue

        object_type = str(event.get("subscriptionType") or event.get("objectType") or "").lower()
        object_id = event.get("objectId") or event.get("object_id")
        if not object_id:
            outcomes.append({"status": "skipped", "reason": "Event has no objectId"})
            continue

        try:
            if "company" in object_type:
                company_id = str(object_id)
                company_result = enrich_company_record(company_id)
                existing_contact_ids = get_company_contacts(company_id)

                discovery_result = None
                contact_results = []

                if existing_contact_ids:
                    for cid in existing_contact_ids:
                        try:
                            contact_results.append(enrich_contact_record(cid))
                        except HTTPException as exc:
                            contact_results.append({"status": "error", "contact_id": cid, "detail": exc.detail})
                else:
                    discovery_result = find_and_sync_company_contacts(
                        company_id, job_title=job_title, limit=5
                    )

                outcomes.append({
                    "event": object_type,
                    "company_id": company_id,
                    "company_result": company_result,
                    "existing_contacts_count": len(existing_contact_ids),
                    "existing_contacts_enriched": contact_results,
                    "new_contacts_discovered": discovery_result,
                    "status": "processed",
                })
            elif "contact" in object_type:
                contact_id = str(object_id)
                contact_result = enrich_contact_record(contact_id)
                outcomes.append({
                    "event": object_type,
                    "contact_id": contact_id,
                    "contact_result": contact_result,
                    "status": "processed",
                })
            else:
                outcomes.append({
                    "status": "ignored",
                    "event": object_type or "unknown",
                    "reason": "Only company and contact events are handled",
                })
        except HTTPException as exc:
            outcomes.append({
                "status": "error",
                "event": object_type or "unknown",
                "object_id": str(object_id),
                "detail": exc.detail,
            })

    return {"received": len(events), "outcomes": outcomes}
