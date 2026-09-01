import os
import re
import json
import time
from typing import Any, Dict, List, Tuple, Optional

import requests
import pandas as pd
import streamlit as st


# ============================================================
# APPLICATION CONFIG
# ============================================================

st.set_page_config(
    page_title="360° Account Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# API ENDPOINTS
# ============================================================

SERPER_URL = "https://google.serper.dev/search"

BUILTWITH_URL = (
    "https://api.builtwith.com/v23/api.json"
)

ZINTLR_BASE_URL = (
    "https://b2b2b.zintlr.com"
)

ZINTLR_PEOPLE_SEARCH = (
    f"{ZINTLR_BASE_URL}/b2b2b/v1/people/search/"
)

ZINTLR_PEOPLE_AI_SEARCH = (
    f"{ZINTLR_BASE_URL}/b2b2b/v1/people/ai-search/"
)

ZINTLR_LN_PROFILE = (
    f"{ZINTLR_BASE_URL}/b2b2b/v1/ln-url-to-ln-data/"
)

ZINTLR_LN_CONTACT = (
    f"{ZINTLR_BASE_URL}/b2b2b/v1/ln-url-to-ph-email/"
)

ZINTLR_DOMAIN_TO_LN = (
    f"{ZINTLR_BASE_URL}/b2b2b/v1/domain-to-ln-url/"
)


# ============================================================
# DEFAULT PERSONAS
# ============================================================

DEFAULT_PERSONAS = [
    "CTO",
    "CIO",
    "CISO",
    "Chief Technology Officer",
    "Chief Information Officer",
    "Chief Information Security Officer",
    "Chief Information Security Officer",
    "VP Technology",
    "VP IT",
    "Vice President IT",
    "Head of Technology",
    "Head of IT",
    "Head of Infrastructure",
    "Head of Cyber Security",
    "Head of Information Security",
    "IT Director",
    "Director IT",
    "IT Manager",
    "Information Security Manager",
    "Cybersecurity Head",
    "System Administrator",
]


# ============================================================
# PERSONA GROUPS
# ============================================================

PERSONA_GROUPS = {
    "Technology Leadership": [
        "CTO",
        "Chief Technology Officer",
        "VP Technology",
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
        "IT Manager",
    ],
    "Security Leadership": [
        "CISO",
        "Chief Information Security Officer",
        "Head of Cyber Security",
        "Head of Information Security",
        "Cybersecurity Head",
        "Information Security Manager",
    ],
    "Infrastructure": [
        "Head of Infrastructure",
        "Infrastructure Director",
        "Infrastructure Manager",
        "System Administrator",
    ],
}


# ============================================================
# SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "account": {},
    "company": {},
    "technology": {},
    "candidates": pd.DataFrame(),
    "verified": pd.DataFrame(),
    "selected": [],
    "enriched": pd.DataFrame(),
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

    .title {
        font-size: 34px;
        font-weight: 800;
        color: #111827;
    }

    .subtitle {
        color: #6b7280;
        margin-bottom: 20px;
    }

    .box {
        padding: 18px;
        border-radius: 14px;
        border: 1px solid #e5e7eb;
        background: white;
        margin-bottom: 15px;
    }

    .green {
        background: #f0fdf4;
        border: 1px solid #bbf7d0;
    }

    .yellow {
        background: #fefce8;
        border: 1px solid #fde68a;
    }

    .red {
        background: #fef2f2;
        border: 1px solid #fecaca;
    }

    .blue {
        background: #eff6ff;
        border: 1px solid #bfdbfe;
    }

    .metric {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 15px;
        text-align: center;
        background: white;
    }

    .metric-value {
        font-size: 28px;
        font-weight: 800;
    }

    .metric-label {
        font-size: 13px;
        color: #6b7280;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# GENERIC HELPERS
# ============================================================

def clean_text(value: Any) -> str:

    if value is None:
        return ""

    return str(value).strip()


def normalize_domain(domain: str) -> str:

    domain = clean_text(domain)

    domain = re.sub(
        r"^https?://",
        "",
        domain,
        flags=re.I,
    )

    domain = domain.split("/")[0]
    domain = domain.lower()

    if domain.startswith("www."):
        domain = domain[4:]

    return domain.strip()


def normalize_company_name(name: str) -> str:

    value = clean_text(name).lower()

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
        "co",
    ]

    for term in remove_terms:
        value = value.replace(term, " ")

    value = re.sub(
        r"[^a-z0-9 ]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def unique(values: List[str]) -> List[str]:

    result = []

    for value in values:

        value = clean_text(value)

        if value and value not in result:
            result.append(value)

    return result


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


def recursive_values(
    data: Any,
    keys: Optional[List[str]] = None,
) -> List[Any]:

    output = []

    if isinstance(data, dict):

        for key, value in data.items():

            if keys is None or key.lower() in [
                x.lower()
                for x in keys
            ]:
                output.append(value)

            output.extend(
                recursive_values(
                    value,
                    keys,
                )
            )

    elif isinstance(data, list):

        for item in data:

            output.extend(
                recursive_values(
                    item,
                    keys,
                )
            )

    return output


def recursive_find(
    data: Any,
    keywords: List[str],
) -> List[Any]:

    output = []

    if isinstance(data, dict):

        for key, value in data.items():

            key_lower = key.lower()

            if any(
                keyword.lower() in key_lower
                for keyword in keywords
            ):
                output.append(value)

            output.extend(
                recursive_find(
                    value,
                    keywords,
                )
            )

    elif isinstance(data, list):

        for item in data:

            output.extend(
                recursive_find(
                    item,
                    keywords,
                )
            )

    return output


# ============================================================
# API ERROR HANDLING
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

        return {
            "raw_response": response.text
        }


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
        timeout=30,
    )


# ============================================================
# COMPANY DOMAIN DISCOVERY
# ============================================================

def find_company_domain(
    company_name: str,
    location: str,
    serper_key: str,
) -> Dict[str, Any]:

    queries = [
        (
            f'"{company_name}" '
            f'"{location}" '
            f'official website'
        ),
        (
            f'"{company_name}" '
            f'official website'
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

            evidence.append({
                "query": query,
                "results": result.get(
                    "organic",
                    [],
                ),
            })

            for item in result.get(
                "organic",
                [],
            ):

                link = clean_text(
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

                blocked = [
                    "google.com",
                    "linkedin.com",
                    "facebook.com",
                    "instagram.com",
                    "youtube.com",
                    "wikipedia.org",
                    "zaubacorp.com",
                    "tofler.in",
                    "builtwith.com",
                ]

                if domain in blocked:
                    continue

                return {
                    "domain": domain,
                    "confidence": "Search-supported",
                    "evidence": evidence,
                }

        except Exception as exc:

            evidence.append({
                "query": query,
                "error": str(exc),
            })

    return {
        "domain": "",
        "confidence": "Not resolved",
        "evidence": evidence,
    }


# ============================================================
# ZAUBA EVIDENCE
# ============================================================

def get_zauba_evidence(
    company_name: str,
    location: str,
    serper_key: str,
) -> Dict[str, Any]:

    query = (
        f'"{company_name}" '
        f'"{location}" '
        f'site:zaubacorp.com'
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

        link = clean_text(
            item.get("link")
        )

        if "zaubacorp.com" not in link.lower():
            continue

        records.append(
            {
                "title": clean_text(
                    item.get("title")
                ),
                "url": link,
                "snippet": clean_text(
                    item.get("snippet")
                ),
            }
        )

    return {
        "status": (
            "Evidence found"
            if records
            else "No evidence found"
        ),
        "records": records,
    }


# ============================================================
# TOFLER EVIDENCE
# ============================================================

def get_tofler_evidence(
    company_name: str,
    location: str,
    serper_key: str,
) -> Dict[str, Any]:

    query = (
        f'"{company_name}" '
        f'"{location}" '
        f'site:tofler.in'
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

        link = clean_text(
            item.get("link")
        )

        if "tofler.in" not in link.lower():
            continue

        records.append(
            {
                "title": clean_text(
                    item.get("title")
                ),
                "url": link,
                "snippet": clean_text(
                    item.get("snippet")
                ),
            }
        )

    return {
        "status": (
            "Evidence found"
            if records
            else "No evidence found"
        ),
        "records": records,
    }


# ============================================================
# ZINTLR AUTH
# ============================================================

def zintlr_headers(
    access_token: str,
    secret_key: str,
) -> Dict[str, str]:

    if not access_token:
        raise RuntimeError(
            "Zintlr Access Token is missing."
        )

    if not secret_key:
        raise RuntimeError(
            "Zintlr Secret Key is missing."
        )

    return {
        "Access-Token": access_token,
        "Secret-Key": secret_key,
        "Content-Type": "application/json",
    }


# ============================================================
# ZINTLR DOMAIN → COMPANY LINKEDIN
# ============================================================

def zintlr_domain_to_company(
    domain: str,
    access_token: str,
    secret_key: str,
) -> Dict[str, Any]:

    headers = zintlr_headers(
        access_token,
        secret_key,
    )

    return api_request(
        "POST",
        ZINTLR_DOMAIN_TO_LN,
        headers=headers,
        payload={
            "domains": [
                domain
            ]
        },
    )


# ============================================================
# ZINTLR PEOPLE AI SEARCH
# ============================================================

def zintlr_ai_people_search(
    company_name: str,
    location: str,
    persona: str,
    access_token: str,
    secret_key: str,
    count: int = 20,
) -> Dict[str, Any]:

    headers = zintlr_headers(
        access_token,
        secret_key,
    )

    query = (
        f'Find current employees at '
        f'"{company_name}" in '
        f'"{location}" whose current '
        f'job title matches "{persona}". '
        f'Only return people currently '
        f'working for this company.'
    )

    return api_request(
        "POST",
        ZINTLR_PEOPLE_AI_SEARCH,
        headers=headers,
        payload={
            "query": query,
            "include_director_details": True,
            "page": 1,
            "count": count,
        },
    )


# ============================================================
# ZINTLR PEOPLE SEARCH
# ============================================================

def zintlr_people_search(
    company_name: str,
    location: str,
    persona: str,
    access_token: str,
    secret_key: str,
    count: int = 20,
) -> Dict[str, Any]:

    headers = zintlr_headers(
        access_token,
        secret_key,
    )

    # We intentionally use broad structured filters here.
    # Exact employer verification happens afterwards
    # against the returned profile data.

    seniority = []

    persona_lower = persona.lower()

    if any(
        term in persona_lower
        for term in [
            "cto",
            "cio",
            "ciso",
            "chief",
        ]
    ):
        seniority = [
            "C-Level"
        ]

    elif any(
        term in persona_lower
        for term in [
            "vp",
            "vice president",
        ]
    ):
        seniority = [
            "VP"
        ]

    elif "director" in persona_lower:
        seniority = [
            "Director"
        ]

    elif "head" in persona_lower:
        seniority = [
            "Director",
            "VP",
        ]

    elif "manager" in persona_lower:
        seniority = [
            "Manager"
        ]

    payload = {
        "company_filters": {
            "company_hq_location": {
                "country": [
                    "India"
                ]
            }
        },
        "people_filters": {
            "seniority": seniority
        },
        "page": 1,
        "count": min(
            max(count, 1),
            20,
        ),
    }

    return api_request(
        "POST",
        ZINTLR_PEOPLE_SEARCH,
        headers=headers,
        payload=payload,
    )


# ============================================================
# ZINTLR LINKEDIN PROFILE
# ============================================================

def zintlr_profile_lookup(
    linkedin_url: str,
    access_token: str,
    secret_key: str,
) -> Dict[str, Any]:

    headers = zintlr_headers(
        access_token,
        secret_key,
    )

    return api_request(
        "POST",
        ZINTLR_LN_PROFILE,
        headers=headers,
        payload={
            "ln_urls": [
                linkedin_url
            ],
            "company_fetch": False,
        },
    )


# ============================================================
# ZINTLR CONTACT ENRICHMENT
# ============================================================

def zintlr_contact_lookup(
    linkedin_url: str,
    access_token: str,
    secret_key: str,
    email_unlock: bool,
    phone_unlock: bool,
) -> Dict[str, Any]:

    headers = zintlr_headers(
        access_token,
        secret_key,
    )

    return api_request(
        "POST",
        ZINTLR_LN_CONTACT,
        headers=headers,
        payload={
            "ln_url": linkedin_url,
            "email_unlock": email_unlock,
            "phone_unlock": phone_unlock,
        },
    )


# ============================================================
# PROFILE EXTRACTION
# ============================================================

def extract_linkedin_url(
    data: Any,
) -> str:

    candidates = recursive_find(
        data,
        [
            "linkedin_url",
            "linkedin",
            "ln_url",
            "profile_url",
        ],
    )

    for value in candidates:

        if isinstance(
            value,
            str,
        ):

            if "linkedin.com/in/" in value.lower():

                return value.split("?")[0].rstrip("/")

    return ""


def extract_name(
    data: Any,
) -> str:

    values = recursive_find(
        data,
        [
            "full_name",
            "name",
            "person_name",
        ],
    )

    for value in values:

        if isinstance(
            value,
            str,
        ) and len(value.split()) >= 2:

            return value.strip()

    return ""


def extract_current_company(
    data: Any,
) -> str:

    values = recursive_find(
        data,
        [
            "current_company",
            "company_name",
            "employer",
            "organization",
            "current_employer",
        ],
    )

    candidates = []

    for value in values:

        if isinstance(
            value,
            str,
        ):

            if len(value.strip()) > 1:
                candidates.append(
                    value.strip()
                )

        elif isinstance(
            value,
            dict,
        ):

            for key in [
                "name",
                "company_name",
                "title",
            ]:

                if key in value:

                    candidates.append(
                        clean_text(
                            value[key]
                        )
                    )

    return (
        candidates[0]
        if candidates
        else ""
    )


def extract_current_title(
    data: Any,
) -> str:

    values = recursive_find(
        data,
        [
            "current_title",
            "job_title",
            "designation",
            "title",
            "headline",
            "position",
        ],
    )

    for value in values:

        if isinstance(
            value,
            str,
        ):

            value = value.strip()

            if len(value) > 2:
                return value

    return ""


def extract_location(
    data: Any,
) -> str:

    values = recursive_find(
        data,
        [
            "location",
            "city",
            "current_location",
        ],
    )

    for value in values:

        if isinstance(
            value,
            str,
        ):

            value = value.strip()

            if len(value) > 2:
                return value

        elif isinstance(
            value,
            dict,
        ):

            parts = []

            for key in [
                "city",
                "state",
                "country",
                "name",
            ]:

                if key in value:
                    parts.append(
                        clean_text(
                            value[key]
                        )
                    )

            if parts:
                return ", ".join(
                    unique(parts)
                )

    return ""


# ============================================================
# MATCHING ENGINE
# ============================================================

def company_match_score(
    target: str,
    actual: str,
) -> int:

    target_norm = normalize_company_name(
        target
    )

    actual_norm = normalize_company_name(
        actual
    )

    if not target_norm or not actual_norm:
        return 0

    if target_norm == actual_norm:
        return 100

    if (
        target_norm in actual_norm
        or actual_norm in target_norm
    ):
        return 90

    target_words = set(
        target_norm.split()
    )

    actual_words = set(
        actual_norm.split()
    )

    if not target_words:
        return 0

    overlap = (
        len(
            target_words
            & actual_words
        )
        / len(target_words)
    )

    if overlap >= 0.8:
        return 80

    if overlap >= 0.5:
        return 60

    return 0


def title_match_score(
    target_persona: str,
    actual_title: str,
) -> int:

    target = target_persona.lower()
    actual = actual_title.lower()

    if not actual:
        return 0

    # Exact / abbreviation matches
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
        "it head": [
            "head of it",
            "it head",
            "head it",
        ],
        "head of it": [
            "head of it",
            "it head",
        ],
        "head of technology": [
            "head of technology",
            "technology head",
            "head technology",
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

    if target in aliases:

        for alias in aliases[target]:

            if alias in actual:
                return 100

    if target in actual:
        return 100

    target_words = [
        word
        for word in re.findall(
            r"[a-z]+",
            target,
        )
        if len(word) > 2
    ]

    if not target_words:
        return 0

    matched = sum(
        word in actual
        for word in target_words
    )

    ratio = (
        matched / len(target_words)
    )

    if ratio >= 0.8:
        return 85

    if ratio >= 0.5:
        return 70

    if ratio > 0:
        return 40

    return 0


def location_match_score(
    target_location: str,
    actual_location: str,
) -> int:

    target = target_location.lower()
    actual = actual_location.lower()

    if not actual:
        return 0

    target_tokens = [
        token
        for token in re.findall(
            r"[a-z]+",
            target,
        )
        if len(token) > 2
    ]

    if not target_tokens:
        return 0

    matched = sum(
        token in actual
        for token in target_tokens
    )

    ratio = (
        matched / len(target_tokens)
    )

    if ratio >= 0.7:
        return 100

    if ratio >= 0.4:
        return 60

    return 20


def seniority_score(
    persona: str,
    title: str,
) -> int:

    text_value = (
        persona + " " + title
    ).lower()

    if any(
        x in text_value
        for x in [
            "cto",
            "cio",
            "ciso",
            "chief",
        ]
    ):
        return 100

    if any(
        x in text_value
        for x in [
            "vp",
            "vice president",
        ]
    ):
        return 90

    if "director" in text_value:
        return 85

    if "head" in text_value:
        return 85

    if "manager" in text_value:
        return 70

    if "administrator" in text_value:
        return 50

    return 30


# ============================================================
# VERIFICATION ENGINE
# ============================================================

def verify_person(
    target_company: str,
    target_location: str,
    requested_persona: str,
    profile_data: Dict[str, Any],
) -> Dict[str, Any]:

    current_company = extract_current_company(
        profile_data
    )

    current_title = extract_current_title(
        profile_data
    )

    actual_location = extract_location(
        profile_data
    )

    linkedin_url = extract_linkedin_url(
        profile_data
    )

    name = extract_name(
        profile_data
    )

    company_score = company_match_score(
        target_company,
        current_company,
    )

    title_score = title_match_score(
        requested_persona,
        current_title,
    )

    location_score = location_match_score(
        target_location,
        actual_location,
    )

    seniority = seniority_score(
        requested_persona,
        current_title,
    )

    # IMPORTANT:
    # Company is weighted most heavily because
    # the main problem is people who no longer
    # work for the target organization.

    total = round(
        (
            company_score * 0.45
            +
            title_score * 0.30
            +
            location_score * 0.10
            +
            seniority * 0.15
        ),
        1,
    )

    if company_score < 80:

        status = "REJECTED"

        reason = (
            "Current employer does not "
            "sufficiently match target company."
        )

    elif title_score < 70:

        status = "REVIEW"

        reason = (
            "Current employer matches, "
            "but current designation does "
            "not sufficiently match requested persona."
        )

    elif total >= 85:

        status = "VERIFIED"

        reason = (
            "Current employer and "
            "current designation match."
        )

    elif total >= 70:

        status = "HIGH CONFIDENCE"

        reason = (
            "Strong account/persona match "
            "but manual review recommended."
        )

    else:

        status = "REVIEW"

        reason = (
            "Insufficient evidence for "
            "automatic verification."
        )

    return {
        "Name": name,
        "LinkedIn": linkedin_url,
        "Current Company": current_company,
        "Current Title": current_title,
        "Current Location": actual_location,
        "Requested Persona": requested_persona,
        "Company Match Score": company_score,
        "Title Match Score": title_score,
        "Location Match Score": location_score,
        "Seniority Score": seniority,
        "Verification Score": total,
        "Verification Status": status,
        "Verification Reason": reason,
    }


# ============================================================
# EXTRACT CANDIDATE RECORDS FROM ZINTLR
# ============================================================

def extract_candidate_objects(
    data: Any,
) -> List[Dict[str, Any]]:

    candidates = []

    def walk(value: Any):

        if isinstance(
            value,
            dict,
        ):

            # Identify likely person records.
            keys = {
                key.lower()
                for key in value.keys()
            }

            has_person_signal = (
                any(
                    "linkedin" in key
                    for key in keys
                )
                or any(
                    "person" in key
                    for key in keys
                )
                or any(
                    "job_title" in key
                    for key in keys
                )
                or any(
                    "designation" in key
                    for key in keys
                )
            )

            if has_person_signal:

                candidates.append(
                    value
                )

            for item in value.values():
                walk(item)

        elif isinstance(
            value,
            list,
        ):

            for item in value:
                walk(item)

    walk(data)

    # Deduplicate using LinkedIn URL where possible.
    unique_records = []
    seen = set()

    for record in candidates:

        linkedin = extract_linkedin_url(
            record
        )

        key = linkedin or safe_json(
            record
        )

        if key in seen:
            continue

        seen.add(key)

        unique_records.append(
            record
        )

    return unique_records


# ============================================================
# PERSONA DISCOVERY + VERIFICATION
# ============================================================

def discover_and_verify_personas(
    company_name: str,
    location: str,
    personas: List[str],
    access_token: str,
    secret_key: str,
    max_candidates: int,
) -> pd.DataFrame:

    rows = []

    total = len(personas)

    progress = st.progress(
        0,
        text="Finding verified personas...",
    )

    for index, persona in enumerate(
        personas
    ):

        try:

            # ------------------------------------------------
            # STEP 1
            # ZINTLR AI PEOPLE SEARCH
            # ------------------------------------------------

            ai_result = zintlr_ai_people_search(
                company_name,
                location,
                persona,
                access_token,
                secret_key,
                max_candidates,
            )

            records = extract_candidate_objects(
                ai_result
            )

            # ------------------------------------------------
            # STEP 2
            # FALLBACK TO STRUCTURED PEOPLE SEARCH
            # ------------------------------------------------

            if not records:

                structured_result = (
                    zintlr_people_search(
                        company_name,
                        location,
                        persona,
                        access_token,
                        secret_key,
                        max_candidates,
                    )
                )

                records = (
                    extract_candidate_objects(
                        structured_result
                    )
                )

            # ------------------------------------------------
            # STEP 3
            # VERIFY EACH PERSON THROUGH
            # LINKEDIN PROFILE DATA
            # ------------------------------------------------

            for candidate in records:

                linkedin_url = (
                    extract_linkedin_url(
                        candidate
                    )
                )

                if not linkedin_url:
                    continue

                try:

                    profile = (
                        zintlr_profile_lookup(
                            linkedin_url,
                            access_token,
                            secret_key,
                        )
                    )

                    profile_records = (
                        extract_candidate_objects(
                            profile
                        )
                    )

                    if profile_records:

                        # Usually the first record
                        # corresponds to the requested URL.
                        profile_data = (
                            profile_records[0]
                        )

                    else:

                        profile_data = profile

                    verified = verify_person(
                        company_name,
                        location,
                        persona,
                        profile_data,
                    )

                    verified[
                        "Source"
                    ] = "Zintlr"

                    verified[
                        "Verification Timestamp"
                    ] = time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    verified[
                        "Raw Profile"
                    ] = safe_json(
                        profile_data
                    )

                    rows.append(
                        verified
                    )

                except Exception as exc:

                    rows.append(
                        {
                            "Name": extract_name(
                                candidate
                            ),
                            "LinkedIn": linkedin_url,
                            "Current Company": "",
                            "Current Title": "",
                            "Current Location": "",
                            "Requested Persona": persona,
                            "Company Match Score": 0,
                            "Title Match Score": 0,
                            "Location Match Score": 0,
                            "Seniority Score": 0,
                            "Verification Score": 0,
                            "Verification Status": "ERROR",
                            "Verification Reason": str(
                                exc
                            ),
                            "Source": "Zintlr",
                            "Verification Timestamp": time.strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "Raw Profile": "",
                        }
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

    # Remove duplicates by LinkedIn.
    if "LinkedIn" in df.columns:

        df = df.drop_duplicates(
            subset=[
                "LinkedIn",
                "Requested Persona",
            ]
        )

    # Sort by verification score.
    df = df.sort_values(
        by="Verification Score",
        ascending=False,
    )

    return df.reset_index(
        drop=True
    )


# ============================================================
# BUILTWITH
# ============================================================

def builtwith_lookup(
    domain: str,
    api_key: str,
) -> Dict[str, Any]:

    if not api_key:
        raise RuntimeError(
            "BuiltWith API key is missing."
        )

    if not domain:
        raise RuntimeError(
            "Domain is required."
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

        if isinstance(
            value,
            dict,
        ):

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

                        walk_technology(
                            item
                        )

                    else:

                        walk(item)

                elif isinstance(
                    item,
                    str,
                ):

                    if any(
                        x in key_lower
                        for x in [
                            "technology",
                            "technologyname",
                        ]
                    ):

                        technologies.append(
                            item
                        )

                    if "category" in key_lower:

                        categories.append(
                            item
                        )

        elif isinstance(
            value,
            list,
        ):

            for item in value:
                walk(item)

    def walk_technology(
        value: Any
    ):

        if isinstance(
            value,
            dict,
        ):

            for key, item in value.items():

                if key.lower() in [
                    "name",
                    "technology",
                    "tech",
                ]:

                    if isinstance(
                        item,
                        str,
                    ):

                        technologies.append(
                            item
                        )

                walk_technology(
                    item
                )

        elif isinstance(
            value,
            list,
        ):

            for item in value:
                walk_technology(
                    item
                )

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

    text_value = (
        " ".join(
            technologies
            + categories
        )
        .lower()
    )

    result = []

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
        "cisco",
        "okta",
        "cloudflare",
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

    if any(
        x in text_value
        for x in cloud
    ):

        result.append(
            "Cloud / Infrastructure"
        )

    if any(
        x in text_value
        for x in security
    ):

        result.append(
            "Cybersecurity / Security"
        )

    if any(
        x in text_value
        for x in enterprise
    ):

        result.append(
            "Enterprise Technology"
        )

    if any(
        x in text_value
        for x in data
    ):

        result.append(
            "Data / Analytics"
        )

    return result


# ============================================================
# CONTACT EXTRACTION
# ============================================================

def extract_contacts(
    data: Any,
) -> Tuple[List[str], List[str]]:

    emails = []
    phones = []

    def walk(value: Any):

        if isinstance(
            value,
            dict,
        ):

            for key, item in value.items():

                key_lower = key.lower()

                if isinstance(
                    item,
                    (dict, list),
                ):

                    walk(item)

                elif isinstance(
                    item,
                    str,
                ):

                    if (
                        "email" in key_lower
                        and "@" in item
                    ):

                        emails.append(
                            item.strip()
                        )

                    if any(
                        x in key_lower
                        for x in [
                            "phone",
                            "mobile",
                            "telephone",
                        ]
                    ):

                        if item.strip():
                            phones.append(
                                item.strip()
                            )

        elif isinstance(
            value,
            list,
        ):

            for item in value:
                walk(item)

    walk(data)

    return (
        unique(emails),
        unique(phones),
    )


# ============================================================
# CONTACT ENRICHMENT
# ============================================================

def enrich_verified_personas(
    df: pd.DataFrame,
    selected_urls: List[str],
    access_token: str,
    secret_key: str,
    email_unlock: bool,
    phone_unlock: bool,
) -> pd.DataFrame:

    df = df.copy()

    for linkedin_url in selected_urls:

        matches = df.index[
            df["LinkedIn"]
            == linkedin_url
        ].tolist()

        if not matches:
            continue

        idx = matches[0]

        # Safety rule:
        # never enrich rejected profiles.
        if df.at[
            idx,
            "Verification Status",
        ] not in [
            "VERIFIED",
            "HIGH CONFIDENCE",
        ]:

            df.at[
                idx,
                "Contact Status",
            ] = (
                "Blocked - persona not verified"
            )

            continue

        try:

            result = zintlr_contact_lookup(
                linkedin_url,
                access_token,
                secret_key,
                email_unlock,
                phone_unlock,
            )

            emails, phones = (
                extract_contacts(
                    result
                )
            )

            df.at[
                idx,
                "Business Email",
            ] = ", ".join(
                emails
            )

            df.at[
                idx,
                "Phone",
            ] = ", ".join(
                phones
            )

            df.at[
                idx,
                "Contact Status",
            ] = "Enriched"

            df.at[
                idx,
                "Contact Evidence",
            ] = safe_json(
                result
            )

        except Exception as exc:

            df.at[
                idx,
                "Contact Status",
            ] = f"Error: {exc}"

    return df


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header(
        "⚙️ Configuration"
    )

    st.markdown(
        "### Search"
    )

    serper_key = st.text_input(
        "Serper API Key",
        value=st.secrets.get(
            "SERPER_API_KEY",
            "",
        ),
        type="password",
    )

    st.markdown(
        "### Zintlr"
    )

    zintlr_access = st.text_input(
        "Zintlr Access Token",
        value=st.secrets.get(
            "ZINTLR_ACCESS_TOKEN",
            "",
        ),
        type="password",
    )

    zintlr_secret = st.text_input(
        "Zintlr Secret Key",
        value=st.secrets.get(
            "ZINTLR_SECRET_KEY",
            "",
        ),
        type="password",
    )

    st.markdown(
        "### BuiltWith"
    )

    builtwith_key = st.text_input(
        "BuiltWith API Key",
        value=st.secrets.get(
            "BUILTWITH_API_KEY",
            "",
        ),
        type="password",
    )

    st.markdown(
        "### Contact Enrichment"
    )

    email_unlock = st.checkbox(
        "Unlock Email",
        value=True,
    )

    phone_unlock = st.checkbox(
        "Unlock Phone",
        value=True,
    )

    st.markdown(
        "### Persona Configuration"
    )

    persona_group = st.selectbox(
        "Persona Group",
        [
            "All",
            *PERSONA_GROUPS.keys(),
            "Custom CSV",
        ],
    )

    if persona_group == "All":

        personas = DEFAULT_PERSONAS

    elif persona_group in PERSONA_GROUPS:

        personas = PERSONA_GROUPS[
            persona_group
        ]

    else:

        uploaded = st.file_uploader(
            "Upload persona CSV",
            type=["csv"],
        )

        if uploaded:

            try:

                uploaded_df = pd.read_csv(
                    uploaded
                )

                personas = (
                    uploaded_df
                    .iloc[:, 0]
                    .dropna()
                    .astype(str)
                    .tolist()
                )

            except Exception:

                personas = DEFAULT_PERSONAS

        else:

            personas = DEFAULT_PERSONAS

    max_candidates = st.slider(
        "Candidates per persona",
        min_value=1,
        max_value=20,
        value=10,
    )

    st.caption(
        f"{len(personas)} persona searches configured."
    )


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="title">'
    '🎯 360° Account Intelligence'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="subtitle">'
    'Verified Account → Verified Persona → '
    'Technology → Contact → Outreach'
    '</div>',
    unsafe_allow_html=True,
)


# ============================================================
# ACCOUNT INPUT
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
# RUN WORKFLOW
# ============================================================

if st.button(
    "🚀 Run Complete Account Intelligence",
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

    if not zintlr_access:

        st.error(
            "Zintlr Access Token is required."
        )

        st.stop()

    if not zintlr_secret:

        st.error(
            "Zintlr Secret Key is required."
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
    st.session_state.candidates = pd.DataFrame()
    st.session_state.verified = pd.DataFrame()
    st.session_state.selected = []
    st.session_state.enriched = pd.DataFrame()

    # --------------------------------------------------------
    # COMPANY DOMAIN
    # --------------------------------------------------------

    with st.spinner(
        "Resolving company website..."
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
        "Collecting Zauba company evidence..."
    ):

        try:

            zauba = get_zauba_evidence(
                company_name,
                location,
                serper_key,
            )

        except Exception as exc:

            zauba = {
                "status": f"Error: {exc}",
                "records": [],
            }

    # --------------------------------------------------------
    # TOFLER
    # --------------------------------------------------------

    with st.spinner(
        "Collecting Tofler company evidence..."
    ):

        try:

            tofler = get_tofler_evidence(
                company_name,
                location,
                serper_key,
            )

        except Exception as exc:

            tofler = {
                "status": f"Error: {exc}",
                "records": [],
            }

    # --------------------------------------------------------
    # ZINTLR COMPANY IDENTITY
    # --------------------------------------------------------

    zintlr_company = {}

    if domain:

        with st.spinner(
            "Resolving company through Zintlr..."
        ):

            try:

                zintlr_company = (
                    zintlr_domain_to_company(
                        domain,
                        zintlr_access,
                        zintlr_secret,
                    )
                )

            except Exception as exc:

                zintlr_company = {
                    "error": str(exc)
                }

    # --------------------------------------------------------
    # STORE COMPANY DATA
    # --------------------------------------------------------

    st.session_state.company = {
        "company_name": company_name,
        "location": location,
        "domain": domain,
        "domain_confidence": domain_result.get(
            "confidence"
        ),
        "domain_evidence": domain_result.get(
            "evidence",
            [],
        ),
        "zauba": zauba,
        "tofler": tofler,
        "zintlr_company": zintlr_company,
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

    if builtwith_key and domain:

        with st.spinner(
            "Scanning technology stack..."
        ):

            try:

                raw = builtwith_lookup(
                    domain,
                    builtwith_key,
                )

                technologies, categories = (
                    parse_builtwith(
                        raw
                    )
                )

                technology = {
                    "status": "Live BuiltWith API",
                    "domain": domain,
                    "technologies": technologies,
                    "categories": categories,
                    "solution_fit": determine_solution_fit(
                        technologies,
                        categories,
                    ),
                    "raw": raw,
                }

            except Exception as exc:

                technology = {
                    "status": f"BuiltWith error: {exc}",
                    "domain": domain,
                    "technologies": [],
                    "categories": [],
                    "solution_fit": [],
                    "raw": {},
                }

    st.session_state.technology = (
        technology
    )

    # --------------------------------------------------------
    # VERIFIED PERSONA DISCOVERY
    # --------------------------------------------------------

    with st.spinner(
        "Finding and verifying current personas..."
    ):

        verified_df = (
            discover_and_verify_personas(
                company_name,
                location,
                personas,
                zintlr_access,
                zintlr_secret,
                max_candidates,
            )
        )

    # Attach technology context.

    if not verified_df.empty:

        verified_df[
            "Technology Stack"
        ] = ", ".join(
            technology.get(
                "technologies",
                [],
            )
        )

        verified_df[
            "Solution Fit"
        ] = "; ".join(
            technology.get(
                "solution_fit",
                [],
            )
        )

    st.session_state.verified = (
        verified_df
    )

    st.success(
        "Account intelligence completed."
    )


# ============================================================
# LOAD STATE
# ============================================================

company_data = (
    st.session_state.company
)

technology_data = (
    st.session_state.technology
)

verified_df = (
    st.session_state.verified
)


# ============================================================
# RESULTS
# ============================================================

if company_data:

    st.divider()

    st.subheader(
        "2. 360° Account Profile"
    )

    tabs = st.tabs(
        [
            "🏢 Account",
            "💻 Technology",
            "👤 Personas",
            "🎯 Verification",
            "📇 Contact",
            "🚀 Outreach",
            "🔬 Evidence",
        ]
    )


    # ========================================================
    # ACCOUNT
    # ========================================================

    with tabs[0]:

        st.markdown(
            f"""
            <div class="box blue">

            <b>Company:</b>
            {company_data.get("company_name", "")}

            <br><br>

            <b>Location:</b>
            {company_data.get("location", "")}

            <br><br>

            <b>Domain:</b>
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

            if zauba.get(
                "records"
            ):

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

            if tofler.get(
                "records"
            ):

                st.dataframe(
                    pd.DataFrame(
                        tofler[
                            "records"
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        st.subheader(
            "Zintlr Company Identity"
        )

        st.json(
            company_data.get(
                "zintlr_company",
                {},
            )
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
                    len(
                        technologies
                    ),
                )
            )

            for index, tech in enumerate(
                technologies
            ):

                cols[
                    index
                    % len(cols)
                ].success(
                    tech
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

                st.success(
                    item
                )

        else:

            st.info(
                "No solution-fit indicators."
            )


    # ========================================================
    # PERSONAS
    # ========================================================

    with tabs[2]:

        st.subheader(
            "Persona Intelligence"
        )

        if verified_df.empty:

            st.warning(
                "No candidate personas found."
            )

        else:

            display = verified_df[
                [
                    "Name",
                    "Current Company",
                    "Current Title",
                    "Current Location",
                    "Requested Persona",
                    "Verification Score",
                    "Verification Status",
                    "LinkedIn",
                ]
            ]

            st.dataframe(
                display,
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

        if verified_df.empty:

            st.info(
                "Nothing to verify."
            )

        else:

            status_counts = (
                verified_df[
                    "Verification Status"
                ]
                .value_counts()
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Verified",
                int(
                    status_counts.get(
                        "VERIFIED",
                        0,
                    )
                ),
            )

            c2.metric(
                "High Confidence",
                int(
                    status_counts.get(
                        "HIGH CONFIDENCE",
                        0,
                    )
                ),
            )

            c3.metric(
                "Review",
                int(
                    status_counts.get(
                        "REVIEW",
                        0,
                    )
                ),
            )

            c4.metric(
                "Rejected",
                int(
                    status_counts.get(
                        "REJECTED",
                        0,
                    )
                ),
            )

            st.markdown(
                "### Verification Rules"
            )

            st.write(
                "• Current company mismatch → REJECTED"
            )

            st.write(
                "• Current title mismatch → REVIEW"
            )

            st.write(
                "• Strong company + title match → VERIFIED"
            )

            st.write(
                "• Contact enrichment is blocked for rejected/review records."
            )

            st.markdown(
                "### Detailed Verification"
            )

            st.dataframe(
                verified_df[
                    [
                        "Name",
                        "Requested Persona",
                        "Current Company",
                        "Current Title",
                        "Current Location",
                        "Company Match Score",
                        "Title Match Score",
                        "Location Match Score",
                        "Seniority Score",
                        "Verification Score",
                        "Verification Status",
                        "Verification Reason",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )


    # ========================================================
    # CONTACT
    # ========================================================

    with tabs[4]:

        st.subheader(
            "Contact Profiling"
        )

        verified_only = verified_df[
            verified_df[
                "Verification Status"
            ].isin(
                [
                    "VERIFIED",
                    "HIGH CONFIDENCE",
                ]
            )
        ].copy()

        if verified_only.empty:

            st.warning(
                "No verified personas are available for enrichment."
            )

        else:

            labels = {}

            for _, row in verified_only.iterrows():

                label = (
                    f"{row['Name']} | "
                    f"{row['Current Title']} | "
                    f"{row['Verification Score']}"
                )

                labels[label] = row[
                    "LinkedIn"
                ]

            selected_labels = st.multiselect(
                "Select verified personas for contact enrichment",
                list(labels.keys()),
            )

            selected_urls = [
                labels[x]
                for x in selected_labels
            ]

            st.session_state.selected = (
                selected_urls
            )

            if selected_urls:

                st.dataframe(
                    verified_only[
                        verified_only[
                            "LinkedIn"
                        ].isin(
                            selected_urls
                        )
                    ][
                        [
                            "Name",
                            "Current Company",
                            "Current Title",
                            "LinkedIn",
                            "Verification Score",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

            if st.button(
                "📇 Enrich Verified Contacts",
                type="primary",
                use_container_width=True,
            ):

                if not selected_urls:

                    st.warning(
                        "Select at least one verified persona."
                    )

                    st.stop()

                with st.spinner(
                    "Enriching verified contacts..."
                ):

                    enriched = (
                        enrich_verified_personas(
                            verified_df,
                            selected_urls,
                            zintlr_access,
                            zintlr_secret,
                            email_unlock,
                            phone_unlock,
                        )
                    )

                st.session_state.enriched = (
                    enriched[
                        enriched[
                            "LinkedIn"
                        ].isin(
                            selected_urls
                        )
                    ].copy()
                )

                st.success(
                    "Contact enrichment completed."
                )

                st.rerun()


    # ========================================================
    # OUTREACH
    # ========================================================

    with tabs[5]:

        st.subheader(
            "Profiled & Outreach-Ready Leads"
        )

        enriched = (
            st.session_state.enriched
        )

        if enriched.empty:

            st.info(
                "No contacts have been enriched yet."
            )

        else:

            for _, lead in enriched.iterrows():

                status = lead.get(
                    "Verification Status",
                    "",
                )

                if status in [
                    "VERIFIED",
                    "HIGH CONFIDENCE",
                ]:

                    st.markdown(
                        f"""
                        <div class="box green">

                        <h3>
                        {lead.get("Name", "")}
                        </h3>

                        <b>Account:</b>
                        {lead.get("Current Company", "")}

                        <br>

                        <b>Title:</b>
                        {lead.get("Current Title", "")}

                        <br>

                        <b>Persona:</b>
                        {lead.get("Requested Persona", "")}

                        <br>

                        <b>Verification:</b>
                        {lead.get("Verification Score", "")}/100

                        <br>

                        <b>Email:</b>
                        {lead.get("Business Email", "") or "Not available"}

                        <br>

                        <b>Phone:</b>
                        {lead.get("Phone", "") or "Not available"}

                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    st.write(
                        f"LinkedIn: {lead.get('LinkedIn', '')}"
                    )

                    st.write(
                        f"Technology: {lead.get('Technology Stack', '')}"
                    )

                    st.write(
                        f"Solution Fit: {lead.get('Solution Fit', '')}"
                    )

            export_columns = [
                "Name",
                "Current Company",
                "Current Title",
                "Current Location",
                "Requested Persona",
                "LinkedIn",
                "Business Email",
                "Phone",
                "Verification Score",
                "Verification Status",
                "Verification Reason",
                "Technology Stack",
                "Solution Fit",
                "Contact Status",
            ]

            export_columns = [
                x
                for x in export_columns
                if x in enriched.columns
            ]

            export_df = enriched[
                export_columns
            ]

            st.download_button(
                "⬇️ Download Outreach-Ready Leads",
                export_df.to_csv(
                    index=False
                ).encode(
                    "utf-8"
                ),
                file_name=(
                    re.sub(
                        r"[^A-Za-z0-9]+",
                        "_",
                        company_name,
                    )
                    + "_verified_leads.csv"
                ),
                mime="text/csv",
                use_container_width=True,
            )


    # ========================================================
    # EVIDENCE
    # ========================================================

    with tabs[6]:

        st.subheader(
            "Source Evidence & Audit Trail"
        )

        st.markdown(
            """
            <div class="box yellow">
            <b>Accuracy principle:</b>
            Every important decision is based on an identifiable
            source. Search results are treated as discovery/evidence,
            while structured Zintlr profile data is used for
            current-person verification.
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            "### Company Domain Evidence"
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
            "### Zintlr Company Identity"
        )

        st.json(
            company_data.get(
                "zintlr_company",
                {},
            )
        )

        st.markdown(
            "### BuiltWith Raw Data"
        )

        st.json(
            technology_data.get(
                "raw",
                {},
            )
        )

        if not verified_df.empty:

            st.markdown(
                "### Persona Verification Evidence"
            )

            for _, row in verified_df.iterrows():

                with st.expander(
                    f"{row.get('Name', '')} — "
                    f"{row.get('Verification Status', '')}"
                ):

                    st.write(
                        "Verification Reason:",
                        row.get(
                            "Verification Reason",
                            "",
                        ),
                    )

                    st.write(
                        "Verification Score:",
                        row.get(
                            "Verification Score",
                            "",
                        ),
                    )

                    raw_profile = row.get(
                        "Raw Profile",
                        "",
                    )

                    if raw_profile:

                        try:

                            st.json(
                                json.loads(
                                    raw_profile
                                )
                            )

                        except Exception:

                            st.code(
                                raw_profile
                            )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "360° Account Intelligence | "
    "Company validation + verified current personas + "
    "technographics + contact enrichment"
)
