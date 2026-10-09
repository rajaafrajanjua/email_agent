import argparse
import csv
import re
import sys
import os
import sqlite3

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import yaml
import time
import random
import datetime
import pytz

from database import (
    add_professor, get_pending, update_status, get_stats,
    get_sent_today, increment_fail, check_identical_focus,
    get_sent_awaiting_reply, export_all, get_connection,
)
from email_sender import render_email, send_email, preflight_checks

with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

FOLLOWUP_AFTER_DAYS = config.get('followup_after_days', 14)


# ── helpers ───────────────────────────────────────────────────────────────────

def is_valid_email(email: str) -> bool:
    return bool(re.match(r"[^@]+@[^@]+\.[^@]+", email))

def can_send_now() -> bool:
    tz = pytz.timezone(config['sending_window']['timezone'])
    now = datetime.datetime.now(tz)
    start_t = datetime.datetime.strptime(config['sending_window']['start'], '%H:%M').time()
    end_t   = datetime.datetime.strptime(config['sending_window']['end'],   '%H:%M').time()
    return start_t <= now.time() <= end_t

def _send_loop(items, is_followup: bool = False):
    """Shared queue-processing loop for initial sends and follow-ups."""
    while items:
        if not can_send_now():
            tz_name = config['sending_window']['timezone']
            print(f"⏸  Outside sending window "
                  f"({config['sending_window']['start']}–{config['sending_window']['end']} {tz_name}). "
                  f"Waiting 5 min...")
            time.sleep(300)
            continue

        sent_today = get_sent_today(config['sending_window']['timezone'])
        if sent_today >= config['daily_cap']:
            print(f"⏸  Daily cap of {config['daily_cap']} reached. Waiting 1 hour...")
            time.sleep(3600)
            continue

        prof = items[0]
        action = "Follow-up" if is_followup else "Sending"
        print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {action} → {prof['email']} ({prof['university']})...")

        try:
            body = render_email(prof, is_followup=is_followup)
            send_email(prof, body, is_followup=is_followup)

            if is_followup:
                update_status(prof['email'], 'followup_sent')
                print(f"  ✓  Follow-up sent to {prof['email']}")
            else:
                update_status(prof['email'], 'sent')
                print(f"  ✓  Sent to {prof['email']}")

            items.pop(0)

            if items:
                delay = random.randint(config['delay_range']['min'], config['delay_range']['max'])
                print(f"  ⏳  Waiting {delay}s before next send...")
                time.sleep(delay)

        except Exception as e:
            print(f"  ✗  Failed: {prof['email']} — {e}")
            if "Authentication Error" in str(e) or "Rate Limit" in str(e):
                print("Critical SMTP error. Stopping.")
                sys.exit(1)

            fail_count = increment_fail(prof['email'])
            if fail_count >= config['max_retries']:
                print(f"  Max retries reached for {prof['email']}. Marking as failed.")
                update_status(prof['email'], 'failed')
                items.pop(0)
            else:
                print(f"  Retry {fail_count}/{config['max_retries']} for {prof['email']}. Waiting 60s...")
                time.sleep(60)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_import(args):
    try:
        with open(args.file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            added = skipped = 0
            for row in reader:
                # Skip header-only rows or rows with missing required fields
                if not row.get('focus_en', '').strip() or \
                   not row.get('focus_ja', '').strip() or \
                   not row.get('source_url', '').strip():
                    print(f"  ⚠  Skipping {row.get('email', '?')}: missing focus or source_url")
                    skipped += 1
                    continue
                if not is_valid_email(row.get('email', '')):
                    print(f"  ⚠  Skipping {row.get('email', '?')}: invalid email")
                    skipped += 1
                    continue
                if not args.skip_verify:
                    from email_verifier import verify_email
                    vr = verify_email(row['email'])
                    if not vr['valid']:
                        print(f"  ✗  INVALID ({vr['reason']}): {row['email']} — {vr['detail']}")
                        skipped += 1
                        continue
                    elif vr['reason'] == 'unverifiable':
                        print(f"  ⚠  Unverifiable (probe blocked): {row['email']} — importing anyway")
                if check_identical_focus(row['focus_en'], row['focus_ja']):
                    print(f"  ⚠  WARNING: Focus text for {row['email']} is identical to an existing entry — ensure it is personalised.")
                if add_professor(row):
                    added += 1
                    print(f"  +  Added: {row['email']} ({row['university']})")
                else:
                    print(f"  –  Duplicate skipped: {row['email']}")
                    skipped += 1
        print(f"\nImport complete. Added: {added}, Skipped/Duplicates: {skipped}")
    except FileNotFoundError:
        print(f"File not found: {args.file}")
    except Exception as e:
        print(f"Error reading CSV: {e}")


def cmd_preview(args):
    pending = get_pending()
    if not pending:
        print("No pending emails to preview.")
        return
    shown = 0
    for prof in pending:
        body = render_email(prof)
        print("=" * 60)
        print(f"To:      {prof['email']}")
        print(f"Name:    {prof['name']}  |  {prof['university']}")
        print(f"Subject: {config['subject']}")
        print("-" * 60)
        print(body)
        shown += 1
        if not args.all and shown >= 1:
            remaining = len(pending) - 1
            if remaining:
                print(f"(+{remaining} more pending. Use --all to see all.)")
            break
    print("=" * 60)


def cmd_send(args):
    if not preflight_checks(warn_only=config.get('warn_only', False)):
        print("\n❌  Pre-flight checks failed. Fix the issues above before sending.")
        sys.exit(1)

    pending = get_pending()
    if not pending:
        print("No pending emails.")
        return

    if not args.confirm:
        print(f"\n{len(pending)} email(s) queued. Preview of the first 3:\n")
        for prof in pending[:3]:
            print(f"  → {prof['email']}  ({prof['university']})")
            print("    " + render_email(prof).splitlines()[0])
        print(f"\nRun with --confirm to start sending.")
        return

    print(f"\n▶  Starting queue processor — {len(pending)} email(s) pending.")
    _send_loop(pending, is_followup=False)
    print("\n✅  Queue processor finished.")


def cmd_followup(args):
    """Send follow-up emails to professors who haven't replied after N days."""
    days = args.days if args.days else FOLLOWUP_AFTER_DAYS
    candidates = get_sent_awaiting_reply(days)

    if not candidates:
        print(f"No follow-ups needed (no sent emails ≥ {days} days old without a reply).")
        return

    print(f"\n{len(candidates)} professor(s) eligible for a follow-up (sent ≥ {days} days ago):\n")
    for p in candidates:
        print(f"  → {p['email']}  ({p['university']})  sent: {p['sent_at'][:10]}")

    if not args.confirm:
        print(f"\nRun with --confirm to send follow-ups.")
        return

    if not preflight_checks(warn_only=config.get('warn_only', False)):
        print("\n❌  Pre-flight checks failed.")
        sys.exit(1)

    _send_loop(candidates, is_followup=True)
    print("\n✅  Follow-up run complete.")


def cmd_status(args):
    stats = get_stats()
    total = sum(stats.values())
    print("\n── Email Queue Status ──────────────────────")
    for status in ['queued', 'sent', 'followup_sent', 'replied', 'failed']:
        count = stats.get(status, 0)
        bar = '█' * min(count, 40)
        print(f"  {status:<15} {count:>4}  {bar}")
    print(f"  {'TOTAL':<15} {total:>4}")
    print("────────────────────────────────────────────")
    window_str = f"{config['sending_window']['start']}–{config['sending_window']['end']} {config['sending_window']['timezone']}"
    if can_send_now():
        print(f"  ✅  Within sending window ({window_str})")
    else:
        print(f"  ⏸  Outside sending window ({window_str})")

    pending_followups = get_sent_awaiting_reply(FOLLOWUP_AFTER_DAYS)
    if pending_followups:
        print(f"  📬  {len(pending_followups)} follow-up(s) ready to send (≥{FOLLOWUP_AFTER_DAYS} days, no reply).")
    print()


def cmd_mark_replied(args):
    update_status(args.email, 'replied')
    print(f"✅  Marked {args.email} as replied.")


def cmd_export(args):
    rows = export_all()
    if not rows:
        print("Database is empty.")
        return
    output_path = args.output if args.output else 'export.csv'
    fieldnames = ['id', 'name', 'email', 'university', 'department',
                  'focus_en', 'focus_ja', 'status', 'fail_count',
                  'added_at', 'sent_at', 'replied_at', 'followup_sent_at',
                  'lab_url', 'source_url']
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f"✅  Exported {len(rows)} rows to {output_path}")


