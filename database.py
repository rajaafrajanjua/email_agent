import sqlite3
import datetime
import os
import pytz

DB_PATH = "professors.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            university TEXT,
            department TEXT,
            lab_url TEXT,
            focus_en TEXT,
            focus_ja TEXT,
            source_url TEXT,
            status TEXT DEFAULT 'queued',
            fail_count INTEGER DEFAULT 0,
            added_at TEXT,
            sent_at TEXT,
            replied_at TEXT,
            followup_sent_at TEXT
        )
    ''')
    # Migrate existing DBs that don't have the new columns yet
    for col, coldef in [('replied_at', 'TEXT'), ('followup_sent_at', 'TEXT')]:
        try:
            c.execute(f'ALTER TABLE queue ADD COLUMN {col} {coldef}')
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()

def add_professor(data):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO queue (
                name, email, university, department, lab_url,
                focus_en, focus_ja, source_url, status, added_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
        ''', (
            data['name'], data['email'], data['university'], data['department'],
            data['lab_url'], data['focus_en'], data['focus_ja'], data['source_url'],
            datetime.datetime.now(datetime.timezone.utc).isoformat()
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_pending():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM queue WHERE status = 'queued'")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_sent_awaiting_reply(days_since: int):
    """Return professors sent to >= days_since days ago with no reply and no follow-up yet."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_since)).isoformat()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM queue
        WHERE status = 'sent'
          AND followup_sent_at IS NULL
          AND sent_at <= ?
    """, (cutoff,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_status(email, status):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if status == 'sent':
        c.execute("UPDATE queue SET status = ?, sent_at = ? WHERE email = ?", (status, now, email))
    elif status == 'replied':
        c.execute("UPDATE queue SET status = ?, replied_at = ? WHERE email = ?", (status, now, email))
    elif status == 'followup_sent':
        c.execute("UPDATE queue SET followup_sent_at = ? WHERE email = ?", (now, email))
    else:
        c.execute("UPDATE queue SET status = ? WHERE email = ?", (status, email))
    conn.commit()
    conn.close()

def increment_fail(email):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE queue SET fail_count = fail_count + 1 WHERE email = ?", (email,))
    conn.commit()
    c.execute("SELECT fail_count FROM queue WHERE email = ?", (email,))
    fail_count = c.fetchone()[0]
    conn.close()
    return fail_count

def get_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT status, COUNT(*) FROM queue GROUP BY status")
    stats = dict(c.fetchall())
    conn.close()
    return stats

def get_sent_today(timezone_str):
    """Count emails sent since midnight in the given timezone (UTC-normalized comparison)."""
    tz = pytz.timezone(timezone_str)
    now_local = datetime.datetime.now(tz)
    # midnight local → UTC ISO string
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_local.astimezone(pytz.utc)
    cutoff = midnight_utc.strftime('%Y-%m-%dT%H:%M:%S')

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM queue WHERE status IN ('sent','followup_sent') AND sent_at >= ?", (cutoff,))
    count = c.fetchone()[0]
    conn.close()
    return count

def check_identical_focus(focus_en, focus_ja):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM queue WHERE focus_en = ? OR focus_ja = ?", (focus_en, focus_ja))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def export_all():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM queue ORDER BY status, added_at")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

init_db()
