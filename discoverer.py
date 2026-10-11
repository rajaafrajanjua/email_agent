"""
discoverer.py
-------------
The fully-automated MEXT professor discovery orchestrator.

Pipeline:
  1. cv_reader   → read CV + template → extract applicant profile (keywords, summary)
  2. scraper     → crawl MEXT university faculty pages → fetch profiles + publications
  3. scorer      → LLM-score each professor → generate personalised focus_en / focus_ja
  4. database    → import approved professors into the send queue

Usage:
  python discoverer.py run              # full auto run
  python discoverer.py run --dry-run    # score and report without importing
  python discoverer.py status           # show pipeline cache state
  python discoverer.py clear-cache      # wipe all caches (profile, scraper, score)
  python discoverer.py report           # pretty-print approved professors from score cache
"""

import argparse
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ── load .env early so OPENAI_API_KEY and GMAIL_* are available ───────────────
if os.path.exists('.env'):
    with open('.env', 'r') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

import yaml
from cv_reader  import extract_profile
from scraper    import discover_professors
from scorer     import score_professors, to_db_row
from database   import add_professor, get_stats

# ── config ────────────────────────────────────────────────────────────────────
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

DISCOVERY = config.get('discovery', {})
MIN_SCORE              = DISCOVERY.get('min_score', 6)
TARGET_UNIVERSITIES    = DISCOVERY.get('target_universities_only', True)
REQUIRE_EMAIL          = DISCOVERY.get('require_email', True)

CACHE_PROFILE       = 'profile_cache.json'
CACHE_SCRAPER       = 'scraper_cache.json'        # Japan scraper cache
CACHE_SCRAPER_CHINA = 'scraper_cache_china.json'  # China scraper cache (separate)
CACHE_SCORE         = 'score_cache.json'           # Japan score cache
CACHE_SCORE_CHINA   = 'score_cache_china.json'     # China score cache (separate)


# ── step helpers ──────────────────────────────────────────────────────────────

def _banner(text: str):
    bar = '─' * 60
    print(f"\n{bar}")
    print(f"  {text}")
    print(bar)


def step_profile(refresh: bool = False) -> dict:
    _banner("STEP 1 — Extracting applicant profile from CV")
    profile = extract_profile(force_refresh=refresh)
    print(f"\n  Keywords ({len(profile['keywords'])}):")
    for kw in profile['keywords']:
        print(f"    • {kw}")
    return profile


