"""
email_verifier.py — standalone email verification module.

Checks email addresses via:
  1. Format validation (regex)
  2. DNS MX lookup (dnspython)
  3. SMTP RCPT probe (port 25)

Results are cached to verify_cache.json with a 30-day TTL.
"""

import re
import json
import os
import smtplib
import socket
import datetime
from pathlib import Path

import dns.resolver
from dotenv import load_dotenv

load_dotenv()

CACHE_PATH = Path(__file__).parent / 'verify_cache.json'
CACHE_TTL_DAYS = 30
SMTP_TIMEOUT = 10

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

_cache: dict = {}


def _load_cache() -> dict:
    """Load the verification cache from disk. Returns {} on any error."""
    try:
        if CACHE_PATH.exists():
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    """Persist the cache dict to CACHE_PATH."""
    try:
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_sender() -> str:
    """Return the sender address to use in SMTP probes."""
    return os.getenv('GMAIL_ADDRESS', 'verify@mext-check.local')


def verify_email(email: str, sender: str = None) -> dict:
    """
    Verify whether an email address is deliverable.

    Returns a dict with keys:
      - email (str): the original address
      - valid (bool): True if deliverable or unverifiable, False if definitely invalid
      - reason (str): 'ok' | 'unverifiable' | 'invalid_format' | 'no_mx' | 'smtp_reject'
      - detail (str): human-readable explanation
      - checked_at (str): ISO 8601 UTC timestamp (absent on cache-miss shortcircuit)
    """
    global _cache

    normalised = email.strip().lower()

    # Load cache on first use
    if not _cache:
        _cache = _load_cache()

    # Return cached result if it is still within the TTL
    if normalised in _cache:
        entry = _cache[normalised]
        try:
            checked_at = datetime.datetime.fromisoformat(entry['checked_at'])
            age = datetime.datetime.utcnow() - checked_at
            if age.days < CACHE_TTL_DAYS:
                return entry
        except Exception:
            pass  # bad cached entry — re-verify

    # ── Step 1: format check ──────────────────────────────────────────────────
    if not _EMAIL_RE.match(normalised):
        result = {
            'email': email,
            'valid': False,
            'reason': 'invalid_format',
            'detail': 'Email format invalid',
            'checked_at': datetime.datetime.utcnow().isoformat(),
        }
        _cache[normalised] = result
        _save_cache(_cache)
        return result

    # ── Step 2: DNS MX lookup ─────────────────────────────────────────────────
    domain = normalised.split('@')[1]
    mx_host = None
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        # Pick the record with lowest preference value
        best = sorted(answers, key=lambda r: r.preference)[0]
        mx_host = str(best.exchange).rstrip('.')
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.resolver.Timeout,
    ):
        result = {
            'email': email,
            'valid': False,
            'reason': 'no_mx',
            'detail': f'No MX record for {domain}',
            'checked_at': datetime.datetime.utcnow().isoformat(),
        }
        _cache[normalised] = result
        _save_cache(_cache)
        return result

    # ── Step 3: SMTP RCPT probe ───────────────────────────────────────────────
    effective_sender = sender or _get_sender()
    result = None

    try:
        smtp = smtplib.SMTP(timeout=SMTP_TIMEOUT)
        smtp.connect(mx_host, 25)
        smtp.ehlo()
        smtp.mail(effective_sender)
        code, _ = smtp.rcpt(email)
        try:
            smtp.quit()
        except Exception:
            pass

        if code in (250, 251):
            result = {
                'email': email,
                'valid': True,
                'reason': 'ok',
                'detail': f'SMTP accepted (code {code})',
            }
        elif code in (550, 551, 552, 553):
            result = {
                'email': email,
                'valid': False,
                'reason': 'smtp_reject',
                'detail': f'SMTP rejected with code {code}',
            }
        else:
            # 421, 450, 451, 452 and any unexpected code → treat as unverifiable
            result = {
                'email': email,
                'valid': True,
                'reason': 'unverifiable',
                'detail': f'SMTP returned transient/unknown code {code}',
            }

    except (socket.timeout, ConnectionRefusedError, OSError):
        result = {
            'email': email,
            'valid': True,
            'reason': 'unverifiable',
            'detail': 'SMTP probe blocked or timed out',
        }
    except Exception as e:
        result = {
            'email': email,
            'valid': True,
            'reason': 'unverifiable',
            'detail': str(e),
        }

    result['checked_at'] = datetime.datetime.utcnow().isoformat()
    _cache[normalised] = result
    _save_cache(_cache)
    return result
