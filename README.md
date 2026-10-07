# MEXT Outreach Tool

A fully-automated pipeline that discovers Japanese university professors aligned with your research interests, scores their fit using OpenAI, generates personalised bilingual outreach emails, and sends them on a polite, rate-limited schedule — all from the command line.

---

## How it works

```
Your CV (PDF)  ──┐
template.txt   ──┼──► cv_reader.py  ──► keywords + profile
                 │         │
                 │         ▼
                 │    scraper.py  ──► ResearchMap API + lab page scraping
                 │         │           (publications, emails, university filter)
                 │         ▼
                 └────► scorer.py  ──► OpenAI scores fit 0–10
                              │         generates focus_en + focus_ja
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

## Prerequisites

- Python 3.8+
- A Gmail account with an App Password
- An OpenAI API key (`sk-...`) — used for profile extraction and fit scoring

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
OPENAI_API_KEY=sk-...
```

Get your Gmail App Password: Google Account → Security → 2-Step Verification → App passwords.

### 3 — Add your CV

Place your CV inside `attachments/`. Supported formats:
- `attachments/cv.txt` — plain text (fastest, no extra library)
- `attachments/YourName_CV.pdf` — PDF (requires `pdfplumber`, already in requirements)

The same file is also sent as an attachment to every professor.

### 4 — Add other attachments (optional)

Put your **Transcripts** and **Research Outline** PDF files in `attachments/` too. They are automatically attached to every email.

### 5 — Adjust `config.yaml`

The file is documented inline. Key discovery settings:

| Key | Purpose |
|-----|---------|
| `discovery.min_score` | Minimum OpenAI fit score (0–10) to include a professor |
| `discovery.max_per_keyword` | ResearchMap results per keyword (higher = more coverage, more API cost) |
| `discovery.target_universities_only` | Only search MEXT-accepting universities (recommended: `true`) |
| `discovery.extra_keywords` | Manually add niche research topics on top of CV-extracted ones |

---

## Full automated workflow

### Step 1 — Run the discovery pipeline

```bash
python discoverer.py run
```

This does everything automatically:
1. Reads your CV + `template.txt` → extracts research keywords via OpenAI
2. Searches ResearchMap for professors matching each keyword
3. Fetches each professor's publications and lab page
4. Scores fit with OpenAI and generates personalised `focus_en` / `focus_ja`
5. Imports approved professors (score ≥ 6) into the send queue

First run may take 10–30 minutes depending on how many candidates are found.

**Dry run (no DB import):**
```bash
python discoverer.py run --dry-run
```

**Force re-extract profile from CV:**
```bash
python discoverer.py run --refresh-profile
```

**Search all Japanese universities (not just MEXT targets):**
```bash
python discoverer.py run --all-universities
```

### Step 2 — Review what was found

```bash
# Pretty-print all approved professors with scores and focus text
python discoverer.py report

# Check how many are in each pipeline stage
python discoverer.py status
```

### Step 3 — Preview the emails

```bash
python mext_sender.py preview --all
```

Read every rendered email carefully. If a `focus_en` doesn't sound right, edit `score_cache.json` or the database directly, or add that professor's email to your manual `professors.csv` with corrected focus text.

### Step 4 — Send

```bash
python mext_sender.py send --confirm
```

Respects `daily_cap`, `sending_window`, and `delay_range` automatically. Leave it running — it pauses and resumes as needed.

### Step 5 — Follow up (after 14 days)

```bash
python mext_sender.py followup --confirm
```

Uses `followup_template.txt` with a `Re:` subject line so it threads in the professor's inbox.

### Step 6 — Track replies

```bash
python mext_sender.py mark-replied professor@example.ac.jp
```

### Step 7 — Export final report

```bash
python mext_sender.py export --output mext_progress.csv
```

---

## Manual override

If you want to add professors the pipeline missed (e.g. someone without a ResearchMap profile):

1. Fill in `professors_template.csv` — see the comments inside for column definitions
2. Import it: `python mext_sender.py import professors.csv`

---

## Discovery pipeline commands

```bash
python discoverer.py run              # full pipeline
python discoverer.py run --dry-run    # preview without importing
python discoverer.py status           # cache + queue counts
python discoverer.py report           # print all approved professors
python discoverer.py clear-cache      # wipe scraper + score caches (keep profile)
python discoverer.py clear-cache --all  # wipe everything including profile
```

## Sender commands

```bash
python mext_sender.py import <file>       # import CSV manually
python mext_sender.py preview [--all]     # dry-run email preview
python mext_sender.py send [--confirm]    # send queue
python mext_sender.py followup [--confirm] [--days N]
python mext_sender.py status             # queue stats
python mext_sender.py mark-replied <email>
python mext_sender.py export [--output file]
```

---

## Caches

All caches are JSON files in the project root. They persist between runs so you pay for API calls only once:

| File | Contents |
|------|---------|
| `profile_cache.json` | Extracted keywords + summary from your CV |
| `scraper_cache.json` | Raw professor profiles from ResearchMap |
| `score_cache.json` | OpenAI scores + generated focus text per professor |

Delete the relevant cache file (or run `discoverer.py clear-cache`) to force a re-run of that stage.

---

## Running in the background

**Windows (PowerShell):**
```powershell
Start-Process -NoNewWindow python -ArgumentList "mext_sender.py send --confirm" `
  -RedirectStandardOutput send.log -RedirectStandardError send.log
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
| `discoverer.py` | Orchestrator CLI — runs the full discovery pipeline |
| `cv_reader.py` | Extracts research keywords from CV + template via OpenAI |
| `scraper.py` | ResearchMap API search + lab page email scraping |
| `scorer.py` | OpenAI fit scoring + focus_en / focus_ja generation |
| `openai_client.py` | Thin OpenAI wrapper (chat, json_chat, retry logic) |
| `mext_sender.py` | Send / followup / status / export CLI |
| `email_sender.py` | Multipart HTML+plain email rendering and SMTP dispatch |
| `database.py` | SQLite queue management |
| `config.yaml` | All settings (sending, discovery, scoring) |
| `template.txt` | Initial outreach email template |
| `followup_template.txt` | Follow-up email template |
| `professors_template.csv` | Manual CSV template with column docs |
| `attachments/` | CV, Transcripts, Research Outline (PDF) |
| `.env` | Credentials — never commit this |
| `profile_cache.json` | Cached CV profile (auto-generated) |
| `scraper_cache.json` | Cached scraper results (auto-generated) |
| `score_cache.json` | Cached scores + focus text (auto-generated) |
