"""
scorer.py
---------
Takes raw professor candidates from scraper.py and uses OpenAI to:

1. Score each professor's fit with the applicant (0–10)
2. Generate a personalised focus_en string (English, 1–2 sentences)
3. Generate a personalised focus_ja string (Japanese translation)
4. Decide whether to include them in the send queue (threshold configurable)

Only professors above the score threshold AND with a known email are returned
as final, send-ready dicts compatible with database.add_professor().
"""

import json
import re
from llm_client import json_chat, translate_to_japanese


# ── prompts ───────────────────────────────────────────────────────────────────

_SCORE_SYSTEM = """
You are an expert academic advisor scoring the fit between a prospective
MEXT scholarship applicant and a Japanese university professor.

The applicant is a software engineer from Pakistan applying for an October
2027 Master's intake via the MEXT University Recommendation Track. Their
background is full-stack mobile/web development (Flutter, React Native,
Laravel, React.js) with published production apps. Their research goal is
to transition into AI/ML research, specifically applying deep learning
inside cross-platform software systems.

You will be given:
- The applicant's research interest keywords
- A professor's research interests and recent paper titles/abstracts

Return a JSON object with EXACTLY these keys:

{
  "score": <integer 0-10>,
  "reason": "<one sentence explaining the score>",
  "focus_en": "<1-2 sentences, specific to THIS professor's work, describing
               the research topics you are interested in from their lab.
               Do NOT use generic phrases like 'machine learning'.
               Reference their actual paper topics or lab focus.
               This text will appear verbatim in the outreach email.>",
  "include":  <true if score >= 6 AND the match is genuine, else false>
}

Scoring guide:
  9-10: Direct overlap between applicant's skills and professor's research
  7-8:  Strong thematic alignment (ML × mobile, systems × AI, etc.)
  5-6:  Some overlap; applicant could credibly pivot to this area
  3-4:  Weak overlap; mainly theoretical, no engineering angle
  0-2:  No meaningful connection

IMPORTANT: focus_en must be personalized per professor. Generic text like
"your research in machine learning" scores 0 in our quality check and the
entry will be dropped.

IMPORTANT — two scoring modes:
Case A (recent publications are listed): base score and focus_en on the professor's ACTUAL paper topics. Reference specific paper titles or research themes from the publications. Do not use generic ML/AI phrases — cite what the papers are actually about.
Case B (recent publications section shows '(no publications found)' or is empty): base score and focus_en on the professor's stated research interests instead. Acknowledge that specific publications are not available and frame focus_en around their stated area of work. This is still valid for outreach if there is genuine field overlap — score >= 6 if the applicant's background meaningfully overlaps with the professor's stated interests.
""".strip()


_SCORE_USER_TEMPLATE = """
=== APPLICANT KEYWORDS ===
{keywords}

=== PROFESSOR ===
Name:        {name}
University:  {university}
Department:  {department}
Lab URL:     {lab_url}

Research interests:
{interests}

Recent publications:
{papers}
"""


# ── quality checks ────────────────────────────────────────────────────────────

_GENERIC_PHRASES = [
    'your research in machine learning',
    'your work in artificial intelligence',
    'your research in ai',
    'your laboratory',
    'your research interests',
    'your field',
    'deep learning in general',
]

def _is_focus_generic(focus_en: str) -> bool:
    f = focus_en.lower()
    return (
        len(focus_en.split()) < 10 or
        any(g in f for g in _GENERIC_PHRASES)
    )


def _format_interests(interests: list[str]) -> str:
    return '\n'.join(f'  - {i}' for i in interests) if interests else '  (none listed)'


def _format_papers(papers: list[dict]) -> str:
    if not papers:
        return '  (no publications found)'
    lines = []
    for p in papers[:5]:
        year = f" ({p['year']})" if p.get('year') else ''
        title = p.get('title', '')
        abstract = p.get('abstract', '')
        line = f"  • {title}{year}"
        if abstract:
            line += f"\n    {abstract[:200]}..."
        lines.append(line)
    return '\n'.join(lines)


# ── main scorer ───────────────────────────────────────────────────────────────

