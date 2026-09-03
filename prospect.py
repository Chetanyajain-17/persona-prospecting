"""
Standalone Persona Prospecting & SignalHire Enrichment CLI
No Streamlit required. Runs directly with standard Python.
Usage:
    python prospect.py --company "Infosys" --location "Bengaluru, India" --persona "CTO"
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

# ============================================================
# API ENDPOINTS & KEYS
# ============================================================

SERPER_URL = "https://google.serper.dev/search"
SIGNALHIRE_BASE_URL = "https://www.signalhire.com/api/v1"
SIGNALHIRE_SEARCH_URL = f"{SIGNALHIRE_BASE_URL}/candidate/search"
SIGNALHIRE_CREDITS_URL = f"{SIGNALHIRE_BASE_URL}/credits"

DEFAULT_SIGNALHIRE_KEY = "202.aBvCsev0gnhPuyBqigoXHS1BfiuZ"

DEFAULT_PERSONAS = [
    "CTO",
    "Chief Technology Officer",
    "VP Technology",
    "Head of Technology",
    "CIO",
    "Chief Information Officer",
    "VP IT",
    "Head of IT",
    "CISO",
    "Chief Information Security Officer",
    "Head of Cyber Security",
    "Head of Infrastructure",
]


# ============================================================
# HELPERS
# ============================================================

def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_company_name(name: str) -> str:
    value = clean(name).lower()
    remove_terms = [
        "private limited", "pvt limited", "pvt ltd", "pvt. ltd.",
        "limited", "ltd", "llp", "incorporated", "inc.", "inc",
        "corporation", "corp", "company", "co.",
    ]
    for term in remove_terms:
        value = value.replace(term, " ")
    value = re.sub(r"[^a-z0-9 ]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def unique(values: List[str]) -> List[str]:
    result = []
    for value in values:
        val = clean(value)
        if val and val not in result:
            result.append(val)
    return result


def title_score(requested: str, title: str) -> int:
    requested = clean(requested).lower()
    title = clean(title).lower()
    if not title:
        return 0

    aliases = {
        "cto": ["cto", "chief technology officer"],
        "cio": ["cio", "chief information officer"],
        "ciso": ["ciso", "chief information security officer", "chief security officer"],
        "vp it": ["vp it", "vice president it"],
        "head of it": ["head of it", "it head"],
        "head of technology": ["head of technology", "technology head"],
    }
    if requested in aliases:
        for alias in aliases[requested]:
            if alias in title:
                return 100

    if requested in title:
        return 100

    words = [w for w in re.findall(r"[a-z]+", requested) if len(w) > 2]
    if not words:
        return 0
    matches = sum(w in title for w in words)
    ratio = matches / len(words)
    if ratio >= 0.8:
        return 85
    if ratio >= 0.5:
        return 70
    return 40 if ratio > 0 else 0


# ============================================================
# SIGNALHIRE API
# ============================================================

def get_signalhire_credits(api_key: str) -> Optional[int]:
    try:
        res = requests.get(SIGNALHIRE_CREDITS_URL, headers={"apikey": api_key}, timeout=15)
        if res.ok:
            return res.json().get("credits")
    except Exception:
        pass
    return None


def enrich_profiles_signalhire(
    linkedin_urls: List[str],
    api_key: str,
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    clean_urls = unique([clean(u) for u in linkedin_urls if clean(u)])
    if not clean_urls:
        return []

    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"items": clean_urls[:100], "withoutWaterfall": True}

    res = requests.post(SIGNALHIRE_SEARCH_URL, headers=headers, json=payload, timeout=timeout)
    if not res.ok:
        raise RuntimeError(f"SignalHire API HTTP {res.status_code}: {res.text}")
    return res.json()


def parse_signalhire_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    status = clean(item.get("status"))
    url = clean(item.get("item"))
    if status != "success":
        return {"url": url, "status": status}

    c = item.get("candidate") or {}
    contacts = c.get("contacts") or []
    work_emails, personal_emails, other_emails = [], [], []
    work_phones, mobile_phones, other_phones = [], [], []

    for ct in contacts:
        if not isinstance(ct, dict):
            continue
        c_type = clean(ct.get("type")).lower()
        val = clean(ct.get("value"))
        sub_type = clean(ct.get("subType")).lower()
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

    experiences = c.get("experience") or []
    current_roles, past_roles = [], []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        is_cur = bool(exp.get("current", False))
        entry = {
            "position": clean(exp.get("position")),
            "company": clean(exp.get("company")),
            "current": is_cur,
            "started": clean(exp.get("started")),
            "summary": clean(exp.get("summary")),
        }
        if is_cur:
            current_roles.append(entry)
        else:
            past_roles.append(entry)

    cur_pos = current_roles[0]["position"] if current_roles else ""
    cur_comp = current_roles[0]["company"] if current_roles else ""

    skills = [clean(s) for s in (c.get("skills") or []) if clean(s)]

    return {
        "url": url,
        "status": "success",
        "full_name": clean(c.get("fullName")),
        "headline": clean(c.get("headLine")),
        "summary": clean(c.get("summary")),
        "skills": skills,
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
    }


# ============================================================
# SERPER SEARCH
# ============================================================

def serper_search(query: str, api_key: str, num: int = 10) -> List[Dict[str, Any]]:
    res = requests.post(
        SERPER_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": num},
        timeout=30,
    )
    if not res.ok:
        raise RuntimeError(f"Serper API HTTP {res.status_code}: {res.text}")
    return res.json().get("organic", [])


def discover_linkedin_candidates(
    company: str,
    location: str,
    personas: List[str],
    serper_key: str,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    candidates = []
    seen_urls = set()

    for persona in personas:
        queries = [
            f'site:linkedin.com/in/ "{company}" "{persona}" "{location}"',
            f'site:linkedin.com/in/ "{company}" "{persona}"',
            f'site:linkedin.com/in/ "{company}" "{persona}" "present"',
        ]
        for q in queries:
            try:
                results = serper_search(q, serper_key, num=max_results)
                for item in results:
                    url = clean(item.get("link")).split("?")[0].rstrip("/")
                    if "linkedin.com/in/" not in url.lower() or url.lower() in seen_urls:
                        continue
                    seen_urls.add(url.lower())
                    name = clean(item.get("title", "")).split(" - ")[0].strip()
                    candidates.append({
                        "Name": name,
                        "Requested Persona": persona,
                        "Search Title": clean(item.get("title")),
                        "LinkedIn": url,
                        "Snippet": clean(item.get("snippet")),
                    })
            except Exception as e:
                print(f"[!] Warning during query '{q}': {e}")
    return candidates


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Persona Prospecting & SignalHire Enrichment CLI (No Streamlit required)"
    )
    parser.add_argument("--company", required=True, help="Target company name (e.g. 'Infosys')")
    parser.add_argument("--location", default="", help="Target location (e.g. 'Bengaluru, India')")
    parser.add_argument(
        "--persona",
        nargs="+",
        default=DEFAULT_PERSONAS[:4],
        help="One or more target personas (e.g. --persona CTO CIO)",
    )
    parser.add_argument("--serper-key", default=os.getenv("SERPER_API_KEY", ""), help="Serper API key")
    parser.add_argument(
        "--signalhire-key",
        default=os.getenv("SIGNALHIRE_API_KEY", DEFAULT_SIGNALHIRE_KEY),
        help="SignalHire API key",
    )
    parser.add_argument("--max-results", type=int, default=5, help="Search results per query")
    parser.add_argument("--enrich-limit", type=int, default=3, help="Max candidates to enrich via SignalHire")
    parser.add_argument("--output", default="", help="Path to save CSV output (optional)")

    args = parser.parse_args()

    print("=" * 65)
    print("🎯 PERSONA PROSPECTING & SIGNALHIRE ENRICHMENT (CLI)")
    print("=" * 65)
    print(f"Company:        {args.company}")
    print(f"Location:       {args.location or 'Global'}")
    print(f"Personas:       {', '.join(args.persona)}")

    # 1. Check SignalHire Credits
    sh_credits = get_signalhire_credits(args.signalhire_key)
    if sh_credits is not None:
        print(f"SignalHire:     Active ({sh_credits} credits available)")
    else:
        print("SignalHire:     [!] Could not verify credits. Check API key.")

    # 2. Check Serper Key
    if not args.serper_key:
        print("\n[!] Error: Serper API key is required for LinkedIn profile discovery.")
        print("    Pass it via --serper-key YOUR_KEY or set environment variable SERPER_API_KEY.")
        sys.exit(1)

    # 3. Discover Candidates
    print(f"\n[*] Searching LinkedIn profiles for {args.company} via Serper...")
    candidates = discover_linkedin_candidates(
        args.company,
        args.location,
        args.persona,
        args.serper_key,
        max_results=args.max_results,
    )
    print(f"[+] Found {len(candidates)} candidate profile(s).")

    if not candidates:
        print("[-] No matching candidates found.")
        sys.exit(0)

    # Convert to DataFrame
    df = pd.DataFrame(candidates)

    # 4. Enrich with SignalHire (Synchronous)
    if args.signalhire_key and args.enrich_limit > 0:
        targets_to_enrich = df.head(args.enrich_limit)
        urls = [u for u in targets_to_enrich["LinkedIn"].tolist() if u]
        print(f"\n[*] Enriching top {len(urls)} profile(s) via SignalHire (synchronous)...")
        try:
            enriched_items = enrich_profiles_signalhire(urls, args.signalhire_key)
            
            # Map enriched data
            parsed_map = {}
            for item in enriched_items:
                parsed = parse_signalhire_candidate(item)
                url = clean(parsed.get("url")).lower()
                if url:
                    parsed_map[url] = parsed

            # Add columns
            df["Work Emails"] = ""
            df["Personal Emails"] = ""
            df["Phones"] = ""
            df["Verified Title"] = ""
            df["Verified Company"] = ""
            df["Verification Status"] = "CANDIDATE"
            df["Verification Reason"] = ""

            norm_target = normalize_company_name(args.company)

            for idx, row in df.iterrows():
                u = clean(row.get("LinkedIn")).lower()
                if u in parsed_map:
                    p = parsed_map[u]
                    if p.get("status") == "success":
                        df.at[idx, "Work Emails"] = ", ".join(p.get("work_emails", []))
                        df.at[idx, "Personal Emails"] = ", ".join(p.get("personal_emails", []))
                        df.at[idx, "Phones"] = ", ".join(p.get("all_phones", []))
                        df.at[idx, "Verified Title"] = p.get("current_position", "")
                        df.at[idx, "Verified Company"] = p.get("current_company", "")

                        # Ground truth verification
                        cur_comp = p.get("current_company", "")
                        cur_pos = p.get("current_position", "")
                        target_in_cur = any(
                            norm_target in normalize_company_name(r.get("company", ""))
                            for r in p.get("current_roles", [])
                        )
                        target_in_past = any(
                            norm_target in normalize_company_name(r.get("company", ""))
                            for r in p.get("past_roles", [])
                        )

                        if target_in_cur:
                            df.at[idx, "Verification Status"] = "VERIFIED"
                            df.at[idx, "Verification Reason"] = f"Employed as '{cur_pos}' at '{cur_comp}'"
                        elif target_in_past:
                            df.at[idx, "Verification Status"] = "REJECTED"
                            df.at[idx, "Verification Reason"] = f"Former employee (now at '{cur_comp or 'Other'}')"
                        elif cur_comp:
                            df.at[idx, "Verification Status"] = "REVIEW"
                            df.at[idx, "Verification Reason"] = f"Currently at '{cur_comp}'"

            print(f"[+] Enrichment complete. Updated credits: {get_signalhire_credits(args.signalhire_key)}")
        except Exception as e:
            print(f"[!] SignalHire enrichment error: {e}")

    # 5. Display Results
    print("\n" + "=" * 65)
    print("📋 RESULTS SUMMARY")
    print("=" * 65)
    for idx, row in df.iterrows():
        print(f"\n[{idx + 1}] {row.get('Name')} | {row.get('Requested Persona')}")
        print(f"    LinkedIn:   {row.get('LinkedIn')}")
        if "Verified Title" in row and row.get("Verified Title"):
            print(f"    Live Role:  {row.get('Verified Title')} @ {row.get('Verified Company')}")
        else:
            print(f"    Search:     {row.get('Search Title')}")
        if "Work Emails" in row and row.get("Work Emails"):
            print(f"    Work Email: {row.get('Work Emails')}")
        if "Personal Emails" in row and row.get("Personal Emails"):
            print(f"    Personal:   {row.get('Personal Emails')}")
        if "Phones" in row and row.get("Phones"):
            print(f"    Phones:     {row.get('Phones')}")
        if "Verification Status" in row and row.get("Verification Status"):
            print(f"    Status:     {row.get('Verification Status')} ({row.get('Verification Reason')})")

    # 6. Export to CSV
    out_file = args.output or f"{normalize_company_name(args.company).replace(' ', '_')}_personas.csv"
    df.to_csv(out_file, index=False)
    print(f"\n[✓] Saved complete results to: {out_file}")


if __name__ == "__main__":
    main()
