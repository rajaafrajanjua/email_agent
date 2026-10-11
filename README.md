# MEXT & China Outreach Tool

A fully-automated pipeline that discovers university professors aligned with your research interests, scores their fit using AI, generates personalised bilingual outreach emails, and sends them on a polite, rate-limited schedule — for both **Japan (MEXT)** and **China (CSC/CGS)** applications.

---

## How it works

```
Your CV (PDF)  ──┐
template.txt   ──┼──► cv_reader.py  ──► keywords + profile
                 │         │
                 │         ▼
                 │    scraper.py  ──► University faculty pages (no API needed)
                 │         │           (crawls real professor pages, extracts
                 │         │            name, email, research interests, papers)
                 │         ▼
                 └────► scorer.py  ──► LLM scores fit 0–10
                              │         generates focus_en + focus_ja/zh
                              ▼
                         database.py  ──► SQLite send queue
                              │
                              ▼
                         mext_sender.py  ──► Gmail SMTP
                              │               (rate-limited, windowed)
                              ▼
                         follow-up after 14 days if no reply
```

---

## Two independent pipelines

| | Japan | China |
|--|-------|-------|
| Scholarship | MEXT University Recommendation | CSC / Chinese Government Scholarship |
| Template | English + Japanese | English + Chinese (Simplified) |
| University config | `discovery.universities` | `discovery.china_universities` |
| Scraper cache | `scraper_cache.json` | `scraper_cache_china.json` |
| Score cache | `score_cache.json` | `score_cache_china.json` |
| Intake | October 2027 | 2026/2027 |

---

## Prerequisites

- Python 3.8+
- A Gmail account with an **App Password**
- An API key for one of: Groq, Google AI Studio (Gemini), or OpenRouter (free tiers available)

---

## Setup

### 1 — Install dependencies

```bash
pip install -r requirements.txt
```

### 2 — Configure credentials

Create `.env` in the project root:

```
GMAIL_ADDRESS=your_email@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
GROQ_API_KEY=gsk_...          # primary LLM (14,400 req/day free)
API_KEY=AIza...               # Gemini fallback (Google AI Studio)
OPEN_ROUTER_API_KEY=sk-or-... # OpenRouter fallback
```

Get your Gmail App Password: **Google Account → Security → 2-Step Verification → App passwords**

### 3 — Add your CV

Place your CV inside `attachments/`:
- `attachments/cv.txt` — plain text (fastest)
- `attachments/YourName_CV.pdf` — PDF (auto-extracted)

Other attachments (Transcripts, Research Outline PDF) in the same folder are automatically attached to every email.

### 4 — Adjust `config.yaml`

Key settings:

| Key | Purpose |
|-----|---------|
| `discovery.min_score` | Minimum LLM fit score (0–10) to queue a professor |
| `discovery.require_email` | `false` = import even without email found |
| `discovery.field_keywords` | Pre-filter — only score professors whose pages mention these terms |
| `discovery.universities` | Japan university list (MEXT) |
| `discovery.china_universities` | China university list (CSC) |
| `sending_window` | Only send inside these hours (Japan timezone) |
| `daily_cap` | Max emails per day |

---

## Full automated workflow

### Japan (MEXT)

```bash
# 1. Discover professors (crawls faculty pages, scores fit, imports queue)
python discoverer.py run --country japan

# Dry-run first to preview without importing
python discoverer.py run --country japan --dry-run

# 2. Verify all queued emails are deliverable
python mext_sender.py verify-queue

# 3. Preview emails
python mext_sender.py preview --all

# 4. Send
python mext_sender.py send --confirm

# 5. Follow up after 14 days
python mext_sender.py followup --confirm
```

### China (CSC)

```bash
# 1. Discover Chinese professors (separate caches, separate template)
python discoverer.py run --country china

python discoverer.py run --country china --dry-run

# 2-5. Same sender commands work for both
python mext_sender.py verify-queue
python mext_sender.py preview --all
python mext_sender.py send --confirm
python mext_sender.py followup --confirm
```

### Both at once

```bash
python discoverer.py run --country all
```

---

## Email verification (before sending)

The tool verifies every email before queuing it:

- **Format check** — basic regex
- **MX record lookup** — confirms the mail server exists
- **SMTP RCPT TO probe** — confirms the specific address is accepted

```bash
# Check all queued/sent emails
python mext_sender.py verify-queue

# Mark confirmed-invalid addresses as failed (won't be sent to)
python mext_sender.py verify-queue --fix

# Import without verification (not recommended)
python mext_sender.py import professors.csv --skip-verify
```

Addresses that **hard-fail** (SMTP 550 "user unknown") are rejected at import time. Addresses where the server **blocks probes** are imported anyway — these are usually valid but conservative mail servers.

---

## Discovery pipeline commands

