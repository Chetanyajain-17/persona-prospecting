import re
import json
import time
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="360° Account Intelligence", page_icon="🎯", layout="wide")

SERPER_URL = "https://google.serper.dev/search"
BUILTWITH_URL = "https://api.builtwith.com/v23/api.json"

PERSONA_GROUPS = {
    "Technology Leadership": ["CTO", "Chief Technology Officer", "VP Technology", "Vice President Technology", "Head of Technology", "Technology Director", "Director of Technology"],
    "IT Leadership": ["CIO", "Chief Information Officer", "VP IT", "Vice President IT", "VP Information Technology", "Head of IT", "IT Director", "Director IT", "IT Manager"],
    "Security Leadership": ["CISO", "Chief Information Security Officer", "Chief Security Officer", "Head of Cyber Security", "Head of Cybersecurity", "Head of Information Security", "Cybersecurity Head", "Information Security Manager", "Director Information Security", "Security Director"],
    "Infrastructure": ["Head of Infrastructure", "Infrastructure Director", "Infrastructure Manager", "IT Infrastructure Manager", "Systems Director", "System Administrator"],
}
DEFAULT_PERSONAS = [x for g in PERSONA_GROUPS.values() for x in g]

st.markdown("""
<style>
.main-title{font-size:36px;font-weight:800;color:#111827}.subtitle{color:#6b7280;font-size:16px;margin-bottom:25px}
.card{padding:18px;border-radius:14px;border:1px solid #e5e7eb;background:white;margin-bottom:15px}
.small{color:#6b7280;font-size:13px}
</style>
""", unsafe_allow_html=True)


def clean(v: Any) -> str:
    return "" if v is None else str(v).strip()


def norm(v: str) -> str:
    v = clean(v).lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", v)).strip()


def tokens(v: str) -> set:
    return {x for x in re.findall(r"[a-z0-9]+", norm(v)) if len(x) > 2}


def unique(values: List[str]) -> List[str]:
    out, seen = [], set()
    for v in values:
        v = clean(v)
        k = norm(v)
        if v and k not in seen:
            out.append(v); seen.add(k)
    return out


def api_request(method: str, url: str, **kwargs) -> Dict[str, Any]:
    r = requests.request(method, url, timeout=45, **kwargs)
    if not r.ok:
        try: body = r.json()
        except Exception: body = r.text
        raise RuntimeError(f"HTTP {r.status_code}: {body}")
    try: return r.json()
    except Exception: return {"raw_response": r.text}


def serper(q: str, key: str, num: int = 10) -> Dict[str, Any]:
    if not key: raise RuntimeError("Serper API key is missing")
    return api_request("POST", SERPER_URL, headers={"X-API-KEY": key, "Content-Type": "application/json"}, json={"q": q, "num": num})


def domain_of(url: str) -> str:
    try: d = urlparse(url if url.startswith("http") else "https://"+url).netloc.lower()
    except Exception: d = ""
    return d[4:] if d.startswith("www.") else d


def company_aliases(company: str) -> List[str]:
    n = norm(company)
    no_suffix = re.sub(r"\b(private limited|pvt limited|pvt ltd|pvt|limited|ltd|llp|incorporated|inc|corporation|corp|company|co)\b", " ", n)
    return unique([n, re.sub(r"\s+", " ", no_suffix).strip()])


def company_in_text(company: str, text: str) -> bool:
    t = norm(text)
    aliases = [a for a in company_aliases(company) if len(a) >= 4]
    return any(a in t for a in aliases)


def blocked_domain(d: str) -> bool:
    return any(x == d or d.endswith("."+x) for x in {
        "linkedin.com","facebook.com","instagram.com","youtube.com","wikipedia.org","zaubacorp.com","tofler.in","builtwith.com","crunchbase.com","glassdoor.com","glassdoor.co.in","ambitionbox.com","indeed.com"
    })


