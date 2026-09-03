
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
        "Director of Technology",
    ],
    "IT Leadership": [
        "CIO",
        "Chief Information Officer",
        "VP IT",
        "Vice President IT",
        "VP Information Technology",
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
        "Director Information Security",
        "Security Director",
    ],
    "Infrastructure": [
        "Head of Infrastructure",
        "Infrastructure Director",
        "Infrastructure Manager",
        "IT Infrastructure Manager",
        "Head Infrastructure",
        "Infrastructure Head",
        "Systems Director",
        "System Administrator",
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


def normalize_text(value: str) -> str:
    value = clean(value).lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_company_name(name: str) -> str:
    value = normalize_text(name)

    remove_terms = [
        "private limited",
        "pvt limited",
        "pvt ltd",
        "pvt",
        "limited",
        "ltd",
        "llp",
        "incorporated",
        "inc",
        "corporation",
        "corp",
        "company",
        "co",
        "technologies",
    ]

    # "technologies" is deliberately removed only from the
    # normalized comparison. The exact company phrase is still
    # retained separately for stronger matching.
    for term in remove_terms:
        value = re.sub(rf"\b{re.escape(term)}\b", " ", value)

    value = re.sub(r"\s+", " ", value)
    return value.strip()


def company_aliases(company: str) -> List[str]:
    original = clean(company)
    normalized = normalize_company_name(company)

    aliases = [
        normalize_text(original),
        normalized,
    ]

    # Add the name without common legal suffixes, but do not
    # invent arbitrary abbreviations.
    original_no_suffix = re.sub(
        r"\b(private limited|pvt\.?\s*ltd\.?|limited|ltd\.?|llp|inc\.?|incorporated|corporation|corp\.?)\b",
        " ",
        original,
        flags=re.I,
    )
    aliases.append(normalize_text(original_no_suffix))

    return unique(aliases)


def normalize_domain(domain: str) -> str:
    domain = clean(domain)
    domain = re.sub(r"^https?://", "", domain, flags=re.I)
    domain = domain.split("/")[0].lower()

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


def unique(values: List[str]) -> List[str]:
    result = []
    seen = set()

    for value in values:
        value = clean(value)
        if value and value.lower() not in seen:
            result.append(value)
            seen.add(value.lower())

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


def token_set(text: str) -> set:
    return set(
        x
        for x in re.findall(r"[a-z0-9]+", normalize_text(text))
        if len(x) > 2
    )


def normalize_person_name(name: str) -> str:
    """Canonicalize a person's name for deduplication."""
    value = normalize_text(name)
    # Remove common profile/company noise accidentally captured from titles.
    value = re.sub(r"\\b(linkedin|profile|official)\\b", " ", value)
    value = re.sub(r"\\s+", " ", value).strip()
    return value


def person_name_key(name: str) -> str:
    """Return a stable key; keeps first/last identity while tolerating initials."""
    parts = normalize_person_name(name).split()
    if not parts:
        return ""
    # Strip single-letter middle initials from the key so
    # "Rahul K Sharma" and "Rahul Sharma" can consolidate.
    if len(parts) >= 3:
        parts = [parts[0]] + [p for p in parts[1:-1] if len(p) > 1] + [parts[-1]]
    return " ".join(parts)


def normalize_linkedin_url(url: str) -> str:
    url = clean(url).split("?")[0].rstrip("/")
    return url.lower()




# ============================================================
# HTTP / SERPER
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


def serper_search(
    query: str,
    api_key: str,
    num: int = 10,
) -> Dict[str, Any]:

    if not api_key:
        raise RuntimeError("Serper API key is missing.")

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
# COMPANY DOMAIN DISCOVERY
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
        "crunchbase.com",
        "glassdoor.co.in",
        "glassdoor.com",
    }

    evidence = []

    for query in queries:
        try:
            result = serper_search(query, serper_key, 10)
        except Exception as exc:
            evidence.append({
                "query": query,
                "error": str(exc),
            })
            continue

        organic = result.get("organic", [])

        evidence.append({
            "query": query,
            "results": organic,
        })

        company_tokens = token_set(company)

        candidates = []

        for item in organic:
            link = clean(item.get("link"))
            title = clean(item.get("title"))
            snippet = clean(item.get("snippet"))

            if not link:
                continue

            match = re.search(
                r"https?://([^/]+)",
                link,
                re.I,
            )

            if not match:
                continue

            domain = normalize_domain(match.group(1))

            if domain in blocked:
                continue

            text = normalize_text(
                f"{title} {snippet} {link}"
            )

            overlap = len(
                company_tokens & token_set(text)
            )

            candidates.append(
                (overlap, domain, link)
            )

        candidates.sort(reverse=True)

        if candidates:
            best_overlap, best_domain, _ = candidates[0]

            # For a company with a reasonably distinctive name,
            # require at least one matching token. We retain the
            # search evidence so the user can inspect it.
            if best_overlap > 0:
                return {
                    "domain": best_domain,
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

    domain = (
        "zaubacorp.com"
        if source == "Zauba"
        else "tofler.in"
    )

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

    for item in result.get("organic", []):
        link = clean(item.get("link"))

        if domain not in link.lower():
            continue

        records.append({
            "title": clean(item.get("title")),
            "url": link,
            "snippet": clean(item.get("snippet")),
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
        raise RuntimeError("Company domain not found.")

    if not api_key:
        raise RuntimeError("BuiltWith API key missing.")

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

    def walk_technology(value: Any):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {
                    "name",
                    "technology",
                    "tech",
                }:
                    if isinstance(item, str):
                        technologies.append(item)
                walk_technology(item)

        elif isinstance(value, list):
            for item in value:
                walk_technology(item)

    def walk(value: Any):
        if isinstance(value, dict):
            for key, item in value.items():
                key_lower = key.lower()

                if isinstance(item, (dict, list)):
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

    walk(data)

    return unique(technologies), unique(categories)


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
        fit.append("Cloud / Infrastructure")

    if any(x in text for x in security):
        fit.append("Cybersecurity / Security")

    if any(x in text for x in enterprise):
        fit.append("Enterprise Technology")

    if any(x in text for x in data):
        fit.append("Data / Analytics")

    return fit


# ============================================================
# TITLE MATCHING
# ============================================================

TITLE_ALIASES = {
    "cto": [
        "cto",
        "chief technology officer",
    ],
    "chief technology officer": [
        "cto",
        "chief technology officer",
    ],
    "cio": [
        "cio",
        "chief information officer",
    ],
    "chief information officer": [
        "cio",
        "chief information officer",
    ],
    "ciso": [
        "ciso",
        "chief information security officer",
    ],
    "chief information security officer": [
        "ciso",
        "chief information security officer",
    ],
    "chief security officer": [
        "cso",
        "chief security officer",
    ],
    "vp it": [
        "vp it",
        "vice president it",
        "vp information technology",
        "vice president information technology",
    ],
    "vice president it": [
        "vp it",
        "vice president it",
        "vp information technology",
        "vice president information technology",
    ],
    "head of it": [
        "head of it",
        "it head",
        "head information technology",
        "head of information technology",
    ],
    "it director": [
        "it director",
        "director it",
        "director of it",
        "director information technology",
        "director of information technology",
    ],
    "it manager": [
        "it manager",
        "manager it",
        "manager of it",
        "information technology manager",
    ],
    "head of technology": [
        "head of technology",
        "technology head",
        "head technology",
    ],
    "technology director": [
        "technology director",
        "director technology",
        "director of technology",
    ],
    "head of cybersecurity": [
        "head of cybersecurity",
        "head of cyber security",
        "cybersecurity head",
        "cyber security head",
    ],
    "head of cyber security": [
        "head of cybersecurity",
        "head of cyber security",
        "cybersecurity head",
        "cyber security head",
    ],
    "head of information security": [
        "head of information security",
        "information security head",
    ],
    "information security manager": [
        "information security manager",
        "security manager",
    ],
    "security director": [
        "security director",
        "director security",
        "director of security",
    ],
    "infrastructure manager": [
        "infrastructure manager",
        "it infrastructure manager",
        "infrastructure head",
        "head infrastructure",
    ],
    "infrastructure director": [
        "infrastructure director",
        "director infrastructure",
        "director of infrastructure",
    ],
    "head of infrastructure": [
        "head of infrastructure",
        "infrastructure head",
    ],
    "systems director": [
        "systems director",
        "director systems",
        "director of systems",
    ],
    "system administrator": [
        "system administrator",
        "systems administrator",
        "sysadmin",
    ],
}


def title_score(
    requested: str,
    title: str,
) -> int:

    requested_norm = normalize_text(requested)
    title_norm = normalize_text(title)

    if not requested_norm or not title_norm:
        return 0

    aliases = TITLE_ALIASES.get(
        requested_norm,
        [requested_norm],
    )

    # Strong exact alias match.
    for alias in aliases:
        if re.search(
            rf"\b{re.escape(alias)}\b",
            title_norm,
        ):
            return 100

    requested_words = token_set(requested_norm)

    if not requested_words:
        return 0

    title_words = token_set(title_norm)

    overlap = len(
        requested_words & title_words
    )

    ratio = overlap / len(requested_words)

    if ratio >= 0.8:
        return 80

    if ratio >= 0.5:
        return 55

    return 0


# ============================================================
# COMPANY EVIDENCE
# ============================================================

def company_match_score(
    company: str,
    evidence_text: str,
) -> int:

    text = normalize_text(evidence_text)

    if not text:
        return 0

    aliases = company_aliases(company)

    # Strongest: exact company phrase.
    for alias in aliases:
        if len(alias) >= 4 and alias in text:
            return 100

    target_tokens = token_set(company)
    evidence_tokens = token_set(text)

    if not target_tokens:
        return 0

    overlap = len(
        target_tokens & evidence_tokens
    )

    ratio = overlap / len(target_tokens)

    if ratio == 1:
        return 90

    if ratio >= 0.75:
        return 60

    return 0


def company_match_strict(
    company: str,
    evidence_text: str,
) -> bool:

    return company_match_score(
        company,
        evidence_text,
    ) >= 90


# ============================================================
# CURRENT EMPLOYMENT DETECTION
# ============================================================

NEGATIVE_EMPLOYMENT_PHRASES = [
    "former",
    "formerly",
    "previously",
    "ex-",
    "ex ",
    "past employee",
    "former employee",
    "previous employer",
    "previous role",
    "previous position",
    "left the company",
    "left company",
    "no longer",
    "retired",
]

CURRENT_EMPLOYMENT_PHRASES = [
    "currently works",
    "currently working",
    "currently serves",
    "currently",
    "works at",
    "working at",
    "serves as",
    "is the current",
    "is currently",
]


def currentness_score(text: str) -> int:

    text_norm = normalize_text(text)

    if not text_norm:
        return 0

    negative_hits = 0

    for phrase in NEGATIVE_EMPLOYMENT_PHRASES:
        if normalize_text(phrase) in text_norm:
            negative_hits += 1

    # Strong negative evidence should be a hard failure.
    if negative_hits > 0:
        return 0

    positive_hits = 0

    for phrase in CURRENT_EMPLOYMENT_PHRASES:
        if normalize_text(phrase) in text_norm:
            positive_hits += 1

    if positive_hits >= 2:
        return 100

    if positive_hits == 1:
        return 85

    # A LinkedIn / person result with company + exact title
    # is possible evidence of current employment, but not enough
    # to award full currentness.
    return 50


# ============================================================
# LINKEDIN RESULT EXTRACTION
# ============================================================

def extract_linkedin_profiles(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    profiles = []
    seen = set()

    for item in results:

        url = clean(item.get("link"))

        if "linkedin.com/in/" not in url.lower():
            continue

        url = url.split("?")[0].rstrip("/")

        if url in seen:
            continue

        seen.add(url)

        title = clean(item.get("title"))
        snippet = clean(item.get("snippet"))

        name = title

        # Google/Serper commonly returns:
        # "Name - Title - Company | LinkedIn"
        parts = [
            x.strip()
            for x in re.split(
                r"\s+-\s+|\s+\|\s+",
                title,
            )
            if x.strip()
        ]

        if parts:
            name = parts[0]

        profiles.append({
            "Name": name,
            "Title from Search": title,
            "LinkedIn": url,
            "Snippet": snippet,
            "Source": "Serper",
        })

    return profiles


# ============================================================
# PERSON DISCOVERY
# ============================================================

def discover_person(
    company: str,
    location: str,
    persona: str,
    serper_key: str,
    max_results: int = 10,
) -> List[Dict[str, Any]]:

    # IMPORTANT:
    # These are discovery queries only.
    # Their existence never counts as verification evidence.
    queries = [
        f'site:linkedin.com/in/ "{company}" "{persona}"',
        f'site:linkedin.com/in/ "{company}" "{persona}" "{location}"',
        f'site:linkedin.com/in/ "{company}" "{persona}" "current"',
        f'site:linkedin.com/in/ "{company}" "{persona}" "present"',
    ]

    all_profiles = []

    for query in queries:

        try:
            result = serper_search(
                query,
                serper_key,
                max_results,
            )
        except Exception:
            continue

        organic = result.get("organic", [])

        profiles = extract_linkedin_profiles(
            organic
        )

        for profile in profiles:
            profile["Discovery Query"] = query
            all_profiles.append(profile)

    merged = {}

    for profile in all_profiles:

        url = profile["LinkedIn"]

        if url not in merged:
            merged[url] = {
                **profile,
                "Discovery Queries": [],
            }

        merged[url]["Discovery Queries"].append(
            profile.get("Discovery Query", "")
        )

    return list(merged.values())


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

    # These searches deliberately vary the evidence being requested.
    # We later inspect the RETURNED RESULTS, never the query string.
    queries = [
        # Exact person + company + role.
        f'"{name}" "{company}" "{persona}"',
        # Exact person + company, without relying on the role query.
        f'"{name}" "{company}"',
        # Target the candidate's actual LinkedIn profile.
        f'"{linkedin_url}"',
        # Look for current-role language around this exact person.
        f'"{name}" "{company}" ("currently" OR "works at" OR "serves as")',
        # Look for dated/current employment evidence.
        f'"{name}" "{company}" "{location}" ("2026" OR "2025" OR "2024")',
        # Explicit contradiction search.
        f'"{name}" "{company}" ("former" OR "formerly" OR "previously" OR "ex-" OR "left")',
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

            for item in organic:

                title = clean(item.get("title"))
                snippet = clean(item.get("snippet"))
                url = clean(item.get("link"))

                evidence.append({
                    "query": query,
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                    "text": (
                        f"{title} {snippet} {url}"
                    ),
                    "is_target_linkedin": (
                        linkedin_url.rstrip("/").lower()
                        in url.rstrip("/").lower()
                    ),
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
# EVIDENCE ANALYSIS
# ============================================================

def analyze_evidence(
    name: str,
    company: str,
    location: str,
    requested_persona: str,
    linkedin_url: str,
    profile: Dict[str, Any],
    cross_validation: Dict[str, Any],
) -> Dict[str, Any]:

    search_title = clean(
        profile.get("Title from Search")
    )

    snippet = clean(
        profile.get("Snippet")
    )

    discovery_text = (
        f"{search_title} {snippet}"
    )

    # --------------------------------------------------------
    # Candidate's own LinkedIn search result
    # --------------------------------------------------------

    candidate_company = company_match_score(
        company,
        discovery_text,
    )

    candidate_title = title_score(
        requested_persona,
        discovery_text,
    )

    candidate_currentness = currentness_score(
        discovery_text,
    )

    # --------------------------------------------------------
    # Actual returned cross-validation results
    # --------------------------------------------------------

    actual_results = []

    for item in cross_validation.get(
        "evidence",
        [],
    ):

        if item.get("error"):
            continue

        text = clean(item.get("text"))

        if not text:
            continue

        actual_results.append(item)

    strong_company_results = []
    strong_role_results = []
    strong_current_results = []
    negative_results = []
    target_profile_results = []

    for item in actual_results:

        text = item.get("text", "")

        company_score = company_match_score(
            company,
            text,
        )

        role_score = title_score(
            requested_persona,
            text,
        )

        current_score = currentness_score(
            text,
        )

        name_present = (
            normalize_text(name)
            in normalize_text(text)
        )

        is_target_profile = bool(
            item.get("is_target_linkedin")
        )

        if is_target_profile:
            target_profile_results.append(item)

        if (
            name_present
            and company_score >= 90
        ):
            strong_company_results.append(item)

        if (
            name_present
            and role_score >= 80
        ):
            strong_role_results.append(item)

        if (
            name_present
            and company_score >= 90
            and role_score >= 80
            and current_score >= 85
        ):
            strong_current_results.append(item)

        if current_score == 0:
            negative_results.append(item)

    # --------------------------------------------------------
    # Independent corroboration
    # --------------------------------------------------------

    # Count distinct URLs, not queries.
    corroborating_urls = unique([
        clean(item.get("url"))
        for item in strong_current_results
        if clean(item.get("url"))
    ])

    independent_evidence_count = len(
        corroborating_urls
    )

    # --------------------------------------------------------
    # Strong company / role evidence
    # --------------------------------------------------------

    company_evidence = min(
        100,
        50 + len(strong_company_results) * 25
    ) if strong_company_results else 0

    role_evidence = min(
        100,
        50 + len(strong_role_results) * 25
    ) if strong_role_results else 0

    current_evidence = min(
        100,
        50 + len(strong_current_results) * 25
    ) if strong_current_results else 0

    # --------------------------------------------------------
    # Target LinkedIn profile corroboration
    # --------------------------------------------------------

    target_profile_evidence = 100 if (
        len(target_profile_results) > 0
    ) else 0

    # --------------------------------------------------------
    # Negative evidence
    # --------------------------------------------------------

    negative_evidence = len(
        negative_results
    )

    # --------------------------------------------------------
    # Final score
    #
    # The score is deliberately secondary to hard gates.
    # A candidate cannot become VERIFIED just because the
    # weighted score is high.
    # --------------------------------------------------------

    final_score = round(
        (
            candidate_company * 0.20
            + candidate_title * 0.20
            + company_evidence * 0.20
            + role_evidence * 0.15
            + current_evidence * 0.15
            + target_profile_evidence * 0.05
            + min(100, independent_evidence_count * 25) * 0.05
        ),
        1,
    )

    # --------------------------------------------------------
    # HARD GATES
    # --------------------------------------------------------

    reasons = []

    # 1. LinkedIn discovery result must have strong company evidence.
    if candidate_company < 90:
        reasons.append(
            "The candidate's LinkedIn search result does not strongly identify the target company."
        )

    # 2. LinkedIn discovery result must have strong title evidence.
    if candidate_title < 80:
        reasons.append(
            "The candidate's displayed title does not strongly match the requested persona."
        )

    # 3. Strong negative evidence always blocks verification.
    if negative_evidence > 0:
        reasons.append(
            "Returned evidence contains former/previous/ex-employee indicators."
        )

    # 4. Need actual returned evidence, not merely the search query.
    if len(strong_company_results) == 0:
        reasons.append(
            "No returned search result independently confirms the target company."
        )

    if len(strong_role_results) == 0:
        reasons.append(
            "No returned search result independently confirms the requested role."
        )

    # 5. Current role/company combination is the critical gate.
    if len(strong_current_results) == 0:
        reasons.append(
            "No returned result independently confirms current employment plus current role."
        )

    # 6. Require at least two distinct corroborating URLs for automatic
    # verification. One result can be stale or incorrectly indexed.
    if independent_evidence_count < 2:
        reasons.append(
            "Fewer than two independent returned sources corroborate the current company and role."
        )

    # --------------------------------------------------------
    # Decision
    # --------------------------------------------------------

    if (
        candidate_company >= 90
        and candidate_title >= 80
        and negative_evidence == 0
        and len(strong_company_results) >= 1
        and len(strong_role_results) >= 1
        and len(strong_current_results) >= 1
        and independent_evidence_count >= 2
        and final_score >= 80
    ):
        status = "VERIFIED"
        reason = (
            "Strong evidence confirms the same person, target company, "
            "requested role and current employment across independent "
            "returned search results."
        )

    elif (
        candidate_company >= 90
        and candidate_title >= 70
        and negative_evidence == 0
        and (
            len(strong_company_results) >= 1
            or len(strong_role_results) >= 1
        )
    ):
        status = "REVIEW"
        reason = (
            "The candidate appears relevant, but the evidence is not "
            "strong enough for automatic verification."
        )

    else:
        status = "REJECTED"
        reason = (
            "The candidate failed one or more hard verification gates."
        )

    return {
        "candidate_company_score": candidate_company,
        "candidate_title_score": candidate_title,
        "candidate_currentness_score": candidate_currentness,
        "company_evidence_score": company_evidence,
        "role_evidence_score": role_evidence,
        "current_evidence_score": current_evidence,
        "target_profile_evidence": target_profile_evidence,
        "independent_evidence_count": independent_evidence_count,
        "negative_evidence_count": negative_evidence,
        "final_score": final_score,
        "status": status,
        "reason": reason,
        "strong_company_results": strong_company_results,
        "strong_role_results": strong_role_results,
        "strong_current_results": strong_current_results,
        "negative_results": negative_results,
        "reason_details": reasons,
    }


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
    search_title = clean(
        profile.get("Title from Search")
    )
    snippet = clean(
        profile.get("Snippet")
    )

    analysis = analyze_evidence(
        name=name,
        company=company,
        location=location,
        requested_persona=requested_persona,
        linkedin_url=linkedin,
        profile=profile,
        cross_validation=cross_validation,
    )

    return {
        "Name": name,
        "LinkedIn": linkedin,
        "Requested Persona": requested_persona,
        "Search Title": search_title,
        "Search Snippet": snippet,

        "Candidate Company Score": analysis[
            "candidate_company_score"
        ],
        "Candidate Title Score": analysis[
            "candidate_title_score"
        ],
        "Candidate Currentness Score": analysis[
            "candidate_currentness_score"
        ],

        "Company Evidence Score": analysis[
            "company_evidence_score"
        ],
        "Role Evidence Score": analysis[
            "role_evidence_score"
        ],
        "Current Employment Evidence": analysis[
            "current_evidence_score"
        ],

        "Independent Evidence Count": analysis[
            "independent_evidence_count"
        ],
        "Negative Evidence Count": analysis[
            "negative_evidence_count"
        ],

        "Verification Score": analysis[
            "final_score"
        ],
        "Verification Status": analysis["status"],
        "Verification Reason": analysis["reason"],

        "Verification Gate Failures": "; ".join(
            analysis["reason_details"]
        ),

        "Discovery Queries": safe_json(
            profile.get("Discovery Queries", [])
        ),

        "Discovery Evidence": safe_json(
            profile.get("Discovery Evidence", [])
        ),

        "Cross Validation": safe_json(
            cross_validation
        ),

        "Strong Current Evidence": safe_json(
            analysis["strong_current_results"]
        ),

        "Negative Evidence": safe_json(
            analysis["negative_results"]
        ),

        "Verification Timestamp": time.strftime(
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

            # We want candidates, but we do not trust discovery.
            # Every candidate goes through a separate validation pass.
            for profile in profiles:

                name = clean(
                    profile.get("Name")
                )

                if not name:
                    continue

                validation = cross_validate_person(
                    name,
                    company,
                    location,
                    persona,
                    profile.get("LinkedIn", ""),
                    serper_key,
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

    # ------------------------------------------------------------
    # FINAL PERSON DEDUPLICATION
    # ------------------------------------------------------------
    # Discovery runs once per persona, so the same executive can be
    # returned many times. Deduplicate by LinkedIn first, then by
    # canonical name + company. Keep the strongest verified record.
    df["_linkedin_key"] = df["LinkedIn"].fillna("").map(normalize_linkedin_url)
    df["_person_key"] = df["Name"].fillna("").map(person_name_key)

    # Prefer verified > review > rejected, then highest evidence score.
    status_rank = {"VERIFIED": 3, "REVIEW": 2, "REJECTED": 1}
    df["_status_rank"] = df["Verification Status"].map(status_rank).fillna(0)

    df = df.sort_values(
        ["_status_rank", "Verification Score", "Independent Evidence Count"],
        ascending=[False, False, False],
    )

    # First collapse the exact same LinkedIn profile, regardless of
    # which requested persona query found it.
    with_linkedin = df[df["_linkedin_key"] != ""].copy()
    without_linkedin = df[df["_linkedin_key"] == ""].copy()

    if not with_linkedin.empty:
        with_linkedin = with_linkedin.drop_duplicates(
            subset=["_linkedin_key"],
            keep="first",
        )

    # Then collapse same-name records at the same account. This catches
    # variants such as "Rahul Sharma" / "Rahul K Sharma".
    if not with_linkedin.empty:
        with_linkedin = with_linkedin.drop_duplicates(
            subset=["_person_key"],
            keep="first",
        )

    if not without_linkedin.empty:
        without_linkedin = without_linkedin.drop_duplicates(
            subset=["_person_key"],
            keep="first",
        )

    df = pd.concat(
        [with_linkedin, without_linkedin],
        ignore_index=True,
    )

    df = df.drop(
        columns=["_linkedin_key", "_person_key", "_status_rank"],
        errors="ignore",
    )

    return df.reset_index(drop=True)


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

    st.markdown("### Persona Selection")

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
        "This version uses Serper for discovery and "
        "independent web corroboration. No Zintlr, Lusha, "
        "ContactOut or Apollo API is required."
    )


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">🎯 360° Account Intelligence</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="subtitle">'
    'Company → Technology → Persona Discovery → '
    'Hard-Gate Verification → Lead Qualification'
    '</div>',
    unsafe_allow_html=True,
)


# ============================================================
# INPUT
# ============================================================

st.subheader("1. Account Input")

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
        st.error("Company name is required.")
        st.stop()

    if not location.strip():
        st.error("Location is required.")
        st.stop()

    if not serper_key:
        st.error("Serper API key is required.")
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
        "Discovering and strictly verifying personas..."
    ):

        persona_df = run_persona_pipeline(
            company_name,
            location,
            personas,
            serper_key,
            max_results,
        )

    if not persona_df.empty:

        persona_df["Technology Stack"] = ", ".join(
            technology.get(
                "technologies",
                [],
            )
        )

        persona_df["Solution Fit"] = "; ".join(
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

# Safety net: never display the same canonical person name twice.
if not persona_df.empty and "Name" in persona_df.columns:
    _display = persona_df.copy()
    _display["_name_key"] = _display["Name"].map(person_name_key)
    _display["_rank"] = _display["Verification Status"].map(
        {"VERIFIED": 3, "REVIEW": 2, "REJECTED": 1}
    ).fillna(0)
    _display = _display.sort_values(
        ["_rank", "Verification Score"],
        ascending=[False, False],
    )
    persona_df = _display.drop_duplicates(
        subset=["_name_key"],
        keep="first",
    ).drop(columns=["_name_key", "_rank"], errors="ignore").reset_index(drop=True)


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
                <h3>{company_data.get("company_name", "")}</h3>
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

            st.subheader("Zauba")

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
                        zauba["records"]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        with c2:

            st.subheader("Tofler")

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
                        tofler["records"]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        st.info(
            "Zauba and Tofler are used as company-level "
            "evidence discovered through search. They are "
            "not represented as direct APIs."
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
                min(4, len(technologies))
            )

            for i, technology in enumerate(
                technologies
            ):
                cols[
                    i % len(cols)
                ].success(technology)

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
                "Independent Evidence Count",
                "Negative Evidence Count",
            ]

            display_columns = [
                x
                for x in display_columns
                if x in persona_df.columns
            ]

            st.dataframe(
                persona_df[display_columns],
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
            "Strict Persona Verification"
        )

        st.info(
            "IMPORTANT: VERIFIED is intentionally difficult to achieve. "
            "The system does not treat a search query itself as evidence. "
            "It requires actual returned results supporting the person, "
            "company, role and current employment."
        )

        if persona_df.empty:

            st.info(
                "No verification results."
            )

        else:

            counts = (
                persona_df[
                    "Verification Status"
                ].value_counts()
            )

            c1, c2, c3 = st.columns(3)

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
                "Review",
                int(
                    counts.get(
                        "REVIEW",
                        0,
                    )
                ),
            )

            c3.metric(
                "Rejected",
                int(
                    counts.get(
                        "REJECTED",
                        0,
                    )
                ),
            )

            st.markdown(
                "### Verification Rules"
            )

            st.write(
                """
                A candidate is automatically VERIFIED only when:

                1. The LinkedIn result strongly identifies the target company.
                2. The displayed title strongly matches the requested persona.
                3. No strong former/previous/ex-employee evidence is found.
                4. Actual returned search results confirm the target company.
                5. Actual returned search results confirm the requested role.
                6. Actual returned search results support current employment.
                7. At least two distinct returned URLs corroborate the current company + role.
                8. The final score also clears the verification threshold.

                Search queries themselves never count as evidence.
                """
            )

            verification_columns = [
                "Name",
                "Requested Persona",
                "Search Title",
                "Candidate Company Score",
                "Candidate Title Score",
                "Company Evidence Score",
                "Role Evidence Score",
                "Current Employment Evidence",
                "Independent Evidence Count",
                "Negative Evidence Count",
                "Verification Score",
                "Verification Status",
                "Verification Reason",
                "Verification Gate Failures",
            ]

            verification_columns = [
                x
                for x in verification_columns
                if x in persona_df.columns
            ]

            st.dataframe(
                persona_df[
                    verification_columns
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
                ] == "VERIFIED"
            ].copy()

            if verified.empty:

                st.warning(
                    "No automatically verified personas are available. "
                    "This is expected when the web evidence is insufficient."
                )

            else:

                st.success(
                    f"{len(verified)} persona(s) passed strict verification."
                )

                for _, row in verified.iterrows():

                    st.markdown(
                        f"""
                        <div class="card verified">
                            <h3>{row.get("Name", "")}</h3>
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
                            <b>Independent Evidence:</b>
                            {row.get("Independent Evidence Count", 0)}
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
                <b>How this version differs:</b><br><br>
                Search queries are discovery instructions, not proof.
                Verification is based on the actual results returned by
                the search engine. This prevents the previous bug where
                putting the company and persona into a query accidentally
                created "evidence" for that same company/persona.
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
                        "Gate Failures:",
                        row.get(
                            "Verification Gate Failures",
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
                        "Independent Evidence Count:",
                        row.get(
                            "Independent Evidence Count",
                            0,
                        ),
                    )

                    st.write(
                        "Negative Evidence Count:",
                        row.get(
                            "Negative Evidence Count",
                            0,
                        ),
                    )

                    st.write(
                        "Strong Current Evidence"
                    )

                    raw_current = row.get(
                        "Strong Current Evidence",
                        "",
                    )

                    if raw_current:
                        try:
                            st.json(
                                json.loads(raw_current)
                            )
                        except Exception:
                            st.code(raw_current)

                    st.write(
                        "Negative Evidence"
                    )

                    raw_negative = row.get(
                        "Negative Evidence",
                        "",
                    )

                    if raw_negative:
                        try:
                            st.json(
                                json.loads(raw_negative)
                            )
                        except Exception:
                            st.code(raw_negative)

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
                                json.loads(raw_validation)
                            )
                        except Exception:
                            st.code(raw_validation)


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "360° Account Intelligence | "
    "Company validation + strict multi-query persona verification "
    "+ technographic intelligence | "
    "No Zintlr/Lusha/ContactOut/Apollo API required"
)
