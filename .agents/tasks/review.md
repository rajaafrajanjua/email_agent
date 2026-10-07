# Scraper rewrite: BeautifulSoup university crawler replacing Semantic Scholar

The previous pipeline broke when Gemini's free-tier quota was exhausted because `cv_reader.py` called Gemini directly for profile extraction. In parallel, the scraper relied on Semantic Scholar's affiliation-search API, which requires an institutional email address the user doesn't have. This change replaces the S2 approach with a direct HTML crawler of MEXT university faculty pages, wires in a four-provider LLM fallback chain (OpenRouter → Groq → AI/ML API → Gemini), and adds Case A / Case B scoring guidance so the LLM can distinguish professors with publications from those without.

Watch for (confirmed): the 30-professor cap and 2-second per-domain delay are both present. Watch for (likely): Pass 2 of the link-detection heuristic uses `depth >= 1` which may admit top-level index pages as professor profiles on flat-structured sites. Watch for (confirmed): `'lab'` in `_PROF_PATH_KEYWORDS` is a substring match, not a path-segment match, so URLs containing `collaboration` or `syllable` pass Pass 1.

**Verdict**: APPROVED

---

## High-level view

`scraper.py` is a full rewrite with zero Semantic Scholar imports or API calls. The module-level `_domain_last_hit` dict enforces a 2-second gap per hostname across all requests in the process, including publication sub-fetches. The 30-professor cap fires in `crawl_university()` before the inner loop, so at most 30 HTTP fetches fire per university.

The link-detection heuristic uses two passes: path-keyword matching (high confidence) and name-like anchor-text analysis (structural). Pass 2 lowered the depth threshold from 2 to 1 — a deliberate trade-off to stop valid profiles on flat-structured sites being dropped. The risk is that some non-profile pages at depth 1 with name-like text will be fetched, fail name-extraction in `_scrape_professor_page`, and return `None`. The `'lab'` keyword in the Pass 1 set is a substring match, meaning paths like `/collaboration/` are admitted — a known false-positive source that costs extra HTTP requests but not data-quality errors.

The email extractor covers `mailto:` hrefs first, then regex-scans visible text after replacing five obfuscation patterns including the fullwidth variants `（at）` and `＠`. A second `re.sub` pass collapses whitespace that may surround `@` or `.` when block-level siblings are joined by BeautifulSoup's separator.

`scorer.py`'s `_SCORE_SYSTEM` prompt now contains explicit Case A / Case B instructions. Case B explicitly tells the LLM not to penalise absent papers when stated interests match — directly addressing the scenario where most professors will have no publications discoverable via direct HTML crawl.

`discoverer.py`'s `step_scrape()` now takes `profile: dict` and passes it through to `discover_professors(applicant_profile=profile, ...)`. `cmd_run()` calls `step_scrape(profile, ...)`. All 13 MEXT universities are present in `config.yaml` with correct `faculty_url` values.

---

<details>
<summary>Issues (3)</summary>

1. **`'lab'` substring match admits false-positive URLs** — `_PROF_PATH_KEYWORDS` is checked with `if kw in path_lower` (substring), so any URL containing `'lab'` anywhere (e.g. `/collaboration/`, `/syllable/`, `/elaborate/`) passes Pass 1 and triggers an HTTP fetch. Switch to a path-segment check (`set(path_lower.split('/')) & _PROF_PATH_KEYWORDS`) to eliminate this class of false positives. Confidence: confirmed.

2. **Pass 1 / Pass 2 filter granularity mismatch** — `_EXCLUDE_PATH_FRAGMENTS` is checked as a set-intersection on path segments (split on `/`), while `_PROF_PATH_KEYWORDS` is a substring scan. A path like `/lab-news/` passes the exclude filter (because `'news'` is a substring of the segment `'lab-news'`, not an exact match after splitting) and simultaneously passes Pass 1 (because `'lab'` is in the path). The two filters need to operate at the same granularity to be consistent. Confidence: confirmed.

