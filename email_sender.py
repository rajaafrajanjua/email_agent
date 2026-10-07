import smtplib
import os
import yaml
import html as html_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import mimetypes
import urllib.request

# ── load .env manually (no extra dependency) ─────────────────────────────────
if os.path.exists('.env'):
    with open('.env', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)


# ── pre-flight checks ─────────────────────────────────────────────────────────

def check_portfolio_reachable(url: str) -> bool:
    """Return True if the portfolio/resume URL responds with HTTP 2xx."""
    try:
        req = urllib.request.Request(url, method='HEAD',
                                     headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False

def preflight_checks(warn_only: bool = False):
    """
    Verify key configuration before a send run:
      - GMAIL credentials present
      - resume_link reachable
      - attachments folder not empty (warn)
    Returns True if all hard checks pass, False otherwise.
    """
    ok = True

    gmail_user = os.environ.get('GMAIL_ADDRESS')
    gmail_password = os.environ.get('GMAIL_APP_PASSWORD')
    if not gmail_user or not gmail_password:
        print("❌  GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set in environment / .env")
        ok = False

    resume_url = config.get('resume_link', '')
    if resume_url:
        print(f"🔗  Checking portfolio URL: {resume_url} ...", end=' ', flush=True)
        if check_portfolio_reachable(resume_url):
            print("OK")
        else:
            print("UNREACHABLE")
            if not warn_only:
                print("❌  Portfolio URL is unreachable. Fix it or set warn_only in config before sending.")
                ok = False
            else:
                print("⚠️   Portfolio URL is unreachable — proceeding anyway (warn_only=true).")
    else:
        print("⚠️   No resume_link set in config.yaml")

    attach_dir = 'attachments'
    if os.path.isdir(attach_dir):
        files = [f for f in os.listdir(attach_dir) if os.path.isfile(os.path.join(attach_dir, f))]
        if files:
            print(f"📎  Attachments found: {', '.join(files)}")
        else:
            print("⚠️   attachments/ folder exists but is empty — emails will be sent without attachments.")
    else:
        print("⚠️   attachments/ folder not found — emails will be sent without attachments.")

    return ok


def _format_focus(focus_en: str, focus_ja: str) -> tuple[str, str]:
    """
    If focus_en looks like a keyword list (no verb, ends without period),
    wrap it in a natural sentence. If it's already a full sentence, use as-is.
    """
    fe = focus_en.strip()
    fj = focus_ja.strip()

    # Detect keyword list: short, comma-separated, no sentence verb
    is_keyword_list = (
        ',' in fe and
        len(fe) < 120 and
        not fe[0].lower() in ('i', 'my', 'your', 'the', 'this') and
        not fe.endswith('.')
    )

    if is_keyword_list:
        fe = f"Having researched your work on {fe}, I believe my development background aligns with your research vision."
        fj = f"先生の研究室における{fj}に関する先進的な研究を拝見し、私の開発実績が先生のビジョンと深く合致していると確信しております。"

    return fe, fj

def render_email(prof, is_followup: bool = False) -> str:
    """Render the plain-text body for a professor record."""
    template_file = 'followup_template.txt' if is_followup else 'template.txt'
    with open(template_file, 'r', encoding='utf-8') as f:
        template = f.read()

    last_name = prof['name'].split()[-1] if ' ' in prof['name'] else prof['name']

    has_attachments = (
        os.path.isdir('attachments') and
        any(os.path.isfile(os.path.join('attachments', f)) for f in os.listdir('attachments'))
    )
    attachment_text = (
        "I have attached my Academic CV, Transcripts, and an initial Master's Research Outline "
        "to this email for your review.\n"
        "ご検討いただけるよう、本メールに履歴書（CV）、成績証明書、および修士研究計画書の概要を添付いたしました。\n"
    ) if has_attachments else ""

    focus_en, focus_ja = _format_focus(prof['focus_en'], prof['focus_ja'])

    body = template.format(
        last=last_name,
        university=prof['university'],
        focus_en=focus_en,
        focus_ja=focus_ja,
        attachment_text=attachment_text,
        resume_link=config['resume_link'],
    )
    return body


def _plain_to_html(plain: str) -> str:
    """Convert plain-text email body to a minimal, clean HTML version."""
    lines = plain.splitlines()
    html_lines = []
    for line in lines:
        escaped = html_lib.escape(line)
        if escaped.strip() == '':
            html_lines.append('<br>')
        else:
            html_lines.append(f'<p style="margin:0 0 4px 0">{escaped}</p>')

    body_content = '\n'.join(html_lines)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      font-family: Arial, sans-serif;
      font-size: 14px;
      line-height: 1.7;
      color: #222;
      max-width: 680px;
      margin: 0 auto;
      padding: 24px 16px;
    }}
    a {{ color: #1a73e8; }}
    p {{ margin: 0 0 4px 0; }}
  </style>
</head>
<body>
{body_content}
</body>
</html>"""


# ── sender ────────────────────────────────────────────────────────────────────

def send_email(prof, body: str, is_followup: bool = False):
    gmail_user = os.environ.get('GMAIL_ADDRESS')
    gmail_password = os.environ.get('GMAIL_APP_PASSWORD')

    if not gmail_user or not gmail_password:
        raise ValueError("GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set")

    subject = config['subject']
    if is_followup:
        subject = "Re: " + subject  # thread-friendly follow-up subject

    # Build multipart/alternative (plain + HTML)
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = f"{config['sender_name']} <{gmail_user}>"
    msg['To'] = prof['email']

    alt_part = MIMEMultipart('alternative')
    alt_part.attach(MIMEText(body, 'plain', 'utf-8'))
    alt_part.attach(MIMEText(_plain_to_html(body), 'html', 'utf-8'))
    msg.attach(alt_part)

    # Attach files
    if os.path.isdir('attachments'):
        for filename in sorted(os.listdir('attachments')):
            filepath = os.path.join('attachments', filename)
            if not os.path.isfile(filepath):
                continue
            ctype, encoding = mimetypes.guess_type(filepath)
            if ctype is None or encoding is not None:
                ctype = 'application/octet-stream'
            maintype, subtype = ctype.split('/', 1)

            with open(filepath, 'rb') as f:
                part = MIMEBase(maintype, subtype)
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(part)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise Exception(f"SMTP Authentication Error: {e}")
    except Exception as e:
        if 'rate limit' in str(e).lower() or '421' in str(e):
            raise Exception(f"Rate Limit Error: {e}")
        raise
