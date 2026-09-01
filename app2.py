```python
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

        # Exact persona + company
        (
            f'site:linkedin.com/in/ '
            f'"{company}" '
            f'"{persona}" '
            f'"{location}"'
        ),

        # Company + persona
        (
            f'site:linkedin.com/in/ '
            f'"{company}" '
            f'"{persona}"'
        ),

        # Current employment wording
        (
            f'site:linkedin.com/in/ '
            f'"{persona}" '
            f'"{company}" '
            f'"present"'
        ),

        # Company + current title
        (
            f'site:linkedin.com/in/ '
            f'"{company}" '
            f'"{persona}" '
            f'"current"'
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
# CURRENTNESS SCORE
# ============================================================

def currentness_score(
    text: str,
) -> int:

    text = clean(text).lower()

    positive = [
        "present",
        "currently",
        "current",
        "working at",
        "works at",
        "at ",

    ]

    negative = [
        "former",
        "previously",
        "ex-",
        "ex ",
        "past",
        "left ",
        "retired",
        "advisor",
        "consultant",
    ]

    positive_hits = sum(
        x in text
        for x in positive
    )

    negative_hits = sum(
        x in text
        for x in negative
    )

    if negative_hits > positive_hits:
        return 0

    if positive_hits >= 2:
        return 100

    if positive_hits == 1:
        return 70

    return 40


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

    name = clean(
        profile.get("Name")
    )

    linkedin = clean(
        profile.get("LinkedIn")
    )

    search_title = clean(
        profile.get(
            "Title from Search"
        )
    )

    snippet = clean(
        profile.get("Snippet")
    )

    all_evidence_text = (
        search_title
        + " "
        + snippet
        + " "
        + safe_json(
            cross_validation
        )
    )

    company_match = company_score(
        company,
        all_evidence_text,
    )

    persona_match = title_score(
        requested_persona,
        search_title
        + " "
        + snippet,
    )

    location_match = location_score(
        location,
        all_evidence_text,
    )

    currentness = currentness_score(
        all_evidence_text,
    )

    # Number of independent search queries
    # which produced relevant evidence.
    evidence_hits = 0

    for block in cross_validation.get(
        "evidence",
        [],
    ):

        query_text = safe_json(
            block
        ).lower()

        company_found = (
            normalize_company_name(
                company
            )
            in normalize_company_name(
                query_text
            )
        )

        persona_found = (
            requested_persona.lower()
            in query_text
        )

        if company_found and persona_found:
            evidence_hits += 1

    evidence_score = min(
        100,
        evidence_hits * 25,
    )

    # --------------------------------------------------------
    # FINAL SCORE
    # --------------------------------------------------------

    final_score = round(
        (
            company_match * 0.35
            + persona_match * 0.30
            + currentness * 0.20
            + location_match * 0.05
            + evidence_score * 0.10
        ),
        1,
    )

    # --------------------------------------------------------
    # STRICT DECISION LOGIC
    # --------------------------------------------------------

    if company_match < 60:

        status = "REJECTED"

        reason = (
            "Insufficient evidence that the "
            "person is associated with the "
            "target company."
        )

    elif persona_match < 70:

        status = "REVIEW"

        reason = (
            "Company association appears "
            "possible, but the requested "
            "persona/title does not match strongly."
        )

    elif currentness == 0:

        status = "REJECTED"

        reason = (
            "Evidence contains indicators "
            "that the person may be a former "
            "employee, advisor, consultant, "
            "or otherwise not currently employed."
        )

    elif final_score >= 85 and evidence_hits >= 2:

        status = "VERIFIED"

        reason = (
            "Strong company, persona and "
            "current-employment evidence "
            "across multiple searches."
        )

    elif final_score >= 70:

        status = "HIGH CONFIDENCE"

        reason = (
            "Strong match, but additional "
            "manual validation is recommended."
        )

    else:

        status = "REVIEW"

        reason = (
            "Evidence is insufficient for "
            "automatic verification."
        )

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
        value=st.secrets.get(
            "SERPER_API_KEY",
            "",
        ),
        type="password",
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

    st.info(
        "Zintlr is intentionally not required "
        "for this version. Contact enrichment "
        "is therefore not performed."
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

            display_columns = [
                "Name",
                "Requested Persona",
                "Search Title",
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

                st.success(
                    f"{len(verified)} persona(s) "
                    "passed strict verification."
                )

                for _, row in verified.iterrows():

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

                        <b>Search Title:</b>
                        {row.get("Search Title", "")}

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

                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                export_columns = [
                    "Name",
                    "Requested Persona",
                    "Search Title",
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
                    "⬇️ Download Verified Personas",
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
                    "Contact enrichment is intentionally "
                    "not included until a person-level "
                    "enrichment provider such as Zintlr "
                    "is configured."
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
```
