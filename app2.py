
import re
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
import pandas as pd
import streamlit as st


# ============================================================
# APP CONFIG
# ============================================================

st.set_page_config(
    page_title="360° Account Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# API
# ============================================================

SERPER_URL = "https://google.serper.dev/search"
BUILTWITH_URL = "https://api.builtwith.com/v23/api.json"
SIGNALHIRE_BASE_URL = "https://www.signalhire.com/api/v1"
SIGNALHIRE_SEARCH_URL = f"{SIGNALHIRE_BASE_URL}/candidate/search"
SIGNALHIRE_CREDITS_URL = f"{SIGNALHIRE_BASE_URL}/credits"


# ============================================================
# PERSONA LIBRARY
# ============================================================

PERSONA_GROUPS = {
    "Technology Leadership": [
        "CTO",
        "Chief Technology Officer",
        "VP Technology",
        "Vice President Technology",
        "Head of Technology",
        "Technology Director",
    ],

    "IT Leadership": [
        "CIO",
        "Chief Information Officer",
        "VP IT",
        "Vice President IT",
        "Head of IT",
        "IT Director",
        "Director IT",
        "IT Manager",
    ],

    "Security Leadership": [
        "CISO",
        "Chief Information Security Officer",
        "Chief Security Officer",
        "Head of Cyber Security",
        "Head of Cybersecurity",
        "Head of Information Security",
        "Cybersecurity Head",
        "Information Security Manager",
    ],

    "Infrastructure": [
        "Head of Infrastructure",
        "Infrastructure Director",
        "Infrastructure Manager",
        "System Administrator",
        "IT Infrastructure Manager",
    ],
}


DEFAULT_PERSONAS = [
    item
    for group in PERSONA_GROUPS.values()
    for item in group
]


# ============================================================
# SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "account": {},
    "company": {},
    "technology": {},
    "personas": pd.DataFrame(),
    "approved": pd.DataFrame(),
    "signalhire_credits": None,
    "signalhire_enriched": {},
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>

    .main-title {
        font-size: 36px;
        font-weight: 800;
        color: #111827;
    }

    .subtitle {
        color: #6b7280;
        font-size: 16px;
        margin-bottom: 25px;
    }

    .card {
        padding: 18px;
        border-radius: 14px;
        border: 1px solid #e5e7eb;
        background: white;
        margin-bottom: 15px;
    }

    .verified {
        background: #f0fdf4;
        border: 1px solid #86efac;
    }

    .review {
        background: #fffbeb;
        border: 1px solid #fcd34d;
    }

    .rejected {
        background: #fef2f2;
        border: 1px solid #fca5a5;
    }

    .info {
        background: #eff6ff;
        border: 1px solid #93c5fd;
    }

    .metric-box {
        padding: 15px;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        text-align: center;
        background: white;
    }

    .contact-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        margin-right: 6px;
        margin-bottom: 6px;
    }

    .badge-work-email {
        background-color: #dbeafe;
        color: #1e40af;
        border: 1px solid #bfdbfe;
    }

    .badge-personal-email {
        background-color: #f3e8ff;
        color: #6b21a8;
        border: 1px solid #e9d5ff;
    }

    .badge-phone {
        background-color: #dcfce7;
        color: #15803d;
        border: 1px solid #bbf7d0;
    }

    .badge-role {
        background-color: #fef3c7;
        color: #92400e;
        border: 1px solid #fde68a;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# GENERIC HELPERS
# ============================================================

def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_company_name(name: str) -> str:

    value = clean(name).lower()

    remove_terms = [
        "private limited",
        "pvt limited",
        "pvt ltd",
        "pvt. ltd.",
        "limited",
        "ltd",
        "llp",
        "incorporated",
        "inc.",
        "inc",
        "corporation",
        "corp",
        "company",
        "co.",
    ]

    for term in remove_terms:
        value = value.replace(term, " ")

    value = re.sub(r"[^a-z0-9 ]", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_domain(domain: str) -> str:

    domain = clean(domain)

    domain = re.sub(
        r"^https?://",
        "",
        domain,
        flags=re.I,
    )

    domain = domain.split("/")[0].lower()

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


def unique(values: List[str]) -> List[str]:

    result = []

    for value in values:

        value = clean(value)

        if value and value not in result:
            result.append(value)

    return result


def get_secret(key: str, default: str = "") -> str:
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default


def is_date_in_past(date_str: Any) -> bool:
    """
    Returns True if an end date is provided and has already passed.
    Returns False for None, empty, 'present', 'current', 'ongoing', or future dates.
    """
    if not date_str:
        return False
    d = clean(date_str).lower()
    if not d or d in {"present", "current", "now", "ongoing", "none", "null"}:
        return False
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            now = datetime.now()
        return dt < now
    except Exception:
        pass
    years = re.findall(r"\b(19\d\d|20\d\d)\b", d)
    if years:
        from datetime import datetime
        end_year = int(years[-1])
        now_year = datetime.now().year
        if end_year < now_year:
            return True
        elif end_year == now_year:
            months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            for idx, m in enumerate(months, start=1):
                if m in d:
                    if idx < datetime.now().month:
                        return True
    return False


def safe_json(data: Any) -> str:

    try:
        return json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    except Exception:
        return str(data)


# ============================================================
# HTTP
# ============================================================

def api_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 45,
) -> Dict[str, Any]:

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        params=params,
        json=payload,
        timeout=timeout,
    )

    if not response.ok:

        try:
            body = response.json()
        except Exception:
            body = response.text

        raise RuntimeError(
            f"HTTP {response.status_code}: {body}"
        )

    try:
        return response.json()
    except Exception:
        return {"raw_response": response.text}


# ============================================================
# SERPER
# ============================================================

def serper_search(
    query: str,
    api_key: str,
    num: int = 10,
) -> Dict[str, Any]:

    if not api_key:
        raise RuntimeError(
            "Serper API key is missing."
        )

    return api_request(
        "POST",
        SERPER_URL,
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        },
        payload={
            "q": query,
            "num": num,
        },
        timeout=35,
    )


# ============================================================
# DOMAIN DISCOVERY
# ============================================================

def find_company_domain(
    company: str,
    location: str,
    serper_key: str,
) -> Dict[str, Any]:

    queries = [
        f'"{company}" "{location}" official website',
        f'"{company}" official website',
    ]

    blocked = {
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "wikipedia.org",
        "zaubacorp.com",
        "tofler.in",
        "builtwith.com",
    }

    evidence = []

    for query in queries:

        result = serper_search(
            query,
            serper_key,
            10,
        )

        organic = result.get(
            "organic",
            [],
        )

        evidence.append({
            "query": query,
            "results": organic,
        })

        for item in organic:

            link = clean(
                item.get("link")
            )

            if not link:
                continue

            match = re.search(
                r"https?://([^/]+)",
                link,
                re.I,
            )

            if not match:
                continue

            domain = normalize_domain(
                match.group(1)
            )

            if domain in blocked:
                continue

            return {
                "domain": domain,
                "confidence": "Search-supported",
                "evidence": evidence,
            }

    return {
        "domain": "",
        "confidence": "Not resolved",
        "evidence": evidence,
    }


# ============================================================
# COMPANY SOURCE EVIDENCE
# ============================================================

def company_source_search(
    company: str,
    location: str,
    source: str,
    serper_key: str,
) -> Dict[str, Any]:

    if source == "Zauba":
        domain = "zaubacorp.com"
    else:
        domain = "tofler.in"

    query = (
        f'"{company}" "{location}" '
        f'site:{domain}'
    )

    result = serper_search(
        query,
        serper_key,
        10,
    )

    records = []

    for item in result.get(
        "organic",
        [],
    ):

        link = clean(
            item.get("link")
        )

        if domain not in link.lower():
            continue

        records.append({
            "title": clean(
                item.get("title")
            ),
            "url": link,
            "snippet": clean(
                item.get("snippet")
            ),
        })

    return {
        "source": source,
        "query": query,
        "status": (
            "Evidence Found"
            if records
            else "No Evidence Found"
        ),
        "records": records,
    }


# ============================================================
# BUILTWITH
# ============================================================

def builtwith_lookup(
    domain: str,
    api_key: str,
) -> Dict[str, Any]:

    if not domain:
        raise RuntimeError(
            "Company domain not found."
        )

    if not api_key:
        raise RuntimeError(
            "BuiltWith API key missing."
        )

    return api_request(
        "GET",
        BUILTWITH_URL,
        params={
            "KEY": api_key,
            "LOOKUP": domain,
        },
        timeout=60,
    )


