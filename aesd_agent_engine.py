#!/usr/bin/env python3
# aesd_agent_engine.py — SAIC AESD Intelligence Engine with jobs_delta.csv

import csv, json, os, sys, re
from collections import defaultdict, Counter
from datetime import datetime, timedelta

REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
DATA_DIR   = os.path.join(REPO_ROOT, "data", "aesd")

JOBS_CSV        = os.path.join(DATA_DIR, "jobs.csv")
PEOPLE_CSV      = os.path.join(DATA_DIR, "people_targets.csv")
COMP_CSV        = os.path.join(DATA_DIR, "competitors.csv")
OUTREACH_CSV    = os.path.join(DATA_DIR, "outreach_drafts.csv")
ORG_JSON        = os.path.join(DATA_DIR, "org.json")
JOBS_SCORED_CSV = os.path.join(DATA_DIR, "jobs_scored.csv")
JOBS_DELTA_CSV  = os.path.join(DATA_DIR, "jobs_delta.csv")
JOBS_SNAPSHOT   = os.path.join(DATA_DIR, "jobs_snapshot.csv")  # previous run snapshot

ARMY_SITES = {"Adelphi","Aberdeen","Fort Eisenhower","Fort Gordon","Fort Liberty","Fort Belvoir","Detroit Arsenal","JBLM","Redstone Arsenal","Fort Meade"}
TOOL_SIGNALS = {"ServiceNow","SCCM","MECM","ACAS","HBSS","Active Directory","M365","Teams","VTC"}
PROCESS_SIGNALS = {"ITIL","Incident","Problem","Change","Knowledge","AESMF","AESMP","Enterprise Service Desk","Service Desk"}

