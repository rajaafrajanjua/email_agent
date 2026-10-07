# Implementation Plan — MEXT Scraper Rewrite (No Semantic Scholar)

Generated from: live reading of scraper.py, scorer.py, discoverer.py, config.yaml,
llm_client.py, cv_reader.py.

---

## Key Design Decisions (recorded here so the coder does not re-decide them)

**D1 — Link-detection strategy for Japanese university pages.**
Professor profile links will be detected using a two-pass heuristic:
- Pass 1 (high-confidence): anchor `href` contains any of these path segments:
  `member`, `faculty`, `staff`, `professor`, `researcher`, `lab`, `people`,
  `teachers`, `教員`, `教授`, `研究者`, `スタッフ`.
- Pass 2 (structural): anchors whose href is on the same domain, points to an HTML
  path at depth ≥ 2 (e.g. `/research/lab-foo/`), and whose link text is ≥ 2
  characters (Japanese name or English name). Navigation items (e.g. "Home",
  "About", "News", "Contact") are filtered by a blocklist.
- All links that match the listing page's own URL are skipped.
- Rationale: Japanese faculty pages rarely use consistent URL patterns; two-pass
  is robust without being fragile.

**D2 — Japanese-page handling.**
Do not attempt machine translation. Extract whatever ASCII/romaji/English text
is present using the existing html.parser path. For interest keywords: look for
both English headings (`Research`, `Keywords`, `Interests`) and Japanese headings
(`専門`, `研究`, `興味`, `キーワード`). If a section is fully Japanese, store the
raw Japanese text in `interests` — the scorer already handles non-English
interests because it is given the text verbatim.

**D3 — `discover_professors()` new signature.**
Old signature: `discover_professors(keywords, max_per_keyword, target_universities_only, cache_path)`
New signature:
```python
def discover_professors(
    applicant_profile: dict,
    target_universities_only: bool = True,
    cache_path: str = 'scraper_cache.json',
    keywords: list[str] | None = None,   # kept for backward compat, ignored
    max_per_keyword: int = 20,            # kept for backward compat, ignored
) -> list[dict]
```
The `keywords` and `max_per_keyword` params are accepted but silently ignored
(the new scraper does not search by keyword; it crawls universities directly).
`applicant_profile` is passed through to each professor dict as
`prof['applicant_profile']` so the scorer can access `tech_stack` alongside
`keywords` — but the scorer calls its own `applicant_keywords` extraction and
doesn't need the full profile, so we only forward `profile['keywords']` via the
existing scorer interface. No scorer API changes are needed for this.