def step_scrape(profile: dict, all_universities: bool = False,
                universities: 'list | None' = None,
                cache_path: str = CACHE_SCRAPER) -> list[dict]:
    _banner("STEP 2 — Discovering professors via university faculty pages")
    if universities is not None:
        # Caller has already assembled the target list; pass it directly.
        from scraper import crawl_university
        import json, os

        cache: dict = {}
        if os.path.isfile(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                try:
                    cache = json.load(f)
                except json.JSONDecodeError:
                    cache = {}
            if cache:
                print(f"  📦  Cache loaded ({len(cache)} professors).")

        seen    = set(cache.keys())
        results = list(cache.values())

        for entry in universities:
            print(f"\n  🏫  {entry.get('name','?')}")
            for p in crawl_university(entry):
                pk = p.get('permalink', '')
                if pk and pk not in seen:
                    seen.add(pk)
                    results.append(p)
                    cache[pk] = p
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        import json as _json
                        _json.dump(cache, f, ensure_ascii=False, indent=2)

        print(f"\n  ✅  Total: {len(results)} professors found.")
        return results
    else:
        candidates = discover_professors(
            applicant_profile        = profile,
            target_universities_only = not all_universities,
            cache_path               = cache_path,
        )
        return candidates


def step_score(candidates: list[dict], keywords: list[str],
               cache_path: str = CACHE_SCORE) -> list[dict]:
    _banner("STEP 3 — Scoring professor fit with OpenAI")
    approved = score_professors(
        candidates         = candidates,
        applicant_keywords = keywords,
        min_score          = MIN_SCORE,
        require_email      = REQUIRE_EMAIL,
        score_cache_path   = cache_path,
        field_keywords     = DISCOVERY.get('field_keywords', []),
    )
    return approved


def step_import(approved: list[dict], dry_run: bool = False) -> tuple[int, int]:
    _banner("STEP 4 — Importing approved professors into send queue")

    import yaml as _yaml
    with open('config.yaml', 'r', encoding='utf-8') as _f:
        _cfg = _yaml.safe_load(_f)
    require_email = _cfg.get('discovery', {}).get('require_email', True)

    added = skipped = 0
    for prof in approved:
        row = to_db_row(prof)
        missing_focus = not row['focus_en'] or not row['focus_ja']
        missing_email = not row['email']
        if missing_focus or (require_email and missing_email):
            reasons = []
            if missing_email:    reasons.append("missing email")
            if missing_focus:    reasons.append("missing focus text")
            print(f"  ⚠  Skipping {row['name']}: {', '.join(reasons)}.")
            skipped += 1
            continue
        if missing_email:
            # require_email=false: import anyway with a placeholder so the row isn't lost.
            # The user can fill the email later (or skip sending to these rows).
            row['email'] = f"unknown@{row.get('university','example').split()[0].lower()}.ac.jp"
            print(f"  ℹ  {row['name']}: email unknown — using placeholder. Update before sending.")
        if dry_run:
            print(f"  [dry-run] Would import: {row['email']}  ({row['university']})  score={prof.get('score')}")
            print(f"            focus_en: {row['focus_en'][:80]}...")
            added += 1
        else:
            if add_professor(row):
                print(f"  +  Imported: {row['email']}  ({row['university']})  score={prof.get('score')}/10")
                added += 1
            else:
                print(f"  –  Duplicate skipped: {row['email']}")
                skipped += 1
    return added, skipped


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_run(args):
    country = getattr(args, 'country', 'japan')

    if country == 'japan':
        print("\n🚀  Japan Professor Discovery Pipeline")
        print(   "   ===================================")
        selected_universities = DISCOVERY.get('universities', [])
        scraper_cache = CACHE_SCRAPER
        score_cache   = CACHE_SCORE
    elif country == 'china':
        print("\n🚀  China Professor Discovery Pipeline")
        print(   "   ===================================")
        selected_universities = DISCOVERY.get('china_universities', [])
        scraper_cache = CACHE_SCRAPER_CHINA
        score_cache   = CACHE_SCORE_CHINA
    else:  # 'all'
        print("\n🚀  Japan + China Professor Discovery Pipeline")
        print(   "   =========================================")
        selected_universities = (DISCOVERY.get('universities', []) +
                                 DISCOVERY.get('china_universities', []))
        # For 'all', use the Japan caches (results merged into same DB anyway)
        scraper_cache = CACHE_SCRAPER
        score_cache   = CACHE_SCORE

    if not selected_universities:
        print(f"\n⚠  No universities configured for country='{country}' in config.yaml.")
        return

    print(f"  Universities to crawl: {len(selected_universities)}")

    # Step 1 — profile
    profile  = step_profile(refresh=args.refresh_profile)
    keywords = profile['keywords']

    # Step 2 — scrape (separate cache per country)
    candidates = step_scrape(
        profile,
        all_universities   = args.all_universities,
        universities       = selected_universities,
        cache_path         = scraper_cache,
    )
    if not candidates:
        print("\n⚠  No candidates found. Check that target university pages are reachable.")
        return

    # Step 3 — score (separate cache per country)
    approved = step_score(candidates, keywords, cache_path=score_cache)
    if not approved:
        print(f"\n⚠  No professors passed the scoring threshold (min_score={MIN_SCORE}).")
        return

    # Step 4 — import
    added, skipped = step_import(approved, dry_run=args.dry_run)

    _banner("PIPELINE COMPLETE")
    print(f"  Country target      : {country}")
    print(f"  Candidates found   : {len(candidates)}")
    print(f"  Approved (score≥{MIN_SCORE}) : {len(approved)}")
    if args.dry_run:
        print(f"  [dry-run] Would import: {added}")
    else:
        print(f"  Imported into queue: {added}")
        print(f"  Skipped/duplicates : {skipped}")
        stats = get_stats()
        print(f"\n  Queue stats:")
        for status, count in stats.items():
            print(f"    {status:<15} {count}")

    if not args.dry_run and added > 0:
        print(f"\n  ✅  Run `python mext_sender.py preview --all` to review emails.")
        print(f"      Then `python mext_sender.py send --confirm` to start sending.")


def cmd_status(args):
    _banner("Discovery Pipeline Cache Status")

    def _cache_info(path: str, key_field: str = None) -> str:
        if not os.path.isfile(path):
            return "not found"
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return f"{len(data)} entries"
        if isinstance(data, list):
            return f"{len(data)} entries"
        return "present"

    print(f"  profile_cache.json        : {_cache_info(CACHE_PROFILE)}")
    print(f"\n  — Japan —")
    print(f"  scraper_cache.json        : {_cache_info(CACHE_SCRAPER)}")
    print(f"  score_cache.json          : {_cache_info(CACHE_SCORE)}")
    print(f"\n  — China —")
    print(f"  scraper_cache_china.json  : {_cache_info(CACHE_SCRAPER_CHINA)}")
    print(f"  score_cache_china.json    : {_cache_info(CACHE_SCORE_CHINA)}")

    if os.path.isfile(CACHE_SCORE):
        with open(CACHE_SCORE, 'r', encoding='utf-8') as f:
            score_data = json.load(f)
        approved = [v for v in score_data.values() if not v.get('excluded') and v.get('score', 0) >= MIN_SCORE]
        no_email = [v for v in approved if not v.get('email')]
        print(f"\n  Approved professors : {len(approved)}")
        print(f"  Missing email       : {len(no_email)}")

    print(f"\n  Send queue:")
    stats = get_stats()
    if stats:
        for status, count in stats.items():
            print(f"    {status:<15} {count}")
    else:
        print("    (empty)")


def cmd_report(args):
    if not os.path.isfile(CACHE_SCORE):
        print("No score cache found. Run `python discoverer.py run` first.")
        return

    with open(CACHE_SCORE, 'r', encoding='utf-8') as f:
        score_data = json.load(f)

    approved = sorted(
        [v for v in score_data.values() if not v.get('excluded') and v.get('score', 0) >= MIN_SCORE],
        key=lambda x: x.get('score', 0),
        reverse=True,
    )

    if not approved:
        print(f"No professors scored ≥ {MIN_SCORE} yet.")
        return

    print(f"\n{'─'*72}")
    print(f"  Approved Professors  ({len(approved)} total, score ≥ {MIN_SCORE})")
    print(f"{'─'*72}")
    for p in approved:
        email_str = p.get('email') or '⚠ NO EMAIL'
        print(f"\n  [{p.get('score', '?')}/10]  {p.get('name', '?')}  <{email_str}>")
        print(f"           {p.get('university', '')} — {p.get('department', '')}")
        print(f"           {p.get('lab_url', '')}")
        print(f"  focus_en: {p.get('focus_en', '')}")
        print(f"  focus_ja: {p.get('focus_ja', '')}")
        if p.get('reason'):
            print(f"  reason  : {p['reason']}")
    print(f"\n{'─'*72}")

    no_email = [p for p in approved if not p.get('email')]
    if no_email:
        print(f"\n  ⚠  {len(no_email)} professor(s) have no email found. "
              f"You can add them manually via:\n"
              f"  python mext_sender.py import professors.csv")


def cmd_clear_cache(args):
    country = getattr(args, 'country', 'all')  # default: clear the specified country's caches

    # Determine which caches to clear
    caches_to_check = []
    if country in ('japan', 'all'):
        caches_to_check += [CACHE_SCRAPER, CACHE_SCORE]
    if country in ('china', 'all'):
        caches_to_check += [CACHE_SCRAPER_CHINA, CACHE_SCORE_CHINA]
    if args.all:  # --all also clears profile
        caches_to_check.append(CACHE_PROFILE)

    removed = []
    for path in caches_to_check:
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)

    if removed:
        print(f"Cleared: {', '.join(removed)}")
    else:
        print("Nothing to clear.")
    if not args.all and os.path.isfile(CACHE_PROFILE):
        print("  (profile_cache.json kept. Use --all to also clear it.)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Automated MEXT professor discovery pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  run          [--dry-run] [--refresh-profile]
               [--all-universities] [--country japan|china|all]
                                    Run the full discovery pipeline
  status                              Show cache and queue status
  report                              Print scored professors from cache
  clear-cache  [--all]               Delete scraper + score caches
                                      (--all also clears profile cache)
""")
    sub = parser.add_subparsers(dest='command', required=True)

    # run
    p_run = sub.add_parser('run', help='Run the full discovery pipeline')
    p_run.add_argument('--dry-run', action='store_true',
                       help='Score and report without importing into the DB')
    p_run.add_argument('--refresh-profile', action='store_true',
                       help='Re-extract profile from CV ignoring cache')
    p_run.add_argument('--all-universities', action='store_true',
                       help='Search all universities, not just MEXT target list')
    p_run.add_argument('--country', choices=['japan', 'china', 'all'], default='japan',
                       help='Target country: japan (default), china, or all')

    # status
    sub.add_parser('status', help='Show pipeline cache and queue status')

    # report
    sub.add_parser('report', help='Print scored and approved professors')

    # clear-cache
    p_clear = sub.add_parser('clear-cache', help='Delete pipeline caches')
    p_clear.add_argument('--all', action='store_true',
                         help='Also clear the profile cache')
    p_clear.add_argument('--country', choices=['japan', 'china', 'all'],
                         default='all', help='Which country caches to clear (default: all)')

    args = parser.parse_args()

    dispatch = {
        'run':         cmd_run,
        'status':      cmd_status,
        'report':      cmd_report,
        'clear-cache': cmd_clear_cache,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
