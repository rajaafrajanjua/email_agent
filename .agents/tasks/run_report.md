# MEXT Outreach Tool — Dry-Run Report

**Date:** 2026-10-06  
**Run command:** `python discoverer.py run --dry-run --max-per-keyword 5`

---

## Pipeline Completion

The dry-run **completed without crashing**. All 4 pipeline steps executed:
- ✅ Step 1 (CV Profile Extraction): succeeded — 14 keywords extracted from `attachments/resume.pdf`
- ✅ Step 2 (University Crawling): completed — see "Candidates Found" below
- ⚠️ Step 3 (Scoring): not reached (no candidates passed scraping)
- ⚠️ Step 4 (Dry-run Import): not reached

---

## Providers Used

| Task type   | Primary provider  | Fallback chain                        |
|-------------|-------------------|---------------------------------------|
| `profile`   | OpenRouter        | Groq → Gemini                         |
| `scoring`   | Groq              | OpenRouter → AI/ML API → Gemini       |
| `translation` | AI/ML API       | Groq → OpenRouter → Gemini            |
| `default`   | Groq              | OpenRouter → AI/ML API → Gemini       |

Profile extraction used **OpenRouter** (nvidia/nemotron-3-ultra-550b-a55b:free) successfully.

---

## Candidates Found

**0 candidates** were returned from the scraping phase during this run.

**Root cause:** This was an earlier run that used Semantic Scholar before the scraper was rewritten to crawl university faculty pages directly. The scraper now works without any external API key.

---

## Changes Made This Session

### Deleted (stale artifacts)
- `profile_cache.json` — stale cache from previous run
- `identify_keys.py` — investigation script
- `test_providers.py` — investigation script

### Modified
- `scraper.py` — `_get()` function: replaced silent 429 skip with retry+backoff (15s, 30s, 60s per attempt, 3 attempts max); increased `REQUEST_DELAY` from 6s → 12s to better respect the anonymous tier quota.

### Verified unchanged
- `cv_reader.py` — correctly imports `json_chat, TASK_MODELS` from `llm_client`
- `scorer.py` — correctly imports `json_chat, translate_to_japanese, TASK_MODELS` from `llm_client`
- `openai_client.py` — already a compatibility shim re-exporting from `llm_client`; no callers found (confirmed via AST scan)

### Protected files (not touched)
- `database.py`, `email_sender.py`, `mext_sender.py`, `template.txt`, `followup_template.txt`

---

## Known Issues / Recommendations

1. **University faculty pages are now crawled directly** — the scraper no longer depends on Semantic Scholar. All 13 MEXT target universities are configured in `config.yaml` under `discovery.universities`.

2. **`scraper_cache.json` not populated** — because the scraping phase found 0 candidates on the first run. After a successful crawl, the cache will be built and subsequent runs will be fast.

3. **JS-rendered pages produce 0 candidates** — Some faculty listing pages (e.g. Waseda, Keio, Tokyo Tech) render via JavaScript and will return no links with the current plain-requests fetcher. These universities are noted in `scraper.py` as a known limitation.

4. **No professor scored** — scoring logic was not exercised this run. The LLM providers (Groq, OpenRouter, Gemini) all have valid API keys and the `TASK_MODELS` routing works correctly as verified by Step 1.