def parse_builtwith(
    data: Dict[str, Any],
) -> Tuple[List[str], List[str]]:

    technologies = []
    categories = []

    def walk(value: Any):

        if isinstance(value, dict):

            for key, item in value.items():

                key_lower = key.lower()

                if isinstance(
                    item,
                    (dict, list),
                ):

                    if any(
                        x in key_lower
                        for x in [
                            "technology",
                            "technologies",
                            "tech",
                        ]
                    ):

                        walk_technology(item)

                    else:
                        walk(item)

                elif isinstance(item, str):

                    if any(
                        x in key_lower
                        for x in [
                            "technology",
                            "technologyname",
                        ]
                    ):
                        technologies.append(item)

                    if "category" in key_lower:
                        categories.append(item)

        elif isinstance(value, list):

            for item in value:
                walk(item)

    def walk_technology(value: Any):

        if isinstance(value, dict):

            for key, item in value.items():

                if key.lower() in {
                    "name",
                    "technology",
                    "tech",
                }:

                    if isinstance(
                        item,
                        str,
                    ):
                        technologies.append(item)

                walk_technology(item)

        elif isinstance(value, list):

            for item in value:
                walk_technology(item)

    walk(data)

    return (
        unique(technologies),
        unique(categories),
    )


# ============================================================
# SOLUTION FIT
# ============================================================

def determine_solution_fit(
    technologies: List[str],
    categories: List[str],
) -> List[str]:

    text = " ".join(
        technologies + categories
    ).lower()

    fit = []

    cloud = [
        "aws",
        "azure",
        "google cloud",
        "gcp",
        "kubernetes",
        "docker",
    ]

    security = [
        "crowdstrike",
        "sentinelone",
        "palo alto",
        "fortinet",
        "cloudflare",
        "okta",
        "firewall",
        "waf",
        "security",
        "identity",
    ]

    enterprise = [
        "sap",
        "oracle",
        "salesforce",
        "servicenow",
        "microsoft",
    ]

    data = [
        "snowflake",
        "databricks",
        "tableau",
        "power bi",
        "analytics",
        "database",
    ]

    if any(x in text for x in cloud):
        fit.append(
            "Cloud / Infrastructure"
        )

    if any(x in text for x in security):
        fit.append(
            "Cybersecurity / Security"
        )

    if any(x in text for x in enterprise):
        fit.append(
            "Enterprise Technology"
        )

    if any(x in text for x in data):
        fit.append(
            "Data / Analytics"
        )

    return fit


# ============================================================
# SIGNALHIRE
# ============================================================

def signalhire_get_credits(api_key: str) -> Optional[int]:
    if not api_key:
        return None
    try:
        res = requests.get(
            SIGNALHIRE_CREDITS_URL,
            headers={"apikey": api_key},
            timeout=15,
        )
        if res.ok:
            data = res.json()
            return data.get("credits")
    except Exception:
        pass
    return None


def signalhire_enrich_profiles(
    linkedin_urls: List[str],
    api_key: str,
    without_contacts: bool = False,
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    """
    Enriches candidates synchronously using SignalHire's withoutWaterfall mode.
    Returns list of candidate outcome objects:
    [{'item': '...', 'status': 'success'|'failed'|'credits_are_over', 'candidate': {...}}]
    """
    if not api_key:
        raise RuntimeError("SignalHire API key is missing.")

    clean_urls = unique([clean(u) for u in linkedin_urls if clean(u)])
    if not clean_urls:
        return []

    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "items": clean_urls[:100],
        "withoutWaterfall": True,
    }
    if without_contacts:
        payload["withoutContacts"] = True

    response = requests.post(
        SIGNALHIRE_SEARCH_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
    )

    if not response.ok:
        try:
            err = response.json()
        except Exception:
            err = response.text
        raise RuntimeError(f"SignalHire API HTTP {response.status_code}: {err}")

    try:
        data = response.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        raise RuntimeError(f"Failed to parse SignalHire JSON response: {exc}")