def read_csv(path):
    if not os.path.exists(path): return []
    with open(path, newline='', encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline='', encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

def copy_csv(src, dst):
    rows = read_csv(src)
    if not rows: 
        # write empty with headers matching jobs.csv if present
        if os.path.exists(src):
            with open(src, newline='', encoding="utf-8") as f:
                hdr = next(csv.reader(f), [])
        else:
            hdr = []
        if hdr: write_csv(dst, [], hdr)
        return
    write_csv(dst, rows, list(rows[0].keys()))

def load_org():
    if os.path.exists(ORG_JSON):
        try:
            with open(ORG_JSON, encoding="utf-8") as f: return json.load(f)
        except Exception:
            return {}
    return {}

def save_org(obj):
    os.makedirs(os.path.dirname(ORG_JSON), exist_ok=True)
    with open(ORG_JSON, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def parse_bool(val):
    s = str(val).strip().lower()
    return s in ("true","t","1","yes","y")

def parse_date(val):
    for fmt in ("%Y-%m-%d","%Y-%m-%dT%H:%M:%SZ","%Y-%m-%dT%H:%M:%S","%m/%d/%Y"):
        try: return datetime.strptime(val, fmt)
        except Exception: pass
    return None

def contains_any(text, vocab):
    if not text: return False
    t = text.lower()
    return any(v.lower() in t for v in vocab)

def aesd_likelihood(row):
    title = (row.get("title") or "")
    notes = (row.get("notes") or "")
    prog  = (row.get("program_hint") or "")
    city  = (row.get("location_city") or "")
    tools = (row.get("tool_stack") or "")
    klass = (row.get("classification") or "")
    score = 0.0
    if contains_any(" ".join([title, notes, prog]), {"AESD","AESMP","Army Enterprise Service Desk"}): score += 4.0
    if any(site.lower() in city.lower() for site in ARMY_SITES): score += 2.0
    if contains_any(" ".join([tools, notes]), TOOL_SIGNALS): score += 1.0
    if contains_any(notes, PROCESS_SIGNALS): score += 0.5
    if "Confirmed AESD" in klass: score += 2.0
    if "Probable AESD"  in klass: score += 1.0
    return score

def why_now_priority(row):
    base = 0.0
    if parse_bool(row.get("repost_flag","")): base += 2.0
    d = parse_date(row.get("posted_date",""))
    if d:
        days = (datetime.utcnow() - d).days
        if days >= 45: base += 2.0
        elif days >= 30: base += 1.0
    shift = (row.get("shift") or "").lower()
    if any(k in shift for k in ["night","swing","weekend","24x7","rotation"]): base += 1.0
    if contains_any(row.get("tool_stack",""), {"ServiceNow","MECM","ACAS"}): base += 0.5
    return base

def norm_shift(s):
    s = (s or "").strip().lower()
    if "night" in s: return "Night"
    if "swing" in s or "evening" in s: return "Swing"
    if "weekend" in s: return "Weekend"
    return "Day"

def cluster_jobs(jobs):
    clusters = defaultdict(list)
    for j in jobs:
        city  = (j.get("location_city") or "").strip() or "Unknown"
        state = (j.get("location_state") or "").strip()
        shift = norm_shift(j.get("shift"))
        clusters[(city, state, shift)].append(j)
    return clusters

def infer_roles_for_cluster(jobs_in_cluster):
    titles = [(r.get("title") or "").lower() for r in jobs_in_cluster]
    c = Counter()
    for t in titles:
        if "manager" in t or "sdm" in t: c["manager_like"] += 1
        if "site lead" in t: c["site_lead"] += 1
        if "shift lead" in t: c["shift_lead"] += 1
        if any(k in t for k in ["tier 1","tier 2","tier 3","service desk tech","help desk","analyst","technician"]):
            c["tech"] += 1
    inferred = {
        "Service Delivery Manager": c["manager_like"] > 0 or c["site_lead"] > 0 or c["tech"] >= 6,
        "Site Lead": c["site_lead"] > 0 or c["tech"] >= 4,
        "Shift Lead": c["shift_lead"] > 0 or any("night" in (r.get("shift","").lower()) for r in jobs_in_cluster)
    }
    return inferred, c

def merge_org_with_sites(org, clusters):
    sites = []
    for (city, state, shift), rows in clusters.items():
        inferred, counts = infer_roles_for_cluster(rows)
        sites.append({
            "site": f"{city}, {state}".strip().strip(","),
            "shift": shift,
            "openings": len(rows),
            "title_counts": dict(counts),
            "inferred_chain": {
                "Program Manager": "TBD",
                "Service Delivery Manager": "Present" if inferred["Service Delivery Manager"] else "Gap",
                "Site Lead": "Present" if inferred["Site Lead"] else "Gap",
                "Shift Lead": "Present" if inferred["Shift Lead"] else "Gap"
            }
        })
    org_out = dict(org) if isinstance(org, dict) else {}
    org_out["Sites"] = sorted(sites, key=lambda s: (-s["openings"], s["site"], s["shift"]))
    return org_out

def ensure_headers(row, expected):
    return {k: row.get(k, "") for k in expected}

def build_index(rows, key="req_id"):
    idx = {}
    for r in rows:
        k = r.get(key, "")
        if k: idx[k] = r
    return idx

DELTA_FIELDS = ["title","location_city","location_state","clearance_required","shift","pay_min","pay_max","classification","program_hint","tool_stack","posted_date","repost_flag"]

def compare_rows(old, new):
    changed = []
    for f in DELTA_FIELDS:
        if (old.get(f,"") or "") != (new.get(f,"") or ""):
            changed.append(f)
    return changed

def main():
    expected_job_fields = ["req_id","title","classification","program_hint","company","location_city","location_state","remote_flag","clearance_required","8570_reqs","tool_stack","shift","pay_min","pay_max","pay_currency","posted_date","repost_flag","url","source","last_seen_utc","notes"]
    os.makedirs(DATA_DIR, exist_ok=True)

    # 0) Read current jobs
    jobs = [ensure_headers(r, expected_job_fields) for r in read_csv(JOBS_CSV)]

    # 1) Score + save jobs_scored.csv
    for r in jobs:
        r["_aesd_likelihood"] = round(aesd_likelihood(r), 2)
        r["_why_now"] = round(why_now_priority(r), 2)
        r["_priority"] = round(r["_aesd_likelihood"]*1.5 + r["_why_now"], 2)
    write_csv(JOBS_SCORED_CSV, jobs, expected_job_fields + ["_aesd_likelihood","_why_now","_priority"])

    # 2) Cluster + update org.json
    org = load_org()
    org2 = merge_org_with_sites(org, cluster_jobs(jobs))
    save_org(org2)

    # 3) Outreach (top 10)
    top = sorted(jobs, key=lambda r: (-r["_priority"], r.get("location_city",""), r.get("title","")))[:10]
    outreach_rows = []
    for r in top:
        site = f'{r.get("location_city","")}, {r.get("location_state","")}'
        pain = []
        if parse_bool(r.get("repost_flag","")): pain.append("repost_30d")
        d = parse_date(r.get("posted_date",""))
        if d and (datetime.utcnow() - d).days >= 30: pain.append("age_30d")
        if norm_shift(r.get("shift","")) != "Day": pain.append("shift_gap")
        pain_signal = ";".join(pain) if pain else "surge_multi_openings"
        subj = f'Rapid backfill for AESD — {r.get("title","")} at {site}'
        body = ("BLUF: We can plug your {title} gap at {site} with cleared, 8570-compliant talent experienced in {tools}. "
                "Typical time-to-slate 24–72 hrs. We’ve staffed night/weekend rotations across Army desks with ServiceNow/MECM coverage.\n\n"
                "Evidence: recurring postings and shift coverage patterns at {site}. "
                "We’ll deliver 3 resumes aligned to your KPIs (ASA, FCR, CSAT).").format(
                    title=r.get("title",""), site=site, tools=(r.get("tool_stack") or "ServiceNow/MECM/ACAS"))
        opener = f'{r.get("title","")} keeps showing up at {site} — are {r.get("shift","")} rotations still thin?'
        ask = f'Authorize a 72‑hr backfill sprint for {r.get("title","")} at {site}. We’ll send 3 slates in 48–72 hours.'
        outreach_rows.append({
            "target_name": "",
            "target_role": "Hiring Manager",
            "target_company": r.get("company","SAIC"),
            "target_site": site,
            "pain_signal": pain_signal,
            "competitor_present": "",
            "email_subject": subj,
            "email_body": body,
            "call_opener": opener,
            "exact_ask": ask,
            "attachments": "Prime_1Pager.pdf"
        })
    write_csv(OUTREACH_CSV, outreach_rows, ["target_name","target_role","target_company","target_site","pain_signal","competitor_present","email_subject","email_body","call_opener","exact_ask","attachments"])

    # 4) DELTA: compute jobs_delta.csv vs last snapshot
    prev = read_csv(JOBS_SNAPSHOT)
    prev_idx = build_index(prev, "req_id")
    curr_idx = build_index(jobs, "req_id")

    delta_rows = []
    seen = set()

    # new or changed
    for req_id, newr in curr_idx.items():
        seen.add(req_id)
        oldr = prev_idx.get(req_id)
        if not oldr:
            delta_rows.append({
                "req_id": req_id,
                "change_type": "new",
                "changed_fields": "",
                "title": newr.get("title",""),
                "location": f'{newr.get("location_city","")}, {newr.get("location_state","")}',
                "shift": newr.get("shift",""),
                "clearance_required": newr.get("clearance_required",""),
                "posted_date": newr.get("posted_date",""),
                "url": newr.get("url","")
            })
        else:
            changed = compare_rows(oldr, newr)
            if changed:
                delta_rows.append({
                    "req_id": req_id,
                    "change_type": "changed",
                    "changed_fields": ";".join(changed),
                    "title": newr.get("title",""),
                    "location": f'{newr.get("location_city","")}, {newr.get("location_state","")}',
                    "shift": newr.get("shift",""),
                    "clearance_required": newr.get("clearance_required",""),
                    "posted_date": newr.get("posted_date",""),
                    "url": newr.get("url","")
                })

    # Optional: removed roles (comment in if you want to track)
    # for req_id, oldr in prev_idx.items():
    #     if req_id not in seen:
    #         delta_rows.append({
    #             "req_id": req_id,
    #             "change_type": "removed",
    #             "changed_fields": "",
    #             "title": oldr.get("title",""),
    #             "location": f'{oldr.get("location_city","")}, {oldr.get("location_state","")}',
    #             "shift": oldr.get("shift",""),
    #             "clearance_required": oldr.get("clearance_required",""),
    #             "posted_date": oldr.get("posted_date",""),
    #             "url": oldr.get("url","")
    #         })

    write_csv(JOBS_DELTA_CSV, delta_rows, ["req_id","change_type","changed_fields","title","location","shift","clearance_required","posted_date","url"])

    # 5) Update snapshot to current for next run comparison
    copy_csv(JOBS_CSV, JOBS_SNAPSHOT)

    print("Wrote:", JOBS_SCORED_CSV)
    print("Wrote:", ORG_JSON)
    print("Wrote:", OUTREACH_CSV)
    print("Wrote:", JOBS_DELTA_CSV)
    print("Updated snapshot:", JOBS_SNAPSHOT)
    return 0

if __name__ == "__main__":
    sys.exit(main())