# China Extension Report

**Task:** Extend the MEXT Outreach Tool to also target top Chinese universities via the CGS/CSC scholarship.

**Date completed:** 2025

---

## Changes Made

### 1. `config.yaml` — china_universities added

Added `china_universities` list under `discovery:` with 8 entries:
- Tsinghua University, Peking University, Shanghai Jiao Tong University, Zhejiang University, Fudan University, USTC, Nanjing University, Harbin Institute of Technology.

### 2. `template_china.txt` — created

English-only (~300 words) initial outreach template for Chinese professors. Placeholders: `{last}`, `{university}`, `{focus_en}`, `{attachment_text}`, `{resume_link}`. References CGS/CSC scholarship. Ends with Zoom call request. No `{focus_ja}` placeholder.

### 3. `followup_template_china.txt` — created

English-only (~150 words) polite follow-up. Same placeholders as `template_china.txt`.

### 4. `email_sender.py` — updated

- Added `_CHINA_MARKERS` tuple with detection strings: `tsinghua`, `peking`, `sjtu`, `shanghai jiao tong`, `zhejiang`, `fudan`, `ustc`, `nanjing`, `harbin`, `wuhan`, `xi'an`, `beijing`, `chinese`.
- Added `_is_china_university(university: str) -> bool` helper using case-insensitive substring match.
- Updated `render_email()` to branch on `_is_china_university()`:
  - China → use `template_china.txt` / `followup_template_china.txt`, call `template.format()` without `focus_ja`.
  - Japan → unchanged behaviour.

### 5. `discoverer.py` — updated

- Added `--country` argument to the `run` subparser with `choices=['japan', 'china', 'all']`, `default='japan'`.
- Updated `cmd_run()` to select the appropriate university list based on `--country`.
- Updated `step_scrape()` to accept an optional `universities: list` parameter; when provided it uses that list directly (with caching), otherwise falls back to existing `discover_professors()` behaviour.

### 6. `README.md` — updated

- Added `--country` flag documentation under Step 1.
- Added dedicated **China universities (CGS/CSC scholarship)** section with feature comparison table and supported university list.
- Updated File overview table with the two new template files.

---

## Verification Results

### Unit tests — all 6 pass

```
test_database_deduplication ... ok
test_database_queue         ... ok
test_database_stats         ... ok
test_increment_fail         ... ok
test_template_last_name_extraction ... ok
test_template_rendering     ... ok
Ran 6 tests in 1.742s — OK
```

### `_is_china_university()` — all 12 cases correct

All Chinese university names return `True`; all Japanese university names return `False`.

### `template_china.txt` renders correctly

Confirmed: "Dear Professor Tang," opens correctly, `{university}` substituted to "Tsinghua University", `{focus_en}` substituted, no `{focus_ja}` placeholder present, no KeyError.

### Japan template regression — no regression

Japan template still renders with bilingual content unchanged.

### `discoverer.py run --country china --dry-run` — no crash

The command ran without crashing. Chinese university pages were attempted; unreachable pages printed warnings and continued. Scraping succeeded for Tsinghua (15 professors with emails) and Peking University (15 links found). STEP 2 completed: 122 total professors. STEP 3 (scoring) proceeded correctly using the existing score cache and OpenAI API.

### `china_universities` in `config.yaml` — confirmed present

8 Chinese university entries added under `discovery.china_universities`.

---

## Files Created / Modified

| File | Action |
|------|--------|
| `config.yaml` | Modified — added `china_universities` under `discovery:` |
| `template_china.txt` | Created — English-only CGS/CSC template |
| `followup_template_china.txt` | Created — English-only follow-up template |
| `email_sender.py` | Modified — `_is_china_university()`, updated `render_email()` |
| `discoverer.py` | Modified — `--country` arg, updated `cmd_run()` and `step_scrape()` |
| `README.md` | Modified — China section and updated file table |
| `.agents/tasks/china_extension_report.md` | Created — this report |

## Files NOT Modified (as required)

`database.py`, `llm_client.py`, `cv_reader.py`, `scorer.py`, `openai_client.py`, `email_verifier.py`