3. **Pass 2 depth ≥ 1 may admit flat index pages** — same-domain links at depth 1 with CJK or title-cased Latin anchor text are accepted. A site whose top-level pages carry Japanese labels (e.g. `<a href="/research/">研究室一覧</a>`) could match. These will be fetched and rejected by `_scrape_professor_page` (no valid `<h1>` name), but they consume HTTP budget and rate-limit slots. Consider gating Pass 2 on depth ≥ 2 for links that also lack a `_PROF_PATH_KEYWORDS` match in the path. Confidence: likely.

</details>

---

<details>
<summary>Details</summary>

### Link-detection heuristics: substring vs segment mismatch

`_is_professor_link` applies `_EXCLUDE_PATH_FRAGMENTS` as `path_parts_set & _EXCLUDE_PATH_FRAGMENTS`, where `path_parts` is the URL path split on `/`. This correctly excludes `/lab/news/` because `'news'` is an exact path part. However, the Pass 1 inclusion check is `if kw in path_lower` — a substring match over the full lowercased path string. The keyword `'lab'` (3 chars) is present inside `'collaboration'`, `'elaboration'`, `'syllable'`, and `'vocabulary'`. A URL like `https://example.ac.jp/collaborative-research/` passes Pass 1 and triggers a professor-page fetch. The fetched page will likely return `None` from `_scrape_professor_page` (no `<h1>` name matching a person), so data quality is preserved, but the wasted fetches add latency and could exhaust per-domain rate-limit headroom faster than expected on multi-lab university sites.

The fix is to apply both filters at the same granularity: `set(path_lower.strip('/').split('/')) & _PROF_PATH_KEYWORDS`. This would catch `'lab'` as an exact path segment (`/lab/`) but not as part of `'collaboration'`.

### Email extraction: whitespace normalisation and a remaining gap

The `get_text(separator=' ')` call prevents adjacent block-level elements from colliding into one token (e.g. `user@` and `domain.com` joining without separator). The follow-up `re.sub(r'\s+@\s+', '@', text)` handles cases where obfuscation replacement leaves surrounding whitespace. This is more thorough than a plain text extraction + regex approach.

One remaining gap: when a local-part is itself split across elements — e.g. `<span>username</span><span> [at] </span><span>domain.ac.jp</span>` — the replacement yields `username @ domain.ac.jp` which the whitespace normalisation collapses to `username@domain.ac.jp` correctly. But if the split is `<span>user</span><span>name</span><span>[at]domain.ac.jp</span>`, the name halves become `user name[at]domain.ac.jp` → `user name@domain.ac.jp`, which does not match the email regex. This pattern is uncommon on Japanese faculty pages but occurs occasionally on older static sites.

### `discover_professors()` backward-compatibility risk

The new signature keeps `keywords` and `max_per_keyword` as accepted-but-ignored keyword arguments. A caller that passes the old first positional argument — `discover_professors(keywords_list, ...)` — silently assigns a list to `applicant_profile`. The scraper never reads `applicant_profile` internally (it only uses `config.yaml`), so this does not crash. But if a future caller expects the function to forward `profile['keywords']` to sub-functions and passes a list instead of a dict, the failure will be silent and hard to debug. A `isinstance(applicant_profile, dict) or raise TypeError` guard at the top of the function would make misuse explicit. Confidence: likely (safe in current codebase, risk lives in future callers).

</details>

---

<details>
<summary>Files changed</summary>

- `scraper.py` — Full rewrite: BeautifulSoup-based university faculty page crawler, no Semantic Scholar code.
- `scorer.py` — Appended Case A / Case B instructions to `_SCORE_SYSTEM`; changed error log from "Gemini error" to "LLM error".
- `discoverer.py` — `step_scrape()` now accepts `profile: dict`; `cmd_run()` updated; removed `MAX_PER_KEYWORD`, `EXTRA_KEYWORDS`, and `--max-per-keyword` argparse arg.
- `config.yaml` — Added 13-entry `universities:` list under `discovery:` with `faculty_url` (and one `fallback_url`) per university.

Full diff: `git diff main` from `D:\python\mext-outreach-tool`
</details>