def find_company_domain(company: str, location: str, key: str) -> Dict[str, Any]:
    queries = [f'"{company}" "{location}" official website', f'"{company}" official website', f'"{company}" homepage']
    candidates = []
    evidence = []
    for q in queries:
        try: data = serper(q, key, 10)
        except Exception as e: evidence.append({"query":q,"error":str(e)}); continue
        org = data.get("organic", [])
        evidence.append({"query":q,"results":org})
        for r in org:
            url, title, snip = clean(r.get("link")), clean(r.get("title")), clean(r.get("snippet"))
            d = domain_of(url)
            if not d or blocked_domain(d): continue
            text = f"{title} {snip} {url}"
            score = 0
            if company_in_text(company, text): score += 60
            if "official" in norm(text): score += 20
            if norm(location) and norm(location) in norm(text): score += 10
            if d.split(".")[0] in tokens(company): score += 10
            if any(x in d for x in ["careers","jobs","blog","news"]): score -= 20
            candidates.append((score,d,url,title,snip))
    candidates.sort(key=lambda x:(x[0],len(x[1])), reverse=True)
    if not candidates: return {"domain":"","confidence":"Not resolved","evidence":evidence}
    best=candidates[0]
    return {"domain":best[1],"confidence":"High" if best[0]>=80 else "Medium","evidence":evidence,"selected":best}


def search_public_sources(company: str, location: str, key: str) -> List[Dict[str,str]]:
    queries = [
        f'"{company}" company about founded headquarters',
        f'"{company}" founded headquarters industry',
        f'"{company}" products services',
        f'"{company}" "about us"',
    ]
    rows=[]
    for q in queries:
        try: data=serper(q,key,8)
        except Exception: continue
        for r in data.get("organic",[]):
            rows.append({"query":q,"title":clean(r.get("title")),"snippet":clean(r.get("snippet")),"url":clean(r.get("link"))})
    # Prefer company-matching results and de-duplicate URLs.
    out=[]; seen=set()
    for r in rows:
        u=r["url"].split("?")[0].rstrip("/")
        if u in seen: continue
        if company_in_text(company, r["title"]+" "+r["snippet"]+" "+r["url"]):
            out.append(r); seen.add(u)
    return out[:15]


def first_match(patterns: List[str], text: str) -> str:
    for p in patterns:
        m=re.search(p,text,re.I)
        if m: return clean(m.group(1))
    return ""


def build_company_profile(company: str, location: str, domain: str, sources: List[Dict[str,str]]) -> Dict[str,Any]:
    text=" ".join((x["title"]+" "+x["snippet"]) for x in sources)
    founded=first_match([r"(?:founded|established|started|incorporated)\s+(?:in\s+)?(19\d{2}|20\d{2})",r"since\s+(19\d{2}|20\d{2})"],text)
    hq=first_match([r"(?:headquartered|headquarters|based)\s+(?:in|at)\s+([^.;,]{3,60})",r"head office\s+(?:in|at)\s+([^.;,]{3,60})"],text)
    industry=first_match([r"(?:industry|sector)\s*[:\-]?\s*([^.;]{4,80})"],text)
    # Use strongest snippets to form a factual, source-grounded overview without inventing facts.
    useful=[]
    for s in sources:
        sn=s["snippet"]
        if sn and sn not in useful: useful.append(sn)
    desc=" ".join(useful[:3])
    desc=re.sub(r"\s+"," ",desc).strip()
    paragraph=f"{company}"
    if founded: paragraph += f" was founded in {founded}"
    if hq: paragraph += f" and is associated with {hq}"
    if industry: paragraph += f" in the {industry} sector"
    paragraph += ". " if paragraph != company else ". "
    paragraph += desc
    if not desc: paragraph += "Public web sources did not provide enough reliable detail to write a fuller company description."
    return {"about":paragraph,"founded":founded,"headquarters":hq,"industry":industry,"domain":domain,"sources":sources}


def builtwith_lookup(domain: str, key: str) -> Dict[str,Any]:
    return api_request("GET",BUILTWITH_URL,params={"KEY":key,"LOOKUP":domain},timeout=60)


