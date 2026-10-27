import json


def extract_structured_location(location_obj: dict) -> dict:
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


def main():
    with open("forager_people.json", "r", encoding="utf-8") as file:
        records = json.load(file)

    #Preserve any existing emails/phones if prepared_contacts.json already had them
    existing_by_id = {}
    try:
        with open("prepared_contacts.json", "r", encoding="utf-8") as existing_file:
            for item in json.load(existing_file):
                if item.get("person_id"):
                    existing_by_id[item["person_id"]] = item
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    contacts = []

    for item in records:
        person = item.get("person") or {}
        organization = item.get("organization") or {}
        person_linkedin = person.get("linkedin_info") or {}
        company_linkedin = organization.get("linkedin_info") or {}
        location = person.get("location") or {}

        # Only consider current roles at the official OpenAI organization (exclude fake "CHAT GPT" page)
        if item.get("is_current") is not True:
            continue
        if (organization.get("domain") or "").lower() != "openai.com":
            continue
        if (organization.get("name") or "").strip().lower() != "openai":
            continue

        name = person.get("full_name")
        if not name:
            continue

        person_id = person.get("id")
        prev = existing_by_id.get(person_id, {})
        loc_data = extract_structured_location(location)
        skills = [s.get("name") for s in (person.get("skills") or []) if s.get("name")]

        contacts.append({
            "person_id": person_id,
            "first_name": person.get("first_name"),
            "last_name": person.get("last_name"),
            "full_name": name,
            "job_title": item.get("role_title"),
            "company": organization.get("name"),
            "company_domain": organization.get("domain"),
            "linkedin_url": person_linkedin.get("public_profile_url"),
            "linkedin_public_identifier": person_linkedin.get("public_identifier"),
            "company_linkedin_url": company_linkedin.get("public_profile_url"),
            "city": loc_data["city"],
            "state": loc_data["state"],
            "country": loc_data["country"],
            "location": loc_data["raw_location"],
            "headline": person.get("headline"),
            "description": person.get("description") or item.get("description"),
            "role_description": item.get("description"),
            "skills": skills[:10],
            "start_date": item.get("start_date"),
            "is_current": item.get("is_current"),
            "email": prev.get("email"),
            "phone": prev.get("phone"),
        })

    with open("prepared_contacts.json", "w", encoding="utf-8") as file:
        json.dump(contacts, file, indent=2, ensure_ascii=False)

    print(f"Prepared {len(contacts)} clean OpenAI contacts:\n")
    for c in contacts:
        print(
            f"- {c['full_name']} (ID: {c['person_id']}) | {c['job_title']} | "
            f"City: {c['city']}, State: {c['state']}, Country: {c['country']}"
        )


if __name__ == "__main__":
    main()