def score_professor(prof: dict, applicant_keywords: list[str]) -> dict | None:
    """
    Score a single professor dict.
    Returns an enriched dict with score, focus_en, focus_ja added,
    or None if the professor should be excluded.
    """
    user_msg = _SCORE_USER_TEMPLATE.format(
        keywords    = ', '.join(applicant_keywords),
        name        = prof.get('name', 'Unknown'),
        university  = prof.get('university', ''),
        department  = prof.get('department', ''),
        lab_url     = prof.get('lab_url', ''),
        interests   = _format_interests(prof.get('interests', [])),
        papers      = _format_papers(prof.get('papers', [])),
    )

    try:
        result = json_chat(
            system      = _SCORE_SYSTEM,
            user        = user_msg,
            task        = 'scoring',
            temperature = 0.3,
            max_tokens  = 1024,
        )
    except Exception as e:
        print(f"  ✗  LLM error scoring {prof.get('name')}: {e}")
        return None

    score     = int(result.get('score', 0))
    include   = bool(result.get('include', False))
    focus_en  = result.get('focus_en', '').strip()
    reason    = result.get('reason', '')

    # Quality gates
    if not include or score < 6:
        return None
    if not focus_en:
        return None
    if _is_focus_generic(focus_en):
        print(f"  ⚠  Dropped {prof.get('name')} — focus text is too generic.")
        return None

    # ── Translate focus_en → focus_ja via HuggingFace (free, no LLM quota) ──
    print(f"     🌐  Translating focus text via HuggingFace...")
    focus_ja = translate_to_japanese(focus_en)
    if not focus_ja:
        print(f"  ⚠  Translation failed for {prof.get('name')} — using English as fallback.")
        focus_ja = focus_en

    return {
        **prof,
        'score':    score,
        'reason':   reason,
        'focus_en': focus_en,
        'focus_ja': focus_ja,
    }


def score_professors(
    candidates: list[dict],
    applicant_keywords: list[str],
    min_score: int = 6,
    require_email: bool = False,
    score_cache_path: str = 'score_cache.json',
    field_keywords: 'list[str] | None' = None,
) -> list[dict]:
    """
    Score all candidates and return only those that pass.
    Results are cached by permalink so re-runs don't re-score known entries.

    field_keywords: if provided, skip LLM scoring for professors whose scraped
    content contains none of these terms — fast pre-filter to avoid wasting quota
    on math/physics/chemistry professors.
    """
    import os, yaml

    # Load field_keywords from config if not passed
    if field_keywords is None:
        try:
            with open('config.yaml', 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            field_keywords = cfg.get('discovery', {}).get('field_keywords', [])
        except Exception:
            field_keywords = []

    # Load cache
    cache: dict = {}
    if os.path.isfile(score_cache_path):
        with open(score_cache_path, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"  📦  Loaded score cache ({len(cache)} entries).")

    approved: list[dict] = []

    for idx, prof in enumerate(candidates, 1):
        permalink = prof.get('permalink', prof.get('email', str(idx)))
        name      = prof.get('name', '?')
        univ      = prof.get('university', '?')
        email     = prof.get('email', '')

        if require_email and not email:
            print(f"  –  Skipping {name} ({univ}): no email found.")
            continue

        # Use cached score if available
        if permalink in cache:
            cached = cache[permalink]
            if cached.get('score', 0) >= min_score:
                approved.append(cached)
            continue

        print(f"  🤖  [{idx}/{len(candidates)}] Scoring: {name} ({univ})")

        # ── Field keyword pre-filter ──────────────────────────────────────────
        # Build a text blob from everything we know about this professor
        if field_keywords:
            prof_text = ' '.join([
                name,
                prof.get('department', ''),
                ' '.join(prof.get('interests', [])),
                ' '.join(p.get('title', '') + ' ' + p.get('abstract', '')
                         for p in prof.get('papers', [])),
            ]).lower()
            if not any(kw.lower() in prof_text for kw in field_keywords):
                print(f"  ⏭  {name} — no field keyword match, skipping LLM call.")
                cache[permalink] = {**prof, 'score': 0, 'excluded': True, 'reason': 'no field match'}
                with open(score_cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)
                continue
        scored = score_professor(prof, applicant_keywords)

        # Cache every result (even None → store as score=0 so we don't re-query)
        cache[permalink] = scored if scored else {**prof, 'score': 0, 'excluded': True}
        with open(score_cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

        if scored:
            print(f"  ✅  {name} — score {scored['score']}/10: {scored.get('reason','')}")
            approved.append(scored)
        else:
            print(f"  –   {name} — below threshold or poor fit.")

    # Sort best matches first
    approved.sort(key=lambda x: x.get('score', 0), reverse=True)
    print(f"\n  ✅  Scoring complete: {len(approved)} professors approved out of {len(candidates)} candidates.")
    return approved


def to_db_row(scored_prof: dict) -> dict:
    """
    Convert a scored professor dict into the shape database.add_professor() expects.
    """
    return {
        'name':       scored_prof.get('name', ''),
        'email':      scored_prof.get('email', ''),
        'university': scored_prof.get('university', ''),
        'department': scored_prof.get('department', ''),
        'lab_url':    scored_prof.get('lab_url', ''),
        'focus_en':   scored_prof.get('focus_en', ''),
        'focus_ja':   scored_prof.get('focus_ja', ''),
        'source_url': scored_prof.get('source_url', ''),
    }