def extract_technologies(text: str) -> List[str]:
    tech_patterns=[
        "AWS","Amazon Web Services","Microsoft Azure","Google Cloud","GCP","Kubernetes","Docker","Cloudflare","Okta","CrowdStrike","Palo Alto Networks","Fortinet","Microsoft 365","Office 365","Salesforce","ServiceNow","SAP","Oracle","Snowflake","Databricks","Tableau","Power BI","MongoDB","PostgreSQL","MySQL","Redis","GitHub","GitLab","Jenkins","Terraform","Cisco","VMware","Zscaler","SentinelOne","Splunk","Elastic","Nginx","Apache","WordPress","HubSpot"
    ]
    low=norm(text); found=[]
    for t in tech_patterns:
        if norm(t) in low: found.append(t)
    return unique(found)


def technology_intelligence(company: str, domain: str, key: str, builtwith_key: str) -> Dict[str,Any]:
    if domain and builtwith_key:
        try:
            raw=builtwith_lookup(domain,builtwith_key)
            blob=json.dumps(raw,ensure_ascii=False)
            tech=extract_technologies(blob)
            if tech: return {"status":"BuiltWith + public web","technologies":tech,"raw":raw}
        except Exception as e:
            built_error=str(e)
        
    queries=[f'"{company}" technology stack',f'"{company}" AWS Azure Kubernetes security',f'"{company}" software technologies',f'"{company}" "technology" "cloud"']
    rows=[]; blob=""
    for q in queries:
        try: data=serper(q,key,8)
        except Exception: continue
        for r in data.get("organic",[]):
            row={"query":q,"title":clean(r.get("title")),"snippet":clean(r.get("snippet")),"url":clean(r.get("link"))}
            rows.append(row); blob += " "+row["title"]+" "+row["snippet"]
    tech=extract_technologies(blob)
    cats=[]
    groups={"Cloud / Infrastructure":["AWS","Amazon Web Services","Microsoft Azure","Google Cloud","GCP","Kubernetes","Docker","VMware"],"Cybersecurity":["CrowdStrike","Palo Alto Networks","Fortinet","Cloudflare","Okta","Zscaler","SentinelOne","Splunk"],"Enterprise Applications":["SAP","Oracle","Salesforce","ServiceNow","Microsoft 365","Office 365","HubSpot"],"Data / Analytics":["Snowflake","Databricks","Tableau","Power BI","MongoDB","PostgreSQL","MySQL","Redis"],"DevOps / Engineering":["GitHub","GitLab","Jenkins","Terraform","Docker","Kubernetes"]}
    for c, vals in groups.items():
        if any(v in tech for v in vals): cats.append(c)
    return {"status":"Public web technology signals" if tech else "No technology signals found","technologies":tech,"categories":unique(cats),"sources":rows[:15],"raw":{}}


def persona_terms(persona: str) -> List[str]:
    n=norm(persona)
    aliases={
        "cto":["cto","chief technology officer"],"chief technology officer":["cto","chief technology officer"],
        "cio":["cio","chief information officer"],"chief information officer":["cio","chief information officer"],
        "ciso":["ciso","chief information security officer"],"chief information security officer":["ciso","chief information security officer"],
        "chief security officer":["cso","chief security officer"],
        "vp it":["vp it","vice president it","vp information technology","vice president information technology"],
        "head of it":["head of it","head of information technology","it head"],
        "it director":["it director","director it","director of it","director information technology"],
        "it manager":["it manager","information technology manager"],
        "head of technology":["head of technology","technology head"],
        "technology director":["technology director","director of technology"],
        "head of cybersecurity":["head of cybersecurity","head of cyber security","cybersecurity head"],
        "head of cyber security":["head of cybersecurity","head of cyber security"],
        "head of information security":["head of information security","information security head"],
        "information security manager":["information security manager","security manager"],
        "security director":["security director","director of security","director information security"],
        "infrastructure manager":["infrastructure manager","it infrastructure manager","infrastructure head"],
        "infrastructure director":["infrastructure director","director of infrastructure"],
        "head of infrastructure":["head of infrastructure","infrastructure head"],
        "systems director":["systems director","director of systems"],
        "system administrator":["system administrator","systems administrator","sysadmin"]}
    return aliases.get(n,[persona])


