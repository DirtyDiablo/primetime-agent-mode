# SAIC AESD Intelligence Engine (PrimeTime)

This folder contains structured outputs for the SAIC Army Enterprise Service Desk (AESD/AESMP) capture engine.

## Files
- `jobs.csv` — Parsed SAIC AESD & **probable AESD** requisitions.
- `people_targets.csv` — Hiring managers & team leads (manually enriched).
- `competitors.csv` — Overlap & churn intelligence in same geos/skills.
- `outreach_drafts.csv` — Turnkey outreach copy per target.
- `org.json` — Org hypothesis scaffold (role shells + known names).

## Classification Rules
- **Confirmed AESD**: explicit “AESD” or “AESMP” + Army markers (NETCOM/ARL/NEC sites).
- **Probable AESD**: Army locations (Adelphi, Aberdeen, Fort Eisenhower/Gordon, Fort Liberty, Fort Belvoir, Detroit Arsenal, etc.) + ITIL/ServiceNow/AESMF tool/process signals.
- **Non‑AESD DoD Desk**: SAIC help/service desk postings lacking Army/AESD signals (still captured for awareness).

## Fields
See column headers in each CSV. Lists are semicolon‑separated.

## Workflow
1. Scrape SAIC Careers + public boards.
2. Classify as Confirmed/Probable/Non‑AESD.
3. Append to `jobs.csv`; update timestamps.
4. Enrich `people_targets.csv` with names/links from Sales Nav/ZoomInfo.
5. Generate outreach rows in `outreach_drafts.csv`.
