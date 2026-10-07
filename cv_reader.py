"""
cv_reader.py
------------
Reads the user's CV (PDF) and email template, then uses OpenAI to extract
a structured profile of research interests that the scraper uses as search seeds.

Output shape:
{
  "keywords":   ["federated learning", "mobile ML", ...],   # English search terms
  "summary_en": "Two-sentence summary of your background and research goals",
  "summary_ja": "Japanese version of the summary (for self-check)",
  "tech_stack": ["Flutter", "React Native", "Laravel", ...]
}
"""

import os
import json

# ── optional PDF support ──────────────────────────────────────────────────────
try:
    import pdfplumber
    _PDF_OK = True
except ImportError:
    _PDF_OK = False

from llm_client import chat, json_chat, TASK_MODELS


def _load_env():
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()


# ── text extractors ───────────────────────────────────────────────────────────

def extract_pdf_text(path: str) -> str:
    """Extract raw text from a PDF file using pdfplumber."""
    if not _PDF_OK:
        raise ImportError(
            "pdfplumber is not installed. Run: pip install pdfplumber\n"
            "Or place a plain-text version of your CV as 'cv.txt' instead."
        )
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return '\n'.join(text_parts)


def _find_cv(cv_dir: str = 'attachments') -> str | None:
    """
    Look for a CV file in order of preference:
      1. attachments/cv.txt  (plain text, fastest)
      2. attachments/*.pdf   (first match, uses pdfplumber)
      3. cv.txt              (project root fallback)
    """
    candidates = []
    if os.path.isdir(cv_dir):
        txt = os.path.join(cv_dir, 'cv.txt')
        if os.path.isfile(txt):
            return txt
        for f in sorted(os.listdir(cv_dir)):
            if f.lower().endswith('.pdf'):
                candidates.append(os.path.join(cv_dir, f))
    root_txt = 'cv.txt'
    if os.path.isfile(root_txt):
        return root_txt
    return candidates[0] if candidates else None


def load_cv_text(cv_path: str | None = None) -> str:
    path = cv_path or _find_cv()
    if not path:
        raise FileNotFoundError(
            "No CV found. Place your CV PDF inside attachments/ "
            "or create attachments/cv.txt with your CV as plain text."
        )
    if path.lower().endswith('.pdf'):
        print(f"  📄  Extracting text from PDF: {path}")
        return extract_pdf_text(path)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def load_template_text() -> str:
    with open('template.txt', 'r', encoding='utf-8') as f:
        return f.read()


# ── AI profile extraction ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are an expert academic advisor helping a Pakistani software engineer
prepare for MEXT scholarship applications to Japanese graduate schools.
Your task: analyse the applicant's CV and email template and return
a JSON object with EXACTLY these keys:

{
  "keywords": [
    // 8-14 specific English research topic strings the candidate should
    // target. Be precise: not "machine learning" but
    // "on-device federated learning for mobile applications".
    // These will be used as search queries on ResearchMap.jp.
  ],
  "summary_en": "One paragraph (3-4 sentences) summarising the applicant's
                  academic background, professional experience, and research goals.",
  "summary_ja": "Japanese translation of summary_en.",
  "tech_stack": ["list", "of", "technologies", "from", "the", "CV"]
}

Return ONLY the JSON object, no markdown fences, no extra text.
""".strip()


def extract_profile(cv_path: str | None = None, force_refresh: bool = False) -> dict:
    """
    Extract a structured profile dict from the user's CV and email template.
    Result is cached in profile_cache.json to avoid repeated API calls.
    """
    cache_path = 'profile_cache.json'
    if not force_refresh and os.path.isfile(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            profile = json.load(f)
        print(f"  ✅  Loaded cached profile ({len(profile['keywords'])} keywords). "
              f"Use --refresh-profile to re-extract.")
        return profile

    print("  🧠  Extracting profile from CV and email template via OpenAI...")
    cv_text = load_cv_text(cv_path)
    template_text = load_template_text()

    user_content = f"""=== CV TEXT ===
{cv_text[:6000]}

=== EMAIL TEMPLATE (shows research framing) ===
{template_text[:2000]}
"""
    raw_dict = json_chat(
        system=_SYSTEM_PROMPT,
        user=user_content,
        model=TASK_MODELS['profile'],   # Groq gpt-oss-20b → Gemini fallback
        temperature=0.2,
        max_tokens=2048,
    )

    # json_chat already returns a parsed dict — no need to strip/parse
    profile = raw_dict

    # Validate required keys
    for key in ('keywords', 'summary_en', 'summary_ja', 'tech_stack'):
        if key not in profile:
            raise ValueError(f"Profile JSON missing key: {key}")

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"  ✅  Profile extracted: {len(profile['keywords'])} keywords, "
          f"saved to {cache_path}")
    return profile


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Extract research profile from CV')
    p.add_argument('--refresh', action='store_true', help='Force re-extraction ignoring cache')
    p.add_argument('--cv', default=None, help='Explicit path to CV file (PDF or txt)')
    args = p.parse_args()
    profile = extract_profile(cv_path=args.cv, force_refresh=args.refresh)
    print(json.dumps(profile, ensure_ascii=False, indent=2))