def name_from_title(title: str) -> str:
    parts=[x.strip() for x in re.split(r"\s+-\s+|\s+\|\s+",title) if x.strip()]
    return parts[0] if parts else ""


def is_probable_name(name: str) -> bool:
    n=clean(name)
    if not n or len(n)>80: return False
    low=norm(n)
    bad={"linkedin","facebook","profile","people","search","results","company","jobs","careers"}
    words=n.split()
    return 2<=len(words)<=5 and not any(x in low for x in bad)


def discover_persona_candidates(company: str, location: str, persona: str, key: str, max_results: int) -> List[Dict[str,Any]]:
    queries=[
        f'site:linkedin.com/in/ "{company}" "{persona}"',
        f'site:linkedin.com/in/ "{company}" "{persona}" "{location}"',
        f'"{company}" "{persona}" LinkedIn',
    ]
    allr=[]
    for q in queries:
        try: data=serper(q,key,max_results)
        except Exception: continue
        for r in data.get("organic",[]):
            url=clean(r.get("link")); title=clean(r.get("title")); snip=clean(r.get("snippet"))
            if "linkedin.com/in/" not in url.lower(): continue
            name=name_from_title(title)
            if not is_probable_name(name): continue
            allr.append({"Name":name,"LinkedIn":url.split("?")[0].rstrip("/"),"Search Title":title,"Snippet":snip,"Persona Searched":persona})
    merged={}
    for r in allr:
        keyu=r["LinkedIn"].lower()
        if keyu not in merged: merged[keyu]=r
        else:
            if len(r["Snippet"])>len(merged[keyu]["Snippet"]): merged[keyu].update({"Search Title":r["Search Title"],"Snippet":r["Snippet"]})
    return list(merged.values())


def candidate_validation(name: str, company: str, location: str, persona: str, linkedin: str, key: str) -> Dict[str,Any]:
    # Search the person independently. Current and former signals are collected separately.
    queries=[
        f'"{name}" "{company}" "{persona}"',
        f'"{name}" "{company}" LinkedIn',
        f'"{name}" "{company}" "{location}"',
        f'"{name}" "{company}" current',
    ]
    negative_queries=[
        f'"{name}" "{company}" former',f'"{name}" "{company}" previously',f'"{name}" "{company}" "ex-"',f'"{name}" "{company}" left'
    ]
    results=[]; negatives=[]
    for q in queries:
        try: data=serper(q,key,8)
        except Exception: continue
        for r in data.get("organic",[]): results.append({"title":clean(r.get("title")),"snippet":clean(r.get("snippet")),"url":clean(r.get("link")),"query":q})
    for q in negative_queries:
        try: data=serper(q,key,5)
        except Exception: continue
        for r in data.get("organic",[]):
            row={"title":clean(r.get("title")),"snippet":clean(r.get("snippet")),"url":clean(r.get("link")),"query":q}
            text=norm(row["title"]+" "+row["snippet"])
            if norm(name) in text and company_in_text(company,text): negatives.append(row)
    # Keep only results that actually mention the candidate name and company.
    relevant=[]
    for r in results:
        t=norm(r["title"]+" "+r["snippet"])
        if norm(name) in t and company_in_text(company,t): relevant.append(r)
    return {"results":relevant,"negative":negatives}


def title_matches_requested(title_text: str, persona: str) -> bool:
    t=norm(title_text)
    aliases=[norm(x) for x in persona_terms(persona)]
    return any(re.search(r"\b"+re.escape(a)+r"\b",t) for a in aliases if a)