**D4 — `step_scrape()` caller update.**
`discoverer.py::step_scrape()` currently builds `all_keywords` and passes
`keywords=all_keywords`. After the rewrite it must pass `applicant_profile=profile`
instead. The `EXTRA_KEYWORDS` list in config.yaml is no longer used by the scraper
(since we're not doing keyword search), so `step_scrape()` should just forward
the profile dict and the `all_universities` flag.

**D5 — `crawler_cache.json` key.**
The cache key for each professor must be a stable string that survives re-runs.
Use: `f"{university_name}::{prof_url}"` where `prof_url` is the full URL of
the professor's profile page. This is stable, collision-safe, and human-readable.

**D6 — scorer.py prompt update approach.**
The `_SCORE_SYSTEM` constant in scorer.py gets a new section appended. The
`_format_papers()` helper already returns `'  (no publications found)'` — the
only change is instructing the LLM how to behave in that case. A single
conditional block added at the bottom of the system prompt is enough; no new
function is needed.

**D7 — Per-domain rate limiting.**
Use a `dict[str, float]` mapping `hostname → last_request_time`. Before each
request, if `time.time() - last_time < 2.0`, sleep for the remainder. This is
simpler than a global delay and prevents hammering one domain when crawling
multiple professors in sequence. It is maintained as a module-level variable
`_domain_last_hit: dict[str, float] = {}`.

**D8 — Python executable.**
All verify commands use `C:\Users\Raja\.local\bin\python3.14.exe`.
BeautifulSoup with `html.parser` is already in requirements.txt (beautifulsoup4).
No new dependencies are needed.

---

## Data Structures

### Professor dict (output of `crawl_university`)
```python
{
  'permalink':   str,          # "<university_name>::<prof_url>"
  'name':        str,          # full name, may be in Japanese if no English found
  'university':  str,          # university name from config.yaml entry
  'department':  str,          # department or lab name, '' if not found
  'lab_url':     str,          # the professor's profile page URL
  'source_url':  str,          # same as lab_url (compatibility with scorer/database)
  'email':       str,          # '' if not found
  'interests':   list[str],    # research interest strings (English or Japanese)
  'papers':      list[dict],   # [{'title': str, 'abstract': str, 'url': str}]
                               # abstract may be '' if not found on pub page
}
```

### config.yaml `universities` entry
```yaml
universities:
  - name: "University of Tokyo"
    faculty_url: "https://www.i.u-tokyo.ac.jp/edu/course/is/member.shtml"
    fallback_url: "https://www.k.u-tokyo.ac.jp/pros-e/index.html"   # optional
  - name: "Kyoto University"
    faculty_url: "https://www.ist.i.kyoto-u.ac.jp/research/professor.html"
  # ... etc
```
Only `name` and `faculty_url` are required. `fallback_url` is optional;
`crawl_university()` tries it only if the primary returns non-200 or 0 links.

---

## Implementation Plan

---

- [ ] 1. Update `config.yaml` — add the `universities:` list under `discovery:`.
      Add all 13 universities with the exact URLs specified in the brief.
      Include `fallback_url` only for University of Tokyo (the only one that
      has a fallback specified). Keep all existing `discovery:` keys intact.

      Files: `config.yaml`

      Verify:
      ```powershell
      C:\Users\Raja\.local\bin\python3.14.exe -c "import yaml; c=yaml.safe_load(open('config.yaml')); unis=c['discovery']['universities']; print(len(unis), 'universities'); assert len(unis)==13"
      ```
      Expected: prints `13 universities` with no AssertionError.

---

- [ ] 2. Rewrite `scraper.py` — full replacement, no Semantic Scholar code.

      ### 2a. Module-level setup (keep only what is needed)

      Keep these imports: `os`, `re`, `time`, `json`, `requests`,
      `BeautifulSoup`, `urljoin`, `urlparse`.
      Remove all S2 imports, constants, and functions.
      Add module-level: `_domain_last_hit: dict = {}`.
      Keep `_is_valid_email()` unchanged (it's a pure utility).

      ### 2b. Internal HTTP helper: `_fetch(url, timeout=15) -> requests.Response | None`

      - Enforces per-domain 2s delay using `_domain_last_hit`.
      - User-Agent: `'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'`
      - Returns `None` on non-200, timeout, or connection error.
      - Does not crash; prints a warning for failures.
      - No retry loop (pages that fail once are skipped to keep the pipeline fast).

      Signature:
      ```python
      def _fetch(url: str, timeout: int = 15) -> requests.Response | None:
      ```

      ### 2c. Email extractor: `_extract_email(html: str, base_url: str) -> str`

      Extracted from the old `_scrape_email()` into a pure HTML-in / email-out
      function (no HTTP calls). Returns `''` if nothing found.

      Logic (in order):
      1. Parse with `BeautifulSoup(html, 'html.parser')`.
      2. Scan all `<a href="mailto:...">` tags; return first valid email.
      3. Regex scan of page text after replacing obfuscations:
         - `[at]` → `@`
         - `(at)` → `@`
         - `（at）` → `@`
         - `＠` → `@`
         - `[dot]` → `.`
         - `_at_` → `@`
      4. Apply `_is_valid_email()` to regex match; reject if ends in `.png`/`.jpg`.

      Signature:
      ```python
      def _extract_email(html: str) -> str:
      ```

      ### 2d. Interest extractor: `_extract_interests(soup: BeautifulSoup) -> list[str]`

      Scans the BeautifulSoup tree for research interest sections.

      Strategy:
      1. Look for `<h2>`, `<h3>`, `<h4>`, `<dt>`, `<th>`, `<strong>`, `<b>` tags
         whose text (stripped, lowercased) matches any of:
         `research`, `interests`, `keywords`, `research interests`,
         `research areas`, `research topics`, `専門`, `研究`, `キーワード`, `興味`
      2. Once a matching heading is found, collect text from its sibling or
         following elements (next siblings, or the parent's next siblings)
         until another heading-level element is encountered.
      3. Split collected text by commas, newlines, and `<li>` boundaries.
      4. Filter out items that are < 3 characters or are pure whitespace.
      5. Return up to 10 items.

      If no interest section found: return `[]`.

      Signature:
      ```python
      def _extract_interests(soup: BeautifulSoup) -> list[str]:
      ```

      ### 2e. Publication link finder: `_find_publication_links(soup, base_url) -> list[str]`

      Scans the professor profile page for links to papers/publications.

      Strategy (in priority order):
      1. `<a>` tags where `href` ends in `.pdf` → absolute URL, up to 3.
      2. `<a>` tags where text contains `doi.org`, `arxiv.org`, `ieeexplore`,
         `acm.org`, `springer`, or `researchgate` in href.
      3. `<a>` tags under sections headed `Publications`, `Papers`, `Research Output`,
         `業績`, `論文` — collect up to 3 hrefs from those sections.
      4. Return deduplicated list, max 3 URLs. Return `[]` if nothing found.

      Signature:
      ```python
      def _find_publication_links(soup: BeautifulSoup, base_url: str) -> list[str]:
      ```

      ### 2f. Publication fetcher: `_fetch_publication(url) -> dict`

      Fetches a publication page (PDF or HTML) and extracts title + abstract.

      For PDFs: skip (don't download binary), return `{'title': url, 'abstract': '', 'url': url}`.
      For HTML:
      - Fetch page with `_fetch()`.
      - Look for `<meta name="description">` or `<meta property="og:description">` → abstract.
      - Look for `<h1>` or `<title>` tag → title.
      - Look for a `<section>` or `<div>` with class/id containing `abstract` → abstract.
      - Return `{'title': title[:200], 'abstract': abstract[:400], 'url': url}`.
      - On failure: return `{'title': url, 'abstract': '', 'url': url}`.

      Signature:
      ```python
      def _fetch_publication(url: str) -> dict:
      ```

      ### 2g. Professor profile link detector: `_is_professor_link(href, text, listing_url) -> bool`

      This is the core heuristic described in Design Decision D1.

      ```python
      _PROF_PATH_KEYWORDS = {
          'member', 'faculty', 'staff', 'professor', 'researcher',
          'lab', 'people', 'teachers', 'teacher',
          '教員', '教授', '研究者', 'スタッフ', 'laboratory',
      }

      _NAV_TEXT_BLOCKLIST = {
          'home', 'news', 'about', 'contact', 'access', 'sitemap',
          'japanese', 'english', 'top', 'back', 'more', 'search',
          'login', 'menu', 'privacy', 'map', 'link', 'links',
          'admission', 'admissions', 'event', 'events',
          'alumni', 'alumnae', 'course', 'courses', 'curriculum',
          'download', 'downloads', '日本語', 'english',
      }
      ```

      Logic:
      1. Parse `href` with `urlparse`. Skip anchors (`#`), mailto:, javascript:,
         external non-.ac.jp domains.
      2. If `href` path (lowercased) contains any word from `_PROF_PATH_KEYWORDS`
         → True.
      3. Else if link text (stripped, 2–40 chars) and not in `_NAV_TEXT_BLOCKLIST`
         and parsed path has depth ≥ 2 → True.
      4. Else False.

      Always return False if the resolved absolute URL == listing_url (self-link).

      Signature:
      ```python
      def _is_professor_link(href: str, text: str, listing_url: str) -> bool:
      ```

      ### 2h. Single-professor page scraper: `_scrape_professor_page(url, university_name) -> dict | None`

      Fetches one professor profile page and extracts all fields.

      Steps:
      1. `resp = _fetch(url)` — return `None` if failed.
      2. Parse with `BeautifulSoup(resp.text, 'html.parser')`.
      3. Extract name:
         - Try `<h1>` first.
         - Then `<title>` tag (split on `|`, `—`, `-`, take first segment).
         - Strip trailing university/department suffixes.
         - If still empty, return `None` (no anonymous professors).
      4. Extract email with `_extract_email(resp.text)`.
      5. Extract department/lab:
         - Look for `<meta name="department">`, or text near name that contains
           `Dept`, `Dept.`, `Laboratory`, `Lab`, `Department`, `研究室`, `学部`.
      6. Extract interests with `_extract_interests(soup)`.
      7. Find publication links with `_find_publication_links(soup, url)`.
      8. For each pub URL (up to 3): call `_fetch_publication(pub_url)`.
      9. Return dict matching the schema in **Data Structures** above.
         `permalink = f"{university_name}::{url}"`

      Signature:
      ```python
      def _scrape_professor_page(url: str, university_name: str) -> dict | None:
      ```

      ### 2i. University crawler: `crawl_university(university_entry: dict) -> list[dict]`

      Public function. Fetches the faculty listing page and returns professor dicts.

      Steps:
      1. Read `university_entry['faculty_url']` and optional `university_entry.get('fallback_url')`.
      2. `resp = _fetch(faculty_url)`. If `None`, try `fallback_url` if present. If still
         `None`, print warning and return `[]`.
      3. Parse listing with BeautifulSoup.
      4. Collect all `<a href=...>` tags. For each, call
         `_is_professor_link(href, text, faculty_url)`. Resolve to absolute URL with
         `urljoin(faculty_url, href)`.
      5. Deduplicate URLs (preserve order). Cap at 30 unique professor URLs.
      6. For each professor URL: call `_scrape_professor_page(url, university_entry['name'])`.
         Skip `None` results.
      7. Return list of professor dicts.

      Print progress: `"  → Crawling: {university_name} ({N} links found)"` before
      inner loop.

      Signature:
      ```python
      def crawl_university(university_entry: dict) -> list[dict]:
      ```

      ### 2j. Main discovery function: `discover_professors(...)`

      New signature (D3):
      ```python
      def discover_professors(
          applicant_profile: dict,
          target_universities_only: bool = True,
          cache_path: str = 'scraper_cache.json',
          keywords: list[str] | None = None,    # accepted, silently ignored
          max_per_keyword: int = 20,             # accepted, silently ignored
      ) -> list[dict]:
      ```

      Steps:
      1. Load `config.yaml` inside the function to read `discovery.universities`.
         This avoids a circular import with discoverer.py which also loads config.
         Use: `with open('config.yaml', 'r', encoding='utf-8') as f: cfg = yaml.safe_load(f)`
      2. `universities = cfg.get('discovery', {}).get('universities', [])`.
         If empty list, print a warning and return `[]`.
      3. Load cache from `cache_path` (dict keyed by permalink). Print loaded count.
      4. `seen_permalinks = set(cache.keys())`; `results = list(cache.values())`.
      5. For each university entry in `universities`:
         - If `target_universities_only=True` (default): process all (all 13 are
           already MEXT target universities). If `False`: also process — the
           distinction only matters if the user adds non-MEXT universities later.
         - Call `crawl_university(university_entry)`.
         - For each returned prof dict: if `prof['permalink']` not in
           `seen_permalinks`, add to results, add to cache, save cache
           incrementally to `cache_path`.
      6. Print `"  ✅  Discovery complete: {N} professor candidates."`.
      7. Return deduplicated results.

      Incremental cache save: after each new professor, write the full cache dict
      to `cache_path` with `json.dump(cache, f, ensure_ascii=False, indent=2)`.

      ### 2k. CLI test entry point (`if __name__ == '__main__':`)

      Replace the old CLI (which accepted `keywords`) with:

      ```python
      if __name__ == '__main__':
          import argparse, yaml
          parser = argparse.ArgumentParser()
          parser.add_argument('university', nargs='?',
                              help='University name to test-crawl (e.g. "NAIST")')
          parser.add_argument('--all', action='store_true',
                              help='Crawl all universities in config.yaml')
          args = parser.parse_args()

          with open('config.yaml', 'r', encoding='utf-8') as f:
              cfg = yaml.safe_load(f)
          unis = cfg['discovery']['universities']

          if args.all:
              targets = unis
          elif args.university:
              targets = [u for u in unis
                         if args.university.lower() in u['name'].lower()]
              if not targets:
                  print(f"No university matching '{args.university}' found in config.yaml.")
                  print("Available:", [u['name'] for u in unis])
                  exit(1)
          else:
              parser.print_help(); exit(0)

          for entry in targets:
              profs = crawl_university(entry)
              print(f"\n── {entry['name']} ── {len(profs)} professor(s)")
              for p in profs:
                  print(f"  {p['name']} | {p['email'] or '—'} | interests: {p['interests'][:2]}")
                  for paper in p['papers'][:2]:
                      print(f"    • {paper['title'][:70]}")
      ```

      Usage: `C:\Users\Raja\.local\bin\python3.14.exe scraper.py "NAIST"`

      Files: `scraper.py` (full rewrite)

      Verify:
      ```powershell
      C:\Users\Raja\.local\bin\python3.14.exe -c "import scraper; print('import OK')"
      ```
      Expected: `import OK` with no errors.

      Then test the CLI with NAIST (fastest page, English-friendly):
      ```powershell
      C:\Users\Raja\.local\bin\python3.14.exe scraper.py "NAIST"
      ```
      Expected: prints progress lines and at least 1 professor with a name. May
      print `0 professors` if the network is unreachable — that is acceptable as
      long as no Python exception is raised.

---

- [ ] 3. Update `scorer.py` — extend `_SCORE_SYSTEM` for Case A / Case B.

      The `_format_papers()` helper already returns `'  (no publications found)'`
      when `papers` is empty. The only change needed is adding the following
      block at the end of `_SCORE_SYSTEM`, before the `.strip()`:

      ```
      PUBLICATION HANDLING:

      Case A — Professor HAS publications (the "Recent publications" section
      lists at least one paper):
        • Base your score on the overlap between the applicant's skills and
          the actual paper topics listed.
        • In focus_en, reference at least one specific paper topic or technique
          by name (e.g. "your work on neural architecture search for IoT devices",
          not "your research in deep learning").

      Case B — Professor has NO publications ("(no publications found)"):
        • Base your score solely on the stated Research interests.
        • In focus_en, reference the specific stated research area or keyword
          from their interests list (e.g. "your research focus on edge AI and
          embedded systems", not "your work in machine learning").
        • Do NOT lower the score just because papers are absent — a strong
          interest-keyword match still warrants a high score.
        • If interests are also empty, score 0 and set include: false.
      ```

      **Exact change:** append the above block to the `_SCORE_SYSTEM` string,
      inside the triple-quoted string, before the `.strip()` call. Do not modify
      any other part of scorer.py.

      Also fix the error message on line:
      ```python
      print(f"  ✗  Gemini error scoring {prof.get('name')}: {e}")
      ```
      Change to:
      ```python
      print(f"  ✗  LLM error scoring {prof.get('name')}: {e}")
      ```
      (Minor: the error now comes from llm_client, not Gemini specifically.)

      Files: `scorer.py`

      Verify:
      ```powershell
      C:\Users\Raja\.local\bin\python3.14.exe -c "import scorer; print('scorer import OK')"
      ```
      Expected: `scorer import OK`.

---

- [ ] 4. Update `discoverer.py` — change `step_scrape()` to pass `applicant_profile`.

      ### Current `step_scrape()`:
      ```python
      def step_scrape(keywords: list[str], max_per_keyword: int = MAX_PER_KEYWORD,
                      all_universities: bool = False) -> list[dict]:
          _banner("STEP 2 — Discovering professors on ResearchMap")
          all_keywords = keywords + EXTRA_KEYWORDS
          if EXTRA_KEYWORDS:
              print(f"  + {len(EXTRA_KEYWORDS)} extra keyword(s) from config.yaml")
          candidates = discover_professors(
              keywords              = all_keywords,
              max_per_keyword       = max_per_keyword,
              target_universities_only = not all_universities,
              cache_path            = CACHE_SCRAPER,
          )
          return candidates
      ```

      ### New `step_scrape()`:
      ```python
      def step_scrape(profile: dict, all_universities: bool = False) -> list[dict]:
          _banner("STEP 2 — Discovering professors via university faculty pages")
          candidates = discover_professors(
              applicant_profile        = profile,
              target_universities_only = not all_universities,
              cache_path               = CACHE_SCRAPER,
          )
          return candidates
      ```

      ### `cmd_run()` call site change:
      Old line:
      ```python
      candidates = step_scrape(keywords, max_per_keyword=args.max_per_keyword, all_universities=args.all_universities)
      ```
      New line:
      ```python
      candidates = step_scrape(profile, all_universities=args.all_universities)
      ```

      ### `argparse` cleanup in `main()`:
      Remove the `--max-per-keyword` argument from `p_run` since the new scraper
      doesn't use it. Remove its `help` line too. Keep `--all-universities`.

      Also remove `MAX_PER_KEYWORD` and `EXTRA_KEYWORDS` reads from the
      `DISCOVERY` dict at the top of the file since neither is used anymore:
      ```python
      # DELETE these two lines:
      MAX_PER_KEYWORD   = DISCOVERY.get('max_per_keyword', 20)
      EXTRA_KEYWORDS    = DISCOVERY.get('extra_keywords', [])
      ```
      Keep `MIN_SCORE`, `TARGET_UNIVERSITIES`, `REQUIRE_EMAIL`.

      Files: `discoverer.py`

      Verify:
      ```powershell
      C:\Users\Raja\.local\bin\python3.14.exe -c "import discoverer; print('discoverer import OK')"
      ```
      Expected: `discoverer import OK`.

      Then dry-run the CLI parser (no network calls):
      ```powershell
      C:\Users\Raja\.local\bin\python3.14.exe discoverer.py --help
      ```
      Expected: help text prints without error.

---

- [ ] 5. End-to-end smoke test (profile already cached from prior run).

      This step verifies the entire pipeline runs without crashing. Because
      scraping is network-dependent, use `--dry-run` and confirm it reaches
      Step 2 without a Semantic Scholar error.

      ```powershell
      C:\Users\Raja\.local\bin\python3.14.exe discoverer.py run --dry-run
      ```

      Expected output includes:
      - `STEP 1 — Extracting applicant profile from CV` (loads cache)
      - `STEP 2 — Discovering professors via university faculty pages`
      - `→ Crawling:` lines for each university
      - No `ImportError`, no `AttributeError`, no `NameError`
      - Pipeline reaches at least Step 2 and starts network attempts

      Acceptable partial outcomes: network timeouts/non-200 responses are fine
      (printed as warnings); the tool must not raise an unhandled exception.

---

## Summary of files changed

| File | Change |
|------|--------|
| `scraper.py` | Full rewrite — BeautifulSoup university crawler, no S2 code |
| `scorer.py` | Append Case A / Case B guidance to `_SCORE_SYSTEM`; fix error message |
| `discoverer.py` | Update `step_scrape()` signature + `cmd_run()` call + remove unused config reads |
| `config.yaml` | Add `universities:` list under `discovery:` |

## Files explicitly NOT touched

`database.py`, `email_sender.py`, `mext_sender.py`, `template.txt`,
`followup_template.txt`, `llm_client.py`, `cv_reader.py`, `openai_client.py`