def cmd_verify_queue(args):
    from email_verifier import verify_email
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT email, status FROM queue WHERE status IN ('queued', 'sent')")
    rows = c.fetchall()
    conn.close()

    if not rows:
        print('No queued or sent emails to verify.')
        return

    valid_count = invalid_count = unverifiable_count = 0
    invalid_queued = []

    for row in rows:
        email, status = row['email'], row['status']
        r = verify_email(email)
        if r['valid'] and r['reason'] == 'ok':
            print(f"  ✓  ok:           {email}")
            valid_count += 1
        elif not r['valid']:
            print(f"  ✗  INVALID ({r['reason']}): {email} — {r['detail']}")
            invalid_count += 1
            if status == 'queued':
                invalid_queued.append(email)
        else:  # unverifiable
            print(f"  ⚠  unverifiable: {email}")
            unverifiable_count += 1

    print()
    print('── Verification Summary ─────────────────────')
    print(f'  Valid (deliverable):  {valid_count}')
    print(f'  Invalid (hard-fail):  {invalid_count}')
    print(f'  Unverifiable:         {unverifiable_count}')
    print('─────────────────────────────────────────────')

    if args.fix:
        if invalid_queued:
            for email in invalid_queued:
                update_status(email, 'failed')
            print(f'  Marked {len(invalid_queued)} queued address(es) as failed.')
        else:
            print('  No queued invalid addresses to fix.')
    elif invalid_queued:
        print(f'  ℹ  {len(invalid_queued)} invalid queued address(es) found. Run with --fix to mark them failed.')


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MEXT Outreach Email Sender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  import    <file>          Import professors from CSV
  preview   [--all]         Preview rendered emails (dry run)
  send      [--confirm]     Process the queue and send emails
  followup  [--confirm] [--days N]   Send follow-up to non-repliers
  status                    Show queue statistics
  mark-replied <email>      Mark a professor as replied
  export    [--output file] Dump full status report to CSV
  verify-queue [--fix]      Verify deliverability of queued/sent emails