def current_signal(text: str) -> bool:
    t=norm(text)
    negatives=["former ","formerly","previously","previous role","previous position","ex employee","ex-employee","left the company","left company","no longer","until 2024","until 2023","until 2022","retired"]
    return not any(x in t for x in negatives)


def make_persona_rows(company: str, location: str, personas: List[str], key: str, max_results: int) -> pd.DataFrame:
    candidates={}
    for persona in personas:
        discovered=discover_persona_candidates(company,location,persona,key,max_results)
        for c in discovered:
            person_key=c["LinkedIn"].lower() or norm(c["Name"])
            if person_key not in candidates: candidates[person_key]={**c,"Requested Personas":[]}
            candidates[person_key]["Requested Personas"].append(persona)
    rows=[]
    for c in candidates.values():
        # Validate once per person, then decide whether any requested persona is supported.
        vals=[]
        for persona in unique(c["Requested Personas"]):
            v=candidate_validation(c["Name"],company,location,persona,c["LinkedIn"],key)
            positives=[]
            for r in v["results"]:
                txt=r["title"]+" "+r["snippet"]
                if title_matches_requested(txt,persona) and current_signal(txt): positives.append(r)
            if positives and not v["negative"]:
                vals.append((persona,positives,v))
        if not vals: continue
        # Choose one row per person, preserving the best/most specific actual current title.
        vals.sort(key=lambda x:len(x[1]),reverse=True)
        persona, positives, v=vals[0]
        best=positives[0]
        actual_title=best["title"]
        if " - " in actual_title: actual_title=actual_title.split(" - ",1)[1]
        rows.append({"Name":c["Name"],"Current Designation":actual_title,"Company":company,"Location":location,"LinkedIn":c["LinkedIn"],"Persona":persona,"Source URL":best["url"]})
    if not rows: return pd.DataFrame(columns=["Name","Current Designation","Company","Location","LinkedIn","Persona","Source URL"])
    df=pd.DataFrame(rows)
    # Final person-level de-duplication: one human = one row.
    df["_person_key"]=df["LinkedIn"].str.lower().str.rstrip("/")
    df=df.sort_values(["Name","Current Designation"]).drop_duplicates("_person_key",keep="first")
    # Name-only fallback for candidates whose LinkedIn URL is missing/odd.
    df=df.drop_duplicates(subset=["Name"],keep="first").drop(columns=["_person_key"])
    return df.reset_index(drop=True)


def state_init():
    for k,v in {"company":{},"technology":{},"personas":pd.DataFrame()}.items():
        if k not in st.session_state: st.session_state[k]=v

state_init()

with st.sidebar:
    st.header("⚙️ Configuration")
    serper_key=st.text_input("Serper API Key",value=st.secrets.get("SERPER_API_KEY",""),type="password")
    builtwith_key=st.text_input("BuiltWith API Key (optional)",value=st.secrets.get("BUILTWITH_API_KEY",""),type="password")
    group=st.selectbox("Persona Group",["All",*PERSONA_GROUPS.keys()])
    personas=DEFAULT_PERSONAS if group=="All" else PERSONA_GROUPS[group]
    max_results=st.slider("Search results per persona",3,10,5)
    st.info("This version focuses only on Company, Technology and current Persona discovery. Verification, Lead Qualification and Evidence tabs have been removed.")

st.markdown('<div class="main-title">🎯 360° Account Intelligence</div>',unsafe_allow_html=True)
st.markdown('<div class="subtitle">Company → Technology → Current Persona Discovery</div>',unsafe_allow_html=True)

st.subheader("1. Account Input")
c1,c2=st.columns(2)
company_name=c1.text_input("Company Name",placeholder="Example: Infosys")
location=c2.text_input("Location",placeholder="Example: Bengaluru, India")

