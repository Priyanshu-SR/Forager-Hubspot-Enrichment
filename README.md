# Forager × HubSpot GTM Enrichment Service

Custom Python (FastAPI) data-enrichment automation connecting **Forager API v2** with **HubSpot CRM**, built for the **ONEGTM LAB — AI Automation Engineer** evaluation.

---

## 1. Scope of Work & Architecture

| # | Task | Endpoint / Component | Description |
|---|------|----------------------|-------------|
| 1 | **Enrich Companies** | `POST /companies/{company_id}/enrich` | Pulls firmographic details from Forager (`/datastorage/organization_search/`) and updates HubSpot (`description`, `numberofemployees`, `forager_revenue`, `industry`, `linkedin_company_page`, `city`, `state`, `country`, `zip`, `founded_year`). |
| 2 | **Enrich Contacts** | `POST /contacts/{contact_id}/enrich` | Enriches a HubSpot contact with required fields (`firstname`, `lastname`, `hs_linkedin_url`, `jobtitle`, `company`, `website`, `company_linkedin_url`, `email`, `phone`, `city`, `state`, `country`, and `linkedinbio`). |
| 3 | **Find Contacts at a Company (Job-Title Filtered)** | `GET /contacts/filter?job_title=...`<br>`POST /companies/{company_id}/find-contacts?job_title=...` | Discovers current employees at a company via Forager (`/datastorage/person_role_search/`), filters by `job_title`, parses structured OpenStreetMap locations (`city`, `state`, `country`), and associates them with the HubSpot Company. |
| 4 | **Company Webhook Automation** | `POST /webhooks/hubspot` (`company.creation`) | Triggered when a company is added to HubSpot. Enriches the company; if associated contacts already exist in HubSpot, enriches them; if none exist, discovers and associates new contacts filtered by job title. |
| 5 | **Contact Webhook Automation** | `POST /webhooks/hubspot` (`contact.creation`) | Triggered when a contact is added to HubSpot. Enriches the contact with Forager profile, location, employer, and contact details. |

---

## 2. Required Fields — HubSpot Property Mapping

### Enriched Contact Fields
* **First & Last Name**: `firstname`, `lastname`
* **Person LinkedIn URL**: `hs_linkedin_url` (`person.linkedin_info.public_profile_url`)
* **Job Title**: `jobtitle` (`role_title`)
* **Employer Name, Domain & Company LinkedIn URL**: `company`, `website`, and custom contact property `company_linkedin_url` (`organization.linkedin_info.public_profile_url`)
* **Email (if available)**: `email` (via `/datastorage/person_contacts_lookup/personal_emails/` & `/work_emails/`)
* **Phone (if available)**: `phone` (via `/datastorage/person_contacts_lookup/phone_numbers/`)
* **Structured Location (City, State, Country)**: `city`, `state`, `country` extracted from `person.location.osm_locations` (`place_type` hierarchy)
* **LinkedIn "About" / Bio (Nice-to-Have)**: Synced to `linkedinbio` (`person.description`)

### Enriched Company Fields
* **Company Name & Domain**: `name`, `domain`, `website`
* **Description**: `description`
* **Revenue**: Custom property `forager_revenue` (`finance_info.revenue`, e.g., `$1,600,000,000` for OpenAI)
* **Headcount**: `numberofemployees` (`employees_amount`, e.g., `10,480` for OpenAI)
* **Industry & LinkedIn Page**: `industry`, `linkedin_company_page`
* **HQ Address**: `city`, `state`, `country`, `zip`

---

## 3. Deliverable #4: Interesting Extra Details Forager Surfaces (Flagged for GTM Discussion)

During development and inspection of the raw Forager payloads (`forager_people.json` and `/datastorage/` schemas), several high-signal fields surfaced beyond the core required fields. Below are the most valuable fields we should discuss adding to HubSpot for GTM scoring and AI-personalized outbound:

### A. Person-Level Signals
1. **LinkedIn "About" Summary (`person.description`) & Role Description (`role.description`)** *(Included in `linkedinbio`)*
   * **What Forager returns**: Both the person's top-level LinkedIn "About" bio (e.g., Mandy Bo's 20+ years in distributed systems, RAG, and LLMs) and their specific role responsibilities at the company (e.g., Siphesihle Maseko's description of working on RLHF & human data evaluation for ChatGPT/GPT-V).
   * **GTM Value**: Ideal input for an LLM step to generate hyper-personalized first lines in outbound emails or classify technical persona focus.
2. **LinkedIn Headline (`person.headline`)**
   * **What Forager returns**: The user's self-written tagline (e.g., *"Senior AI Engineer | Applied ML & Generative AI systems"* or *"Software Engineer - Backend, Human Data"*).
   * **GTM Value**: Often more specific and up-to-date than the standardized `role_title`, revealing team/product area (e.g., Growth, Backend, Applied ML).
3. **Skills Array (`person.skills[].name`)**
   * **What Forager returns**: Up to 20 structured skill tags per person (e.g., `"Large Language Models (LLMs)"`, `"Retrieval-Augmented Generation (RAG)"`, `"Cloud-Native Systems (AWS, Kubernetes)"`).
   * **GTM Value**: Enables technographic persona filtering and technical champion routing when selling developer or AI infrastructure tools.
4. **Role Tenure & Start Date (`start_date`, `end_date`, `is_current`)**
   * **What Forager returns**: Exact role start date (e.g., `"2023-01-01"`) and current employment status boolean.
   * **GTM Value**: Allows triggering "New in Role" (<90 days) outbound plays or identifying long-tenured decision-makers.
5. **Profile Freshness (`person.date_updated`) & Photo (`person.photo`)**
   * **What Forager returns**: ISO timestamp of the last Forager verification refresh and profile image URL.
   * **GTM Value**: Helps measure data decay and schedule periodic re-enrichment only for stale CRM records.

### B. Company-Level & Intent Signals
1. **Domain Rank (`organization.domain_rank`) & Keywords (`organization.keywords`)**
   * **What Forager returns**: Web traffic rank (e.g., `242` for `openai.com`) and structured category tags (`"Artificial Intelligence"`, `"Machine Learning"`).
   * **GTM Value**: Useful for automated ICP tiering when employee headcount or revenue is undisclosed on smaller startups.
2. **Employee Size Band (`organization.employees_range`) + Exact Count (`employees_amount`)**
   * **What Forager returns**: Both the LinkedIn bracket (`"1001 - 5000"`) and exact scraped count (`10480`).
3. **Real-Time Buying Intent Arrays (`found_funding_events`, `found_job_post_events`, `found_simple_events`)**
   * **What Forager returns**: Recent funding rounds, active job postings, and product launch events (e.g., Product Hunt / SEC Form C filings), plus dedicated endpoints for `/datastorage/job_search/` and organization technology lookups.
   * **GTM Value**: Can trigger automated outbound workflows in HubSpot the moment a target account raises capital or hires for relevant engineering roles.

---

## 4. Setup & Running Locally

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt