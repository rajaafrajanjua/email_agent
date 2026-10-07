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

CACHE_PROFILE = 'profile_cache.json'
CACHE_SCRAPER = 'scraper_cache.json'
CACHE_SCORE   = 'score_cache.json'


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


def step_scrape(profile: dict, all_universities: bool = False) -> list[dict]:
    _banner("STEP 2 — Discovering professors via university faculty pages")
    candidates = discover_professors(
        applicant_profile        = profile,
        target_universities_only = not all_universities,
        cache_path               = CACHE_SCRAPER,
    )
    return candidates


def step_score(candidates: list[dict], keywords: list[str]) -> list[dict]:
    _banner("STEP 3 — Scoring professor fit with OpenAI")
    approved = score_professors(
        candidates         = candidates,
        applicant_keywords = keywords,
        min_score          = MIN_SCORE,
        require_email      = REQUIRE_EMAIL,
        score_cache_path   = CACHE_SCORE,
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
    print("\n🚀  MEXT Automated Professor Discovery Pipeline")
    print(   "   ==========================================")

    # Step 1 — profile
    profile  = step_profile(refresh=args.refresh_profile)
    keywords = profile['keywords']

    # Step 2 — scrape
    candidates = step_scrape(profile, all_universities=args.all_universities)
    if not candidates:
        print("\n⚠  No candidates found. Check that target university pages are "
              "reachable or run with --all-universities.")
        return

    # Step 3 — score
    approved = step_score(candidates, keywords)
    if not approved:
        print("\n⚠  No professors passed the scoring threshold "
              f"(min_score={MIN_SCORE}). Consider lowering it in config.yaml.")
        return

    # Step 4 — import
    added, skipped = step_import(approved, dry_run=args.dry_run)

    # ── summary ───────────────────────────────────────────────────────────────
    _banner("PIPELINE COMPLETE")
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

    print(f"  profile_cache.json  : {_cache_info(CACHE_PROFILE)}")
    print(f"  scraper_cache.json  : {_cache_info(CACHE_SCRAPER)}")
    print(f"  score_cache.json    : {_cache_info(CACHE_SCORE)}")

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
    removed = []
    for path in [CACHE_PROFILE, CACHE_SCRAPER, CACHE_SCORE]:
        if args.all or path != CACHE_PROFILE:  # keep profile unless --all
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
               [--all-universities]   Run the full discovery pipeline
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

    # status
    sub.add_parser('status', help='Show pipeline cache and queue status')

    # report
    sub.add_parser('report', help='Print scored and approved professors')

    # clear-cache
    p_clear = sub.add_parser('clear-cache', help='Delete pipeline caches')
    p_clear.add_argument('--all', action='store_true',
                         help='Also clear the profile cache')

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