if st.button("🚀 Run Account Intelligence",type="primary",use_container_width=True):
    if not company_name.strip(): st.error("Company name is required."); st.stop()
    if not location.strip(): st.error("Location is required."); st.stop()
    if not serper_key: st.error("Serper API key is required."); st.stop()
    company=company_name.strip(); loc=location.strip()
    st.session_state.company={}; st.session_state.technology={}; st.session_state.personas=pd.DataFrame()
    with st.spinner("Finding and validating the official company domain..."):
        dom=find_company_domain(company,loc,serper_key)
    domain=dom.get("domain","")
    with st.spinner("Building company profile from public sources..."):
        sources=search_public_sources(company,loc,serper_key)
        profile=build_company_profile(company,loc,domain,sources)
    profile["domain_evidence"]=dom.get("evidence",[])
    st.session_state.company=profile
    with st.spinner("Collecting technology intelligence..."):
        tech=technology_intelligence(company,domain,serper_key,builtwith_key)
    st.session_state.technology=tech
    with st.spinner("Discovering current personas and removing duplicate people..."):
        pdf=make_persona_rows(company,loc,personas,serper_key,max_results)
    if not pdf.empty:
        pdf["Technology Stack"] = ", ".join(tech.get("technologies",[]))
    st.session_state.personas=pdf
    st.success("Account Intelligence completed.")

company_data=st.session_state.company
tech_data=st.session_state.technology
persona_df=st.session_state.personas

if company_data:
    st.divider(); st.subheader("2. Account Intelligence")
    tabs=st.tabs(["🏢 Company","💻 Technology","👤 Personas"])
    with tabs[0]:
        st.markdown(f'<div class="card"><h3>{company_name}</h3><p>{company_data.get("about","")}</p></div>',unsafe_allow_html=True)
        a,b,c=st.columns(3)
        a.metric("Founded",company_data.get("founded") or "Not found")
        b.metric("Headquarters",company_data.get("headquarters") or "Not found")
        c.metric("Industry",company_data.get("industry") or "Not found")
        st.markdown("### Company Details")
        st.write("**Official Domain:**",company_data.get("domain") or "Not resolved")
        if company_data.get("sources"):
            st.markdown("### Public Sources")
            st.dataframe(pd.DataFrame(company_data["sources"]),use_container_width=True,hide_index=True,column_config={"url":st.column_config.LinkColumn("Source")})
        st.markdown("### Zauba & Tofler")
        st.info("Zauba and Tofler are no longer used as a generic 'evidence' tab. Their public company records can be added here later only when they provide a specific corporate field we can reliably extract. This prevents a misleading evidence dump.")
    with tabs[1]:
        st.subheader("Technology Stack")
        st.write("**Source:**",tech_data.get("status",""))
        techs=tech_data.get("technologies",[])
        if techs:
            cols=st.columns(min(4,len(techs)))
            for i,t in enumerate(techs): cols[i%len(cols)].success(t)
        else: st.warning("No reliable public technology signals were found for this company.")
        cats=tech_data.get("categories",[])
        if cats:
            st.markdown("### Technology Areas")
            for x in cats: st.write("•",x)
        if tech_data.get("sources"):
            st.markdown("### Technology Sources")
            st.dataframe(pd.DataFrame(tech_data["sources"]),use_container_width=True,hide_index=True,column_config={"url":st.column_config.LinkColumn("Source")})
    with tabs[2]:
        st.subheader("Current Personas")
        st.caption("One person is shown only once. Former/previous/ex-employee search signals are excluded, and the actual current designation is displayed instead of relabeling the person as the requested persona.")
        if persona_df.empty:
            st.warning("No current persona could be found with sufficient public signals.")
        else:
            st.dataframe(persona_df[["Name","Current Designation","Company","Location","LinkedIn","Persona"]],use_container_width=True,hide_index=True,column_config={"LinkedIn":st.column_config.LinkColumn("LinkedIn")})
            st.download_button("⬇️ Download Personas",persona_df.to_csv(index=False).encode("utf-8"),file_name=re.sub(r"[^A-Za-z0-9]+","_",company_name)+"_personas.csv",mime="text/csv",use_container_width=True)

st.divider(); st.caption("360° Account Intelligence | Company + Technology + current Persona Discovery")