""")
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_import = subparsers.add_parser('import', help='Import professors from CSV')
    p_import.add_argument('file', help='Path to CSV file')
    p_import.add_argument(
        '--skip-verify', action='store_true',
        help='Skip SMTP email verification (import all format-valid addresses)'
    )

    p_preview = subparsers.add_parser('preview', help='Preview rendered emails (dry run)')
    p_preview.add_argument('--all', action='store_true', help='Preview all pending emails')

    p_send = subparsers.add_parser('send', help='Process the send queue')
    p_send.add_argument('--confirm', action='store_true', help='Start sending after reviewing previews')

    p_followup = subparsers.add_parser('followup', help='Send follow-up emails to non-repliers')
    p_followup.add_argument('--confirm', action='store_true', help='Start sending follow-ups')
    p_followup.add_argument('--days', type=int, default=None,
                            help=f'Days since initial send to qualify (default: {FOLLOWUP_AFTER_DAYS})')

    subparsers.add_parser('status', help='Show queue statistics')

    p_mark = subparsers.add_parser('mark-replied', help='Mark a professor as replied')
    p_mark.add_argument('email', help='Professor email address')

    p_export = subparsers.add_parser('export', help='Export status report as CSV')
    p_export.add_argument('--output', default='export.csv', help='Output file path (default: export.csv)')

    p_vq = subparsers.add_parser('verify-queue',
                                  help='Verify deliverability of queued/sent emails')
    p_vq.add_argument('--fix', action='store_true',
                      help='Mark confirmed-invalid queued addresses as failed')

    args = parser.parse_args()

    dispatch = {
        'import':       cmd_import,
        'preview':      cmd_preview,
        'send':         cmd_send,
        'followup':     cmd_followup,
        'status':       cmd_status,
        'mark-replied': cmd_mark_replied,
        'export':       cmd_export,
        'verify-queue': cmd_verify_queue,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