```bash
python discoverer.py run [--country japan|china|all] [--dry-run] [--refresh-profile]
python discoverer.py status           # cache counts + queue stats
python discoverer.py report           # print all approved professors
python discoverer.py clear-cache [--country japan|china|all] [--all]
```

## Sender commands

```bash
python mext_sender.py import <file>           # import CSV manually
python mext_sender.py import <file> --skip-verify  # skip email verification
python mext_sender.py preview [--all]         # dry-run email preview
python mext_sender.py send [--confirm]        # send queue
python mext_sender.py followup [--confirm] [--days N]
python mext_sender.py verify-queue [--fix]   # check email deliverability
python mext_sender.py status                 # queue stats
python mext_sender.py mark-replied <email>
python mext_sender.py export [--output file]
```

---

## Manual professor list

If you want to add professors the auto-discovery missed (e.g. no public faculty page):

1. Fill `professors_template.csv` — see comments inside for column definitions
2. Import: `python mext_sender.py import professors.csv`

The CSV format for **Japan** professors:
```
name,email,university,department,lab_url,focus_en,focus_ja,source_url
```

The CSV format for **China** professors (no `focus_ja` needed — leave blank):
```
name,email,university,department,lab_url,focus_en,focus_ja,source_url
Tao Wang,wang@cs.tsinghua.edu.cn,Tsinghua University,CS,...,"On-device federated learning...",,https://...
```

The system auto-detects China universities by name and uses the bilingual EN+ZH template automatically.

---

## Caches

All caches are JSON files in the project root. They persist so you pay for API calls only once:

| File | Contents |
|------|---------|
| `profile_cache.json` | Extracted keywords + summary from your CV |
| `scraper_cache.json` | Raw professor profiles — Japan universities |
| `scraper_cache_china.json` | Raw professor profiles — China universities |
| `score_cache.json` | LLM scores + focus text — Japan |
| `score_cache_china.json` | LLM scores + focus text — China |
| `verify_cache.json` | Email verification results (30-day TTL) |

---

## Running in the background

**Windows (PowerShell):**
```powershell
Start-Process -NoNewWindow `
  -FilePath "C:\Users\Raja\.local\bin\python3.14.exe" `
  -ArgumentList "mext_sender.py send --confirm" `
  -RedirectStandardOutput "send.log" `
  -RedirectStandardError "send_err.log"
```

**Linux/macOS:**
```bash
nohup python mext_sender.py send --confirm > send.log 2>&1 &
```

---

## Running tests

```bash
python -m unittest tests/test_sender.py
```

---

## File overview

| File | Purpose |
|------|---------|
| `discoverer.py` | Orchestrator — runs the full discovery pipeline |
| `cv_reader.py` | Extracts research keywords from CV + template via LLM |
| `scraper.py` | University faculty page crawler (no external API) |
| `scorer.py` | LLM fit scoring + focus_en / focus_ja generation |
| `llm_client.py` | Multi-provider LLM router (Groq → OpenRouter → Gemini) |
| `email_verifier.py` | MX + SMTP email deliverability checker |
| `openai_client.py` | Compatibility shim → re-exports from llm_client |
| `mext_sender.py` | Send / followup / status / export / verify-queue CLI |
| `email_sender.py` | Multipart HTML+plain email rendering and SMTP dispatch |
| `database.py` | SQLite queue management |
| `config.yaml` | All settings (sending, discovery, university lists) |
| `template.txt` | Japan outreach email (English + Japanese) |
| `followup_template.txt` | Japan follow-up email (English + Japanese) |
| `template_china.txt` | China outreach email (English + Chinese Simplified) |
| `followup_template_china.txt` | China follow-up email (English + Chinese Simplified) |
| `professors_template.csv` | Manual CSV template with column docs |
| `attachments/` | CV, Transcripts, Research Outline (PDF) |
| `.env` | Credentials — never commit this |
| `profile_cache.json` | Cached CV profile (auto-generated) |
| `scraper_cache.json` | Cached Japan scraper results (auto-generated) |
| `scraper_cache_china.json` | Cached China scraper results (auto-generated) |
| `score_cache.json` | Cached Japan scores + focus text (auto-generated) |
| `score_cache_china.json` | Cached China scores + focus text (auto-generated) |
| `verify_cache.json` | Cached email verification results (auto-generated) |

---

## Recommended workflow (end to end)

```
1.  Put CV PDF in attachments/
2.  Set credentials in .env
3.  python discoverer.py run --country japan --dry-run   ← review
4.  python discoverer.py run --country japan             ← import queue
5.  python mext_sender.py verify-queue --fix             ← remove bad emails
6.  python mext_sender.py preview --all                  ← read every email
7.  python mext_sender.py send --confirm                 ← send
8.  [14 days later] python mext_sender.py followup --confirm
9.  python mext_sender.py mark-replied <email>           ← for every reply
10. python mext_sender.py export                         ← final report

Repeat steps 3–9 with --country china for Chinese universities.
```