def parse_signalhire_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses a single SignalHire item result into structured persona details.
    """
    if not isinstance(item, dict):
        return {}

    status = clean(item.get("status"))
    url = clean(item.get("item"))

    if status != "success":
        return {
            "url": url,
            "status": status,
            "error": f"SignalHire status: {status}",
            "full_name": "",
            "headline": "",
            "summary": "",
            "location": "",
            "skills": [],
            "current_position": "",
            "current_company": "",
            "current_roles": [],
            "past_roles": [],
            "work_emails": [],
            "personal_emails": [],
            "all_emails": [],
            "work_phones": [],
            "mobile_phones": [],
            "all_phones": [],
            "raw_candidate": {},
        }

    candidate = item.get("candidate") or {}

    full_name = clean(candidate.get("fullName"))
    headline = clean(candidate.get("headLine"))
    summary = clean(candidate.get("summary"))

    # Locations
    locations = candidate.get("locations") or []
    loc_names = [clean(l.get("name")) for l in locations if isinstance(l, dict) and l.get("name")]
    location_str = ", ".join(loc_names)

    # Skills
    skills = candidate.get("skills") or []
    skills_list = [clean(s) for s in skills if clean(s)]

    # Contacts
    contacts = candidate.get("contacts") or []
    work_emails = []
    personal_emails = []
    other_emails = []
    work_phones = []
    mobile_phones = []
    other_phones = []

    for c in contacts:
        if not isinstance(c, dict):
            continue
        c_type = clean(c.get("type")).lower()
        val = clean(c.get("value"))
        sub_type = clean(c.get("subType")).lower()
        if not val:
            continue

        if c_type == "email":
            if sub_type == "work":
                work_emails.append(val)
            elif sub_type == "personal":
                personal_emails.append(val)
            else:
                other_emails.append(val)
        elif c_type == "phone":
            if "work" in sub_type:
                work_phones.append(val)
            elif "mobile" in sub_type:
                mobile_phones.append(val)
            else:
                other_phones.append(val)

    # Experience
    experiences = candidate.get("experience") or []
    current_roles = []
    past_roles = []

    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        pos = clean(exp.get("position"))
        comp = clean(exp.get("company"))
        is_cur = bool(exp.get("current", False))
        started = clean(exp.get("started"))
        ended = clean(exp.get("ended"))
        is_ended = is_date_in_past(ended) or (not is_cur and bool(ended))
        is_active = is_cur and not is_ended and (not ended or ended.lower() in {"present", "current", "now", "ongoing"})

        exp_item = {
            "position": pos,
            "company": comp,
            "current": is_cur,
            "is_active": is_active,
            "started": started,
            "ended": ended,
            "summary": clean(exp.get("summary")),
            "industry": clean(exp.get("industry")),
        }
        if is_active:
            current_roles.append(exp_item)
        else:
            past_roles.append(exp_item)

    cur_pos = current_roles[0]["position"] if current_roles else ""
    cur_comp = current_roles[0]["company"] if current_roles else ""

    return {
        "url": url,
        "status": "success",
        "full_name": full_name,
        "headline": headline,
        "summary": summary,
        "location": location_str,
        "skills": skills_list,
        "current_position": cur_pos,
        "current_company": cur_comp,
        "current_roles": current_roles,
        "past_roles": past_roles,
        "work_emails": unique(work_emails),
        "personal_emails": unique(personal_emails),
        "all_emails": unique(work_emails + personal_emails + other_emails),
        "work_phones": unique(work_phones),
        "mobile_phones": unique(mobile_phones),
        "all_phones": unique(work_phones + mobile_phones + other_phones),
        "raw_candidate": candidate,
    }


def validate_signalhire_experiences(
    experiences: List[Dict[str, Any]],
    target_company: str,
    requested_persona: str,
) -> Dict[str, Any]:
    """
    Strict ground-truth validation:
    Only accepts candidates presently working at target organisation.
    Rejects all former employees whose employment has ended.
    """
    norm_target = normalize_company_name(target_company)
    if not norm_target or not experiences:
        return {
            "status": "REJECTED",
            "score": 0.0,
            "reason": f"No experience records found for '{target_company}'.",
            "current_position": "",
            "current_company": "",
        }

    target_active_roles = []
    target_past_roles = []
    other_active_roles = []
    other_past_roles = []

    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        comp = clean(exp.get("company", ""))
        comp_norm = normalize_company_name(comp)
        pos = clean(exp.get("position", ""))
        is_cur_flag = bool(exp.get("current", False))
        started = clean(exp.get("started", ""))
        ended = clean(exp.get("ended", ""))

        is_ended = is_date_in_past(ended) or (not is_cur_flag and bool(ended))
        is_active = is_cur_flag and not is_ended and (not ended or ended.lower() in {"present", "current", "now", "ongoing"})

        is_target = norm_target in comp_norm or comp_norm in norm_target

        role_info = {
            "company": comp,
            "position": pos,
            "current": is_cur_flag,
            "started": started,
            "ended": ended,
            "is_active": is_active,
        }

        if is_target:
            if is_active:
                target_active_roles.append(role_info)
            else:
                target_past_roles.append(role_info)
        else:
            if is_active:
                other_active_roles.append(role_info)
            else:
                other_past_roles.append(role_info)

    # 1. Confirmed active ongoing role at target company
    if target_active_roles:
        primary_role = target_active_roles[0]
        cur_pos = primary_role["position"]
        cur_comp = primary_role["company"]
        t_score = title_score(requested_persona, cur_pos)

        if t_score >= 50:
            return {
                "status": "VERIFIED",
                "score": 98.0,
                "reason": f"CONFIRMED PRESENT EMPLOYEE: Live SignalHire records confirm active ongoing employment as '{cur_pos}' at '{cur_comp}' (no end date).",
                "current_position": cur_pos,
                "current_company": cur_comp,
            }
        else:
            return {
                "status": "REVIEW",
                "score": 70.0,
                "reason": f"ACTIVE AT TARGET (Title mismatch): Active at '{cur_comp}', but role '{cur_pos}' does not strongly match requested persona '{requested_persona}'.",
                "current_position": cur_pos,
                "current_company": cur_comp,
            }

    # 2. Target company only in past roles -> FORMER EMPLOYEE
    if target_past_roles:
        last_past = target_past_roles[0]
        end_str = f" (ended {last_past.get('ended', 'past')[:10]})" if last_past.get("ended") else ""
        cur_where = f"Currently employed at '{other_active_roles[0]['company']}'" if other_active_roles else "No longer with target organisation"
        return {
            "status": "REJECTED",
            "score": 0.0,
            "reason": f"FORMER EMPLOYEE: Employment at '{target_company}' ended{end_str}. {cur_where}. Excluded from results.",
            "current_position": other_active_roles[0]["position"] if other_active_roles else "",
            "current_company": other_active_roles[0]["company"] if other_active_roles else "",
        }

    # 3. Not found in experience records
    cur_where = f"Currently at '{other_active_roles[0]['company']}'" if other_active_roles else "Not employed at target organisation"
    return {
        "status": "REJECTED",
        "score": 0.0,
        "reason": f"Target organisation '{target_company}' not found in candidate experience history. {cur_where}.",
        "current_position": other_active_roles[0]["position"] if other_active_roles else "",
        "current_company": other_active_roles[0]["company"] if other_active_roles else "",
    }


def apply_signalhire_enrichment(
    df: pd.DataFrame,
    enriched_results: List[Dict[str, Any]],
    target_company: str,
) -> pd.DataFrame:
    """
    Merges SignalHire profile & contact data into the persona DataFrame.
    Improves verification accuracy using actual employment records.
    Strictly excludes former employees.
    """
    if df.empty or not enriched_results:
        return df

    parsed_map = {}
    for item in enriched_results:
        parsed = parse_signalhire_candidate(item)
        url = clean(parsed.get("url")).split("?")[0].rstrip("/").lower()
        if url:
            parsed_map[url] = parsed

    new_cols = [
        "Work Emails",
        "Personal Emails",
        "All Emails",
        "Work Phones",
        "Mobile Phones",
        "All Phones",
        "SignalHire Title",
        "SignalHire Company",
        "SignalHire Headline",
        "SignalHire Skills",
        "SignalHire Status",
    ]
    for col in new_cols:
        if col not in df.columns:
            df[col] = ""

    for idx, row in df.iterrows():
        ln_url = clean(row.get("LinkedIn")).split("?")[0].rstrip("/").lower()
        if ln_url not in parsed_map:
            continue

        p = parsed_map[ln_url]
        status = p.get("status")
        df.at[idx, "SignalHire Status"] = status

        if status == "success":
            df.at[idx, "Work Emails"] = ", ".join(p.get("work_emails", []))
            df.at[idx, "Personal Emails"] = ", ".join(p.get("personal_emails", []))
            df.at[idx, "All Emails"] = ", ".join(p.get("all_emails", []))
            df.at[idx, "Work Phones"] = ", ".join(p.get("work_phones", []))
            df.at[idx, "Mobile Phones"] = ", ".join(p.get("mobile_phones", []))
            df.at[idx, "All Phones"] = ", ".join(p.get("all_phones", []))

            cur_pos = p.get("current_position", "")
            cur_comp = p.get("current_company", "")
            df.at[idx, "SignalHire Title"] = cur_pos
            df.at[idx, "SignalHire Company"] = cur_comp
            df.at[idx, "SignalHire Headline"] = p.get("headline", "")
            df.at[idx, "SignalHire Skills"] = ", ".join(p.get("skills", [])[:10])

            if p.get("full_name") and not clean(row.get("Name")):
                df.at[idx, "Name"] = p.get("full_name")

            # Ground truth verification using validate_signalhire_experiences
            raw_exps = p.get("raw_candidate", {}).get("experience", [])
            val_res = validate_signalhire_experiences(
                raw_exps,
                target_company,
                clean(row.get("Requested Persona")),
            )

            df.at[idx, "Verification Status"] = val_res["status"]
            df.at[idx, "Verification Score"] = val_res["score"]
            df.at[idx, "Verification Reason"] = val_res["reason"]
            if val_res.get("current_position"):
                df.at[idx, "SignalHire Title"] = val_res["current_position"]
            if val_res.get("current_company"):
                df.at[idx, "SignalHire Company"] = val_res["current_company"]

            if val_res["status"] == "VERIFIED":
                df.at[idx, "Company Match"] = 100
                df.at[idx, "Currentness Score"] = 100
            else:
                df.at[idx, "Currentness Score"] = 0
                df.at[idx, "Company Match"] = 0 if val_res["status"] == "REJECTED" else 70

    return df


# ============================================================
# LINKEDIN DISCOVERY
# ============================================================

def extract_linkedin_profiles(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    profiles = []
    seen = set()

    for item in results:

        url = clean(
            item.get("link")
        )

        if "linkedin.com/in/" not in url.lower():
            continue

        url = url.split("?")[0].rstrip("/")

        if url in seen:
            continue

        seen.add(url)

        profiles.append({
            "Name": clean(
                item.get("title", "")
            ).split(" - ")[0].strip(),

            "Title from Search": clean(
                item.get("title")
            ),

            "LinkedIn": url,

            "Snippet": clean(
                item.get("snippet")
            ),

            "Source": "Serper",
        })

    return profiles


# ============================================================
# MULTI-QUERY PERSON DISCOVERY
# ============================================================

def discover_person(
    company: str,
    location: str,
    persona: str,
    serper_key: str,
    max_results: int = 10,
) -> List[Dict[str, Any]]:

    queries = [

        # 1. High-precision: Persona at Company with location, excluding former/ex/past
        (
            f'site:linkedin.com/in/ '
            f'"{persona} at {company}" '
            f'"{location}" '
            f'-ex -former -past -previously'
        ),

        # 2. Persona at Company general (excluding former/ex/past)
        (
            f'site:linkedin.com/in/ '
            f'"{persona} at {company}" '
            f'-ex -former -past -previously'
        ),

        # 3. Explicit Present keyword (excluding former/ex/past)
        (
            f'site:linkedin.com/in/ '
            f'"{company}" '
            f'"{persona}" '
            f'"present" '
            f'-former -ex -past'
        ),

        # 4. Explicit Current keyword (excluding former/ex/past)
        (
            f'site:linkedin.com/in/ '
            f'"{company}" '
            f'"{persona}" '
            f'"current" '
            f'-former -ex -past'
        ),
    ]

    all_profiles = []
    evidence = []

    for query in queries:

        try:

            result = serper_search(
                query,
                serper_key,
                max_results,
            )

            organic = result.get(
                "organic",
                [],
            )

            evidence.append({
                "query": query,
                "results": organic,
            })

            profiles = extract_linkedin_profiles(
                organic
            )

            for profile in profiles:

                profile[
                    "Discovery Queries"
                ] = [
                    query
                ]

                all_profiles.append(
                    profile
                )

        except Exception:
            continue

    merged = {}

    for profile in all_profiles:

        url = profile["LinkedIn"]

        if url not in merged:

            merged[url] = profile

        else:

            merged[url][
                "Discovery Queries"
            ].extend(
                profile.get(
                    "Discovery Queries",
                    [],
                )
            )

    output = []

    for profile in merged.values():

        profile[
            "Discovery Evidence"
        ] = evidence

        output.append(
            profile
        )

    return output


# ============================================================
# PERSON-SPECIFIC CROSS VALIDATION
# ============================================================

def cross_validate_person(
    name: str,
    company: str,
    location: str,
    persona: str,
    linkedin_url: str,
    serper_key: str,
) -> Dict[str, Any]:

    queries = [

        # Person + company
        (
            f'"{name}" '
            f'"{company}" '
            f'"{persona}"'
        ),

        # Person + company + LinkedIn
        (
            f'"{name}" '
            f'"{company}" '
            f'site:linkedin.com/in/'
        ),

        # Current role language
        (
            f'"{name}" '
            f'"{company}" '
            f'"{persona}" '
            f'"present"'
        ),

        # Location validation
        (
            f'"{name}" '
            f'"{company}" '
            f'"{location}"'
        ),
    ]

    evidence = []

    for query in queries:

        try:

            result = serper_search(
                query,
                serper_key,
                10,
            )

            organic = result.get(
                "organic",
                [],
            )

            relevant = []

            for item in organic:

                text = (
                    clean(item.get("title"))
                    + " "
                    + clean(item.get("snippet"))
                    + " "
                    + clean(item.get("link"))
                ).lower()

                relevant.append({
                    "title": clean(
                        item.get("title")
                    ),
                    "url": clean(
                        item.get("link")
                    ),
                    "snippet": clean(
                        item.get("snippet")
                    ),
                    "contains_company": (
                        normalize_company_name(
                            company
                        )
                        in normalize_company_name(
                            text
                        )
                    ),
                    "contains_persona": (
                        persona.lower()
                        in text
                    ),
                })

            evidence.append({
                "query": query,
                "results": relevant,
            })

        except Exception as exc:

            evidence.append({
                "query": query,
                "error": str(exc),
            })

    return {
        "queries": queries,
        "evidence": evidence,
    }


# ============================================================
# TITLE MATCHING
# ============================================================

def title_score(
    requested: str,
    title: str,
) -> int:

    requested = clean(requested).lower()
    title = clean(title).lower()

    if not title:
        return 0

    aliases = {

        "cto": [
            "cto",
            "chief technology officer",
        ],

        "cio": [
            "cio",
            "chief information officer",
        ],

        "ciso": [
            "ciso",
            "chief information security officer",
            "chief security officer",
        ],

        "vp it": [
            "vp it",
            "vice president it",
            "vp information technology",
        ],

        "head of it": [
            "head of it",
            "it head",
        ],

        "head of technology": [
            "head of technology",
            "technology head",
        ],

        "it director": [
            "it director",
            "director it",
            "director of it",
        ],

        "it manager": [
            "it manager",
            "manager it",
            "manager of it",
        ],
    }

    if requested in aliases:

        for alias in aliases[requested]:

            if alias in title:
                return 100

    if requested in title:
        return 100

    requested_words = [
        x
        for x in re.findall(
            r"[a-z]+",
            requested,
        )
        if len(x) > 2
    ]

    if not requested_words:
        return 0

    matches = sum(
        word in title
        for word in requested_words
    )

    ratio = matches / len(
        requested_words
    )

    if ratio >= 0.8:
        return 85

    if ratio >= 0.5:
        return 70

    if ratio > 0:
        return 40

    return 0


# ============================================================
# COMPANY MATCHING
# ============================================================

def company_score(
    target: str,
    evidence_text: str,
) -> int:

    target_norm = normalize_company_name(
        target
    )

    text_norm = normalize_company_name(
        evidence_text
    )

    if not target_norm or not text_norm:
        return 0

    if target_norm in text_norm:
        return 100

    target_words = set(
        target_norm.split()
    )

    text_words = set(
        text_norm.split()
    )

    overlap = len(
        target_words & text_words
    )

    if overlap == len(target_words):
        return 95

    if target_words and (
        overlap / len(target_words)
    ) >= 0.7:
        return 80

    if target_words and (
        overlap / len(target_words)
    ) >= 0.5:
        return 60

    return 0

def is_company_match(
    company: str,
    title: str,
    snippet: str,
) -> bool:

    target = normalize_company_name(company)

    evidence = normalize_company_name(
        f"{title} {snippet}"
    )

    if not target:
        return False

    # Exact normalized company name
    if target in evidence:
        return True

    # Compare individual words
    target_words = set(target.split())
    evidence_words = set(evidence.split())

    if not target_words:
        return False

    overlap = len(
        target_words & evidence_words
    )

    ratio = overlap / len(target_words)

    # Require ALL words for 2-word+ company names
    if len(target_words) >= 2:
        return overlap == len(target_words)

    # Single-word company
    return ratio >= 1.0
# ============================================================
# LOCATION SCORE
# ============================================================

def location_score(
    target: str,
    actual_text: str,
) -> int:

    target_words = [
        x
        for x in re.findall(
            r"[a-z]+",
            target.lower(),
        )
        if len(x) > 2
    ]

    actual = actual_text.lower()

    if not target_words or not actual:
        return 0

    matches = sum(
        word in actual
        for word in target_words
    )

    ratio = matches / len(
        target_words
    )

    if ratio >= 0.7:
        return 100

    if ratio >= 0.4:
        return 60

    return 20


# ============================================================
# CURRENTNESS & FORMER EMPLOYEE DETECTION
# ============================================================

def check_former_employee_indicators(
    target_company: str,
    title: str,
    snippet: str,
    evidence_text: str = "",
) -> Tuple[bool, str]:
    """
    Detects any indicator that the person has left the target company
    or currently works at another organisation.
    Returns (is_former, reason).
    """
    target_norm = normalize_company_name(target_company)
    if not target_norm:
        return False, ""

    escaped_target = re.escape(target_norm)
    combined = f"{title} {snippet} {evidence_text}".lower()

    # 1. Direct negative keywords explicitly tied to target company
    direct_patterns = [
        (rf"\bex[- ]{escaped_target}\b", f"Profile explicitly mentions 'ex-{target_company}'"),
        (rf"\bformer(?:ly)?\s+(?:at\s+)?{escaped_target}\b", f"Profile explicitly mentions 'former {target_company}'"),
        (rf"\bprevious(?:ly)?\s+(?:at\s+)?{escaped_target}\b", f"Profile mentions 'previously at {target_company}'"),
        (rf"\bprior\s+to\s+{escaped_target}\b", f"Profile mentions 'prior to {target_company}'"),
        (rf"\b{escaped_target}\s+alumni\b", f"Profile mentions '{target_company} alumni'"),
        (rf"\bleft\s+{escaped_target}\b", f"Profile mentions 'left {target_company}'"),
        (rf"\bretired\s+(?:from\s+)?{escaped_target}\b", f"Profile mentions 'retired from {target_company}'"),
        (rf"\bwas\s+(?:a\s+)?(?:[\w\s]{{1,25}})?at\s+{escaped_target}\b", f"Profile mentions 'was at {target_company}'"),
    ]
    for pattern, reason in direct_patterns:
        if re.search(pattern, combined):
            return True, reason

    # 2. LinkedIn snippet "Past:" section
    past_match = re.search(r"\bpast:\s*([^·\n|]+)", combined)
    if past_match:
        past_content = past_match.group(1)
        if target_norm in normalize_company_name(past_content):
            cur_match = re.search(r"\bcurrent:\s*([^·\n|]+)", combined)
            cur_content = cur_match.group(1) if cur_match else ""
            if target_norm not in normalize_company_name(cur_content):
                return True, f"LinkedIn snippet lists target under 'Past' experience: '{past_content.strip()}'"

    # 3. Closed date ranges without present/current near target
    date_range_matches = re.findall(r"\b(19\d\d|20\d\d)\s*[-–—to]+\s*(20[0-2][0-6])\b", combined)
    for start_yr, end_yr in date_range_matches:
        from datetime import datetime
        if int(end_yr) <= datetime.now().year:
            has_present_near_target = bool(
                re.search(rf"{escaped_target}[^·\n|]{{0,50}}\b(present|current|ongoing)\b", combined) or
                re.search(rf"\b(present|current|ongoing)\b[^·\n|]{{0,50}}{escaped_target}", combined)
            )
            if not has_present_near_target:
                return True, f"Snippet contains closed employment date range: {start_yr} - {end_yr}"

    # 4. Headline current role points to a DIFFERENT company
    title_parts = title.split(" - ")
    headline = title_parts[-1] if len(title_parts) > 1 else title
    headline_clean = headline.split(" | ")[0].split(" · ")[0].strip().lower()

    at_match = re.search(r"\b(?:at|@)\s+([A-Za-z0-9&., ]+)", headline_clean)
    if at_match:
        other_comp = normalize_company_name(at_match.group(1))
        if other_comp and len(other_comp) > 2 and target_norm not in other_comp and other_comp not in target_norm:
            return True, f"Headline indicates current employment is at '{at_match.group(1).strip()}', not '{target_company}'"

    return False, ""


def check_current_employee_indicators(
    target_company: str,
    title: str,
    snippet: str,
    evidence_text: str = "",
) -> Tuple[bool, int, str]:
    """
    Checks if the person is presently working at the target organisation.
    Returns (is_current, confidence_score, reason).
    """
    target_norm = normalize_company_name(target_company)
    if not target_norm:
        return False, 0, "No target company provided."

    escaped_target = re.escape(target_norm)
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    combined = f"{title_lower} {snippet_lower} {evidence_text.lower()}"

    # 1. Headline explicitly states: "[Role] at [Target Company]"
    at_target_pattern = rf"\b(?:at|@)\s+{escaped_target}\b"
    headline_has_target = bool(re.search(at_target_pattern, title_lower))

    # 2. Snippet structured "Current: ... Target Company"
    cur_match = re.search(r"\bcurrent:\s*([^·\n|]+)", snippet_lower)
    snippet_current_has_target = False
    if cur_match:
        snippet_current_has_target = target_norm in normalize_company_name(cur_match.group(1))

    # 3. Explicit "present" / "ongoing" associated with target company
    present_pattern = rf"{escaped_target}[^·\n|]{{0,60}}\b(present|current|currently|ongoing|now)\b|\b(present|current|currently|ongoing|now)\b[^·\n|]{{0,60}}{escaped_target}"
    has_present = bool(re.search(present_pattern, combined))

    if headline_has_target and (has_present or snippet_current_has_target):
        return True, 100, f"Headline confirms role at '{target_company}' with active ongoing indicators ('Present/Current')."
    elif headline_has_target:
        return True, 85, f"Headline indicates current role at '{target_company}'."
    elif snippet_current_has_target:
        return True, 90, f"LinkedIn snippet explicitly marks '{target_company}' under 'Current:' employment."
    elif has_present:
        return True, 75, f"Profile text associates '{target_company}' with 'present/current' employment."

    return False, 0, "No explicit indication of present/ongoing employment at target company."


# ============================================================
# PERSONA VERIFICATION
# ============================================================

def verify_persona(
    company: str,
    location: str,
    requested_persona: str,
    profile: Dict[str, Any],
    cross_validation: Dict[str, Any],
) -> Dict[str, Any]:

    name = clean(profile.get("Name"))
    linkedin = clean(profile.get("LinkedIn"))
    search_title = clean(profile.get("Title from Search"))
    snippet = clean(profile.get("Snippet"))

    all_evidence_text = (
        search_title
        + " "
        + snippet
        + " "
        + safe_json(cross_validation)
    )

    company_match = company_score(company, all_evidence_text)
    persona_match = title_score(requested_persona, search_title + " " + snippet)
    location_match = location_score(location, all_evidence_text)

    # 1. STRICT FORMER EMPLOYEE CHECK
    is_former, former_reason = check_former_employee_indicators(
        company,
        search_title,
        snippet,
        all_evidence_text,
    )
    if is_former:
        return {
            "Name": name,
            "LinkedIn": linkedin,
            "Requested Persona": requested_persona,
            "Search Title": search_title,
            "Search Snippet": snippet,
            "Company Match": company_match,
            "Persona Match": persona_match,
            "Currentness Score": 0,
            "Location Match": location_match,
            "Independent Evidence Score": 0,
            "Verification Score": 0.0,
            "Verification Status": "REJECTED",
            "Verification Reason": f"FORMER EMPLOYEE: {former_reason}. Excluded from results.",
            "Evidence Hits": 0,
            "Discovery Evidence": safe_json(profile.get("Discovery Evidence", [])),
        }

    # 2. COMPANY MATCH CHECK
    if company_match < 60:
        return {
            "Name": name,
            "LinkedIn": linkedin,
            "Requested Persona": requested_persona,
            "Search Title": search_title,
            "Search Snippet": snippet,
            "Company Match": company_match,
            "Persona Match": persona_match,
            "Currentness Score": 0,
            "Location Match": location_match,
            "Independent Evidence Score": 0,
            "Verification Score": 0.0,
            "Verification Status": "REJECTED",
            "Verification Reason": f"Target company '{company}' does not match profile evidence.",
            "Evidence Hits": 0,
            "Discovery Evidence": safe_json(profile.get("Discovery Evidence", [])),
        }

    # 3. STRICT CURRENT EMPLOYMENT CHECK
    is_current, current_score, current_reason = check_current_employee_indicators(
        company,
        search_title,
        snippet,
        all_evidence_text,
    )

    # Evidence hits across queries
    evidence_hits = 0
    for block in cross_validation.get("evidence", []):
        query_text = safe_json(block).lower()
        if normalize_company_name(company) in normalize_company_name(query_text) and requested_persona.lower() in query_text:
            evidence_hits += 1

    evidence_score = min(100, evidence_hits * 25)

    if not is_current:
        # Per user requirement:
        # If employment status is unclear or cannot be confidently verified,
        # exclude from verified results rather than returning incorrect result.
        return {
            "Name": name,
            "LinkedIn": linkedin,
            "Requested Persona": requested_persona,
            "Search Title": search_title,
            "Search Snippet": snippet,
            "Company Match": company_match,
            "Persona Match": persona_match,
            "Currentness Score": 0,
            "Location Match": location_match,
            "Independent Evidence Score": evidence_score,
            "Verification Score": 40.0,
            "Verification Status": "REVIEW",
            "Verification Reason": f"UNCLEAR EMPLOYMENT: {current_reason} (Not verified as currently working at '{company}').",
            "Evidence Hits": evidence_hits,
            "Discovery Evidence": safe_json(profile.get("Discovery Evidence", [])),
        }

    if persona_match < 70:
        return {
            "Name": name,
            "LinkedIn": linkedin,
            "Requested Persona": requested_persona,
            "Search Title": search_title,
            "Search Snippet": snippet,
            "Company Match": company_match,
            "Persona Match": persona_match,
            "Currentness Score": current_score,
            "Location Match": location_match,
            "Independent Evidence Score": evidence_score,
            "Verification Score": 65.0,
            "Verification Status": "REVIEW",
            "Verification Reason": f"Current role confirmed at '{company}', but title does not strongly match requested persona '{requested_persona}'.",
            "Evidence Hits": evidence_hits,
            "Discovery Evidence": safe_json(profile.get("Discovery Evidence", [])),
        }

    # 4. CONFIRMED PRESENT EMPLOYEE
    final_score = round(
        company_match * 0.35
        + persona_match * 0.30
        + current_score * 0.25
        + evidence_score * 0.10,
        1,
    )

    status = "VERIFIED"
    reason = f"CONFIRMED PRESENT EMPLOYEE: {current_reason}"

    return {
        "Name": name,
        "LinkedIn": linkedin,
        "Requested Persona": requested_persona,
        "Search Title": search_title,
        "Search Snippet": snippet,
        "Company Match": company_match,
        "Persona Match": persona_match,
        "Currentness Score": current_score,
        "Location Match": location_match,
        "Independent Evidence Score": evidence_score,
        "Verification Score": final_score,
        "Verification Status": status,
        "Verification Reason": reason,
        "Evidence Hits": evidence_hits,
        "Discovery Evidence": safe_json(profile.get("Discovery Evidence", [])),
    }

    return {
        "Name": name,
        "LinkedIn": linkedin,
        "Requested Persona": requested_persona,
        "Search Title": search_title,
        "Search Snippet": snippet,

        "Company Match": company_match,
        "Persona Match": persona_match,
        "Currentness Score": currentness,
        "Location Match": location_match,
        "Independent Evidence Score": evidence_score,

        "Verification Score": final_score,
        "Verification Status": status,
        "Verification Reason": reason,

        "Evidence Hits": evidence_hits,

        "Discovery Evidence": safe_json(
            profile.get(
                "Discovery Evidence",
                [],
            )
        ),

        "Cross Validation": safe_json(
            cross_validation
        ),

        "Verification Timestamp":
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
    }


# ============================================================
# COMPLETE PERSONA PIPELINE
# ============================================================

def run_persona_pipeline(
    company: str,
    location: str,
    personas: List[str],
    serper_key: str,
    max_results: int,
) -> pd.DataFrame:

    rows = []

    total = len(personas)

    progress = st.progress(
        0,
        text="Searching for relevant personas...",
    )

    for index, persona in enumerate(personas):

        try:

            profiles = discover_person(
                company,
                location,
                persona,
                serper_key,
                max_results,
            )

            for profile in profiles:

                name = clean(
                    profile.get("Name")
                )

                if not name:
                    continue

                validation = (
                    cross_validate_person(
                        name,
                        company,
                        location,
                        persona,
                        profile.get(
                            "LinkedIn",
                            "",
                        ),
                        serper_key,
                    )
                )

                verified = verify_persona(
                    company,
                    location,
                    persona,
                    profile,
                    validation,
                )

                rows.append(
                    verified
                )

        except Exception as exc:

            st.warning(
                f"{persona}: {exc}"
            )

        progress.progress(
            (index + 1) / total,
            text=(
                f"Processing {persona} "
                f"({index + 1}/{total})"
            ),
        )

    progress.empty()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    df = df.drop_duplicates(
        subset=[
            "LinkedIn",
            "Requested Persona",
        ]
    )

    df = df.sort_values(
        "Verification Score",
        ascending=False,
    )

    return df.reset_index(
        drop=True
    )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("⚙️ Configuration")

    serper_key = st.text_input(
        "Serper API Key",
        value=get_secret(
            "SERPER_API_KEY",
            "",
        ),
        type="password",
    )

    builtwith_key = st.text_input(
        "BuiltWith API Key",
        value=get_secret(
            "BUILTWITH_API_KEY",
            "",
        ),
        type="password",
    )

    signalhire_key = st.text_input(
        "SignalHire API Key",
        value=get_secret(
            "SIGNALHIRE_API_KEY",
            "202.aBvCsev0gnhPuyBqigoXHS1BfiuZ",
        ),
        type="password",
    )

    if signalhire_key:
        credits_left = signalhire_get_credits(signalhire_key)
        if credits_left is not None:
            st.session_state.signalhire_credits = credits_left
            st.success(f"💳 SignalHire: **{credits_left}** credits left")
        else:
            st.warning("⚠️ Could not verify SignalHire API Key.")

    st.markdown(
        "### Persona Selection"
    )

    persona_group = st.selectbox(
        "Persona Group",
        [
            "All",
            *PERSONA_GROUPS.keys(),
        ],
    )

    if persona_group == "All":

        personas = DEFAULT_PERSONAS

    else:

        personas = PERSONA_GROUPS[
            persona_group
        ]

    max_results = st.slider(
        "Search results per persona",
        3,
        10,
        5,
    )

    st.markdown(
        "### ⚡ Enrichment Settings"
    )

    auto_enrich = st.checkbox(
        "Auto-enrich top verified candidates",
        value=False,
        help="Automatically calls SignalHire to retrieve emails, phones, and live company data.",
    )

    max_enrich = 0
    if auto_enrich:
        max_enrich = st.slider(
            "Max profiles to auto-enrich",
            1,
            5,
            2,
            help="Limit credit consumption per run",
        )


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">'
    '🎯 360° Account Intelligence'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="subtitle">'
    'Company → Technology → Persona Discovery '
    '→ Multi-source Verification → Lead Qualification'
    '</div>',
    unsafe_allow_html=True,
)


# ============================================================
# INPUT
# ============================================================

st.subheader(
    "1. Account Input"
)

col1, col2 = st.columns(2)

company_name = col1.text_input(
    "Company Name",
    placeholder="Example: Infosys",
)

location = col2.text_input(
    "Location",
    placeholder="Example: Bengaluru, India",
)


# ============================================================
# RUN
# ============================================================

if st.button(
    "🚀 Run Complete Intelligence",
    type="primary",
    use_container_width=True,
):

    if not company_name.strip():

        st.error(
            "Company name is required."
        )
        st.stop()

    if not location.strip():

        st.error(
            "Location is required."
        )
        st.stop()

    if not serper_key:

        st.error(
            "Serper API key is required."
        )
        st.stop()

    # --------------------------------------------------------
    # RESET
    # --------------------------------------------------------

    st.session_state.account = {
        "company": company_name.strip(),
        "location": location.strip(),
    }

    st.session_state.company = {}
    st.session_state.technology = {}
    st.session_state.personas = pd.DataFrame()
    st.session_state.approved = pd.DataFrame()

    # --------------------------------------------------------
    # COMPANY DOMAIN
    # --------------------------------------------------------

    with st.spinner(
        "Finding official company domain..."
    ):

        domain_result = find_company_domain(
            company_name,
            location,
            serper_key,
        )

    domain = domain_result.get(
        "domain",
        "",
    )

    # --------------------------------------------------------
    # ZAUBA
    # --------------------------------------------------------

    with st.spinner(
        "Checking Zauba company evidence..."
    ):

        try:

            zauba = company_source_search(
                company_name,
                location,
                "Zauba",
                serper_key,
            )

        except Exception as exc:

            zauba = {
                "source": "Zauba",
                "status": f"Error: {exc}",
                "records": [],
            }

    # --------------------------------------------------------
    # TOFLER
    # --------------------------------------------------------

    with st.spinner(
        "Checking Tofler company evidence..."
    ):

        try:

            tofler = company_source_search(
                company_name,
                location,
                "Tofler",
                serper_key,
            )

        except Exception as exc:

            tofler = {
                "source": "Tofler",
                "status": f"Error: {exc}",
                "records": [],
            }

    # --------------------------------------------------------
    # COMPANY DATA
    # --------------------------------------------------------

    st.session_state.company = {

        "company_name": company_name,

        "location": location,

        "domain": domain,

        "domain_confidence":
            domain_result.get(
                "confidence"
            ),

        "domain_evidence":
            domain_result.get(
                "evidence",
                [],
            ),

        "zauba": zauba,

        "tofler": tofler,
    }

    # --------------------------------------------------------
    # BUILTWITH
    # --------------------------------------------------------

    technology = {
        "status": "Not configured",
        "domain": domain,
        "technologies": [],
        "categories": [],
        "solution_fit": [],
        "raw": {},
    }

    if domain and builtwith_key:

        with st.spinner(
            "Scanning technology environment..."
        ):

            try:

                raw = builtwith_lookup(
                    domain,
                    builtwith_key,
                )

                technologies, categories = (
                    parse_builtwith(raw)
                )

                technology = {
                    "status": "Live BuiltWith",
                    "domain": domain,
                    "technologies": technologies,
                    "categories": categories,
                    "solution_fit":
                        determine_solution_fit(
                            technologies,
                            categories,
                        ),
                    "raw": raw,
                }

            except Exception as exc:

                technology = {
                    "status":
                        f"BuiltWith error: {exc}",
                    "domain": domain,
                    "technologies": [],
                    "categories": [],
                    "solution_fit": [],
                    "raw": {},
                }

    elif not builtwith_key:

        technology["status"] = (
            "BuiltWith API key not configured"
        )

    else:

        technology["status"] = (
            "Company domain not resolved"
        )

    st.session_state.technology = technology

    # --------------------------------------------------------
    # PERSONA PIPELINE
    # --------------------------------------------------------

    with st.spinner(
        "Discovering and verifying personas..."
    ):

        persona_df = run_persona_pipeline(
            company_name,
            location,
            personas,
            serper_key,
            max_results,
        )

    if not persona_df.empty:

        persona_df[
            "Technology Stack"
        ] = ", ".join(
            technology.get(
                "technologies",
                [],
            )
        )

        persona_df[
            "Solution Fit"
        ] = "; ".join(
            technology.get(
                "solution_fit",
                [],
            )
        )

        # ----------------------------------------------------
        # SIGNALHIRE AUTO-ENRICHMENT (OPTION A)
        # ----------------------------------------------------
        if auto_enrich and signalhire_key and max_enrich > 0:
            with st.spinner(
                f"Enriching top {max_enrich} candidates via SignalHire..."
            ):
                candidate_targets = persona_df.head(max_enrich)
                urls_to_enrich = [
                    u for u in candidate_targets["LinkedIn"].tolist() if u
                ]
                if urls_to_enrich:
                    try:
                        enriched_items = signalhire_enrich_profiles(
                            urls_to_enrich,
                            signalhire_key,
                            without_contacts=False,
                        )
                        persona_df = apply_signalhire_enrichment(
                            persona_df,
                            enriched_items,
                            company_name,
                        )
                        persona_df = persona_df.sort_values(
                            "Verification Score",
                            ascending=False,
                        ).reset_index(drop=True)

                        rem_credits = signalhire_get_credits(signalhire_key)
                        if rem_credits is not None:
                            st.session_state.signalhire_credits = rem_credits
                    except Exception as err:
                        st.warning(f"SignalHire enrichment warning: {err}")

    st.session_state.personas = persona_df

    st.success(
        "360° Account Intelligence completed."
    )


# ============================================================
# RESULTS
# ============================================================

company_data = st.session_state.company
technology_data = st.session_state.technology
persona_df = st.session_state.personas


if company_data:

    st.divider()

    st.subheader(
        "2. 360° Account & Persona Profile"
    )

    tabs = st.tabs(
        [
            "🏢 Company",
            "💻 Technology",
            "👤 Personas",
            "✅ Verification",
            "🎯 Lead Qualification",
            "🔬 Evidence",
        ]
    )


    # ========================================================
    # COMPANY
    # ========================================================

    with tabs[0]:

        st.markdown(
            f"""
            <div class="card info">

            <h3>
            {company_data.get("company_name", "")}
            </h3>

            <b>Location:</b>
            {company_data.get("location", "")}

            <br><br>

            <b>Official Domain:</b>
            {company_data.get("domain", "Not resolved")}

            <br><br>

            <b>Domain Confidence:</b>
            {company_data.get("domain_confidence", "")}

            </div>
            """,
            unsafe_allow_html=True,
        )

        c1, c2 = st.columns(2)

        with c1:

            st.subheader(
                "Zauba"
            )

            zauba = company_data.get(
                "zauba",
                {},
            )

            st.write(
                zauba.get(
                    "status",
                    "",
                )
            )

            if zauba.get("records"):

                st.dataframe(
                    pd.DataFrame(
                        zauba[
                            "records"
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        with c2:

            st.subheader(
                "Tofler"
            )

            tofler = company_data.get(
                "tofler",
                {},
            )

            st.write(
                tofler.get(
                    "status",
                    "",
                )
            )

            if tofler.get("records"):

                st.dataframe(
                    pd.DataFrame(
                        tofler[
                            "records"
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        st.info(
            "Zauba and Tofler are being used here "
            "as company-level evidence discovered "
            "through search. They are not being "
            "represented as direct APIs."
        )


    # ========================================================
    # TECHNOLOGY
    # ========================================================

    with tabs[1]:

        st.subheader(
            "Technographic Intelligence"
        )

        st.write(
            "**Source:**",
            technology_data.get(
                "status",
                "",
            ),
        )

        st.write(
            "**Domain:**",
            technology_data.get(
                "domain",
                "",
            ),
        )

        technologies = technology_data.get(
            "technologies",
            [],
        )

        if technologies:

            st.markdown(
                "### Technology Stack"
            )

            cols = st.columns(
                min(
                    4,
                    len(technologies),
                )
            )

            for i, technology in enumerate(
                technologies
            ):

                cols[
                    i % len(cols)
                ].success(
                    technology
                )

        else:

            st.info(
                "No technology data available."
            )

        st.markdown(
            "### Solution-Fit Indicators"
        )

        fit = technology_data.get(
            "solution_fit",
            [],
        )

        if fit:

            for item in fit:
                st.success(item)

        else:

            st.info(
                "No solution-fit indicators detected."
            )


    # ========================================================
    # PERSONAS
    # ========================================================

    with tabs[2]:

        st.subheader(
            "Persona Intelligence"
        )

        if persona_df.empty:

            st.warning(
                "No persona candidates found."
            )

        else:

            # SignalHire interactive enrichment bar
            if signalhire_key:
                c_enr1, c_enr2 = st.columns([3, 1])
                with c_enr1:
                    rem = st.session_state.get("signalhire_credits")
                    credit_msg = f" ({rem} credits available)" if rem is not None else ""
                    st.caption(
                        f"⚡ **SignalHire Enrichment**: Enrich profiles with verified work emails, phone numbers, and live employment data{credit_msg}."
                    )
                with c_enr2:
                    if st.button("⚡ Enrich Top 3 via SignalHire", key="btn_enrich_personas", use_container_width=True):
                        _sh_col = "SignalHire Status"
                        if _sh_col in persona_df.columns:
                            unenriched = persona_df[persona_df[_sh_col] != "success"].head(3)
                        else:
                            unenriched = persona_df.head(3)
                        urls = [u for u in unenriched["LinkedIn"].tolist() if u]
                        if urls:
                            with st.spinner(f"Enriching {len(urls)} profiles via SignalHire..."):
                                try:
                                    results = signalhire_enrich_profiles(
                                        urls,
                                        signalhire_key,
                                        without_contacts=False,
                                    )
                                    updated_df = apply_signalhire_enrichment(
                                        persona_df,
                                        results,
                                        company_data.get("company_name", ""),
                                    )
                                    st.session_state.personas = updated_df.sort_values(
                                        "Verification Score",
                                        ascending=False,
                                    ).reset_index(drop=True)
                                    rem_credits = signalhire_get_credits(signalhire_key)
                                    if rem_credits is not None:
                                        st.session_state.signalhire_credits = rem_credits
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Enrichment error: {e}")
                        else:
                            st.info("Top candidates are already enriched.")

            display_columns = [
                "Name",
                "Requested Persona",
                "Search Title",
                "SignalHire Title",
                "SignalHire Company",
                "Work Emails",
                "Personal Emails",
                "Work Phones",
                "LinkedIn",
                "Verification Score",
                "Verification Status",
            ]

            display_columns = [
                x
                for x in display_columns
                if x in persona_df.columns
            ]

            st.dataframe(
                persona_df[
                    display_columns
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "LinkedIn":
                        st.column_config.LinkColumn(
                            "LinkedIn"
                        )
                },
            )


    # ========================================================
    # VERIFICATION
    # ========================================================

    with tabs[3]:

        st.subheader(
            "Persona Verification"
        )

        if persona_df.empty:

            st.info(
                "No verification results."
            )

        else:

            counts = (
                persona_df[
                    "Verification Status"
                ]
                .value_counts()
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Verified",
                int(
                    counts.get(
                        "VERIFIED",
                        0,
                    )
                ),
            )

            c2.metric(
                "High Confidence",
                int(
                    counts.get(
                        "HIGH CONFIDENCE",
                        0,
                    )
                ),
            )

            c3.metric(
                "Review",
                int(
                    counts.get(
                        "REVIEW",
                        0,
                    )
                ),
            )

            c4.metric(
                "Rejected",
                int(
                    counts.get(
                        "REJECTED",
                        0,
                    )
                ),
            )

            st.markdown(
                "### Verification methodology"
            )

            st.write(
                """
                The system does NOT consider a LinkedIn
                search result to be automatic proof.

                It evaluates:

                1. Company association
                2. Requested persona/title match
                3. Current-employment indicators
                4. Location evidence
                5. Independent search evidence

                Former employees, consultants, advisors and
                weak title matches are downgraded or rejected.
                """
            )

            st.dataframe(
                persona_df[
                    [
                        "Name",
                        "Requested Persona",
                        "Search Title",
                        "Company Match",
                        "Persona Match",
                        "Currentness Score",
                        "Location Match",
                        "Independent Evidence Score",
                        "Verification Score",
                        "Verification Status",
                        "Verification Reason",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )


    # ========================================================
    # LEAD QUALIFICATION
    # ========================================================

    with tabs[4]:

        st.subheader(
            "Profiled & Outreach-Ready Candidates"
        )

        if persona_df.empty:

            st.info(
                "No candidates."
            )

        else:

            verified = persona_df[
                persona_df[
                    "Verification Status"
                ]
                == "VERIFIED"
            ].copy()

            if verified.empty:

                st.warning(
                    "No automatically verified "
                    "personas are available."
                )

            else:

                # SignalHire Bulk Action Bar
                if signalhire_key:
                    c_lead1, c_lead2 = st.columns([3, 1])
                    with c_lead1:
                        rem = st.session_state.get("signalhire_credits")
                        credit_txt = f" ({rem} credits available)" if rem is not None else ""
                        st.markdown(
                            f"**⚡ Contact Enrichment**: Reveal verified work emails, personal emails, direct phone numbers, and full background via SignalHire{credit_txt}."
                        )
                    with c_lead2:
                        sh_col = "SignalHire Status"
                        if sh_col in verified.columns:
                            un_enr = verified[verified[sh_col] != "success"]
                        else:
                            un_enr = verified
                        if not un_enr.empty:
                            if st.button(
                                f"⚡ Enrich {len(un_enr)} Verified",
                                key="btn_enrich_verified_leads",
                                use_container_width=True,
                            ):
                                urls = [u for u in un_enr["LinkedIn"].tolist() if u]
                                with st.spinner(f"Enriching {len(urls)} candidates via SignalHire..."):
                                    try:
                                        results = signalhire_enrich_profiles(
                                            urls,
                                            signalhire_key,
                                            without_contacts=False,
                                        )
                                        updated_df = apply_signalhire_enrichment(
                                            persona_df,
                                            results,
                                            company_data.get("company_name", ""),
                                        )
                                        st.session_state.personas = updated_df.sort_values(
                                            "Verification Score",
                                            ascending=False,
                                        ).reset_index(drop=True)
                                        rem_credits = signalhire_get_credits(signalhire_key)
                                        if rem_credits is not None:
                                            st.session_state.signalhire_credits = rem_credits
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Enrichment error: {e}")
                        else:
                            st.success("All verified leads enriched!")

                st.success(
                    f"{len(verified)} persona(s) "
                    "passed strict verification."
                )

                for idx, row in verified.iterrows():

                    work_emails = clean(row.get("Work Emails", ""))
                    personal_emails = clean(row.get("Personal Emails", ""))
                    phones = clean(row.get("Work Phones", "")) or clean(row.get("All Phones", ""))
                    sh_title = clean(row.get("SignalHire Title", ""))
                    sh_company = clean(row.get("SignalHire Company", ""))
                    skills = clean(row.get("SignalHire Skills", ""))

                    contact_badges = []
                    if work_emails:
                        for em in work_emails.split(", "):
                            if em.strip():
                                contact_badges.append(f'<span class="contact-badge badge-work-email">📧 Work: {em.strip()}</span>')
                    if personal_emails:
                        for em in personal_emails.split(", "):
                            if em.strip():
                                contact_badges.append(f'<span class="contact-badge badge-personal-email">✉️ Personal: {em.strip()}</span>')
                    if phones:
                        for ph in phones.split(", "):
                            if ph.strip():
                                contact_badges.append(f'<span class="contact-badge badge-phone">📞 {ph.strip()}</span>')
                    if sh_title and sh_company:
                        contact_badges.append(f'<span class="contact-badge badge-role">💼 {sh_title} @ {sh_company}</span>')

                    badges_html = " ".join(contact_badges)
                    if badges_html:
                        badges_html = f"<div style='margin: 8px 0;'>{badges_html}</div>"

                    st.markdown(
                        f"""
                        <div class="card verified">

                        <h3>
                        {row.get("Name", "")}
                        </h3>

                        <b>Account:</b>
                        {company_data.get("company_name", "")}

                        <br>

                        <b>Persona:</b>
                        {row.get("Requested Persona", "")}

                        <br>

                        <b>Title:</b>
                        {row.get("SignalHire Title", "") or row.get("Search Title", "")}

                        <br>

                        <b>Verification Score:</b>
                        {row.get("Verification Score", "")}/100

                        <br>

                        <b>LinkedIn:</b>
                        {row.get("LinkedIn", "")}

                        <br>

                        <b>Technology:</b>
                        {row.get("Technology Stack", "")}

                        <br>

                        <b>Solution Fit:</b>
                        {row.get("Solution Fit", "")}

                        {f"<br><b>Skills:</b> {skills}" if skills else ""}

                        {badges_html}

                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Per-candidate on-demand enrichment button if not yet enriched
                    if signalhire_key and not contact_badges and row.get("LinkedIn"):
                        if st.button(f"⚡ Enrich {row.get('Name', 'Profile')}", key=f"btn_single_enr_{idx}"):
                            with st.spinner(f"Enriching {row.get('Name')} via SignalHire..."):
                                try:
                                    res = signalhire_enrich_profiles(
                                        [row.get("LinkedIn")],
                                        signalhire_key,
                                        without_contacts=False,
                                    )
                                    up_df = apply_signalhire_enrichment(
                                        persona_df,
                                        res,
                                        company_data.get("company_name", ""),
                                    )
                                    st.session_state.personas = up_df.sort_values(
                                        "Verification Score",
                                        ascending=False,
                                    ).reset_index(drop=True)
                                    rem_credits = signalhire_get_credits(signalhire_key)
                                    if rem_credits is not None:
                                        st.session_state.signalhire_credits = rem_credits
                                    st.rerun()
                                except Exception as err:
                                    st.error(f"Enrichment error: {err}")

                export_columns = [
                    "Name",
                    "Requested Persona",
                    "Search Title",
                    "SignalHire Title",
                    "SignalHire Company",
                    "Work Emails",
                    "Personal Emails",
                    "All Emails",
                    "Work Phones",
                    "Mobile Phones",
                    "All Phones",
                    "SignalHire Skills",
                    "LinkedIn",
                    "Verification Score",
                    "Verification Status",
                    "Verification Reason",
                    "Technology Stack",
                    "Solution Fit",
                ]

                export_columns = [
                    x
                    for x in export_columns
                    if x in verified.columns
                ]

                st.download_button(
                    "⬇️ Download Verified Personas & Contacts (CSV)",
                    verified[
                        export_columns
                    ].to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name=(
                        re.sub(
                            r"[^A-Za-z0-9]+",
                            "_",
                            company_name,
                        )
                        + "_verified_personas.csv"
                    ),
                    mime="text/csv",
                    use_container_width=True,
                )

                st.info(
                    "Contact enrichment is powered by SignalHire API. "
                    "Verified candidates display live emails, phone numbers, and ground-truth employment data."
                )


    # ========================================================
    # EVIDENCE
    # ========================================================

    with tabs[5]:

        st.subheader(
            "Evidence & Audit Trail"
        )

        st.markdown(
            """
            <div class="card info">

            <b>Important:</b>

            Search evidence is treated as evidence,
            not as guaranteed ground truth.

            The application keeps the queries and
            returned evidence so that a user can
            manually inspect why a persona was
            classified as VERIFIED, REVIEW or REJECTED.

            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            "### Domain Discovery Evidence"
        )

        st.json(
            company_data.get(
                "domain_evidence",
                [],
            )
        )

        st.markdown(
            "### Zauba Evidence"
        )

        st.json(
            company_data.get(
                "zauba",
                {},
            )
        )

        st.markdown(
            "### Tofler Evidence"
        )

        st.json(
            company_data.get(
                "tofler",
                {},
            )
        )

        st.markdown(
            "### BuiltWith Data"
        )

        st.json(
            technology_data.get(
                "raw",
                {},
            )
        )

        if not persona_df.empty:

            st.markdown(
                "### Persona Evidence"
            )

            for _, row in persona_df.iterrows():

                with st.expander(
                    f"{row.get('Name', '')} | "
                    f"{row.get('Verification Status', '')} | "
                    f"{row.get('Verification Score', '')}"
                ):

                    st.write(
                        "Verification Reason:",
                        row.get(
                            "Verification Reason",
                            "",
                        ),
                    )

                    st.write(
                        "LinkedIn:",
                        row.get(
                            "LinkedIn",
                            "",
                        ),
                    )

                    st.write(
                        "Discovery Evidence"
                    )

                    raw_discovery = row.get(
                        "Discovery Evidence",
                        "",
                    )

                    if raw_discovery:

                        try:
                            st.json(
                                json.loads(
                                    raw_discovery
                                )
                            )
                        except Exception:
                            st.code(
                                raw_discovery
                            )

                    st.write(
                        "Cross Validation"
                    )

                    raw_validation = row.get(
                        "Cross Validation",
                        "",
                    )

                    if raw_validation:

                        try:
                            st.json(
                                json.loads(
                                    raw_validation
                                )
                            )
                        except Exception:
                            st.code(
                                raw_validation
                            )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "360° Account Intelligence | "
    "Company validation + multi-query persona "
    "verification + technographic intelligence"
)

