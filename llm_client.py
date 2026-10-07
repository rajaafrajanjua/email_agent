"""
llm_client.py
-------------
4-provider LLM router with per-task fallback chains.

  OPENROUTER  — nvidia/nemotron-3-ultra-550b-a55b:free (1M ctx)
                Profile extraction, large-context work.

  GROQ        — openai/gpt-oss-20b  (fast, 30 RPM)
                Fit scoring, fast JSON tasks.

  AI/ML API   — meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo
                Japanese translation (high volume, low cost per token).
                Currently blocked (no credits) — falls back automatically.

  GEMINI      — gemini-flash-lite-latest
                Last-resort fallback when all other providers fail.

Task routing:
  profile:     openrouter → groq → gemini
  scoring:     groq → openrouter → aiml → gemini
  translation: aiml → groq → openrouter → gemini
  default:     groq → openrouter → aiml → gemini

Public API (drop-in replacement for previous llm_client.py):
  chat(system, user, ..., task='default')         → str
  json_chat(system, user, ..., task='default')    → dict
  translate_to_japanese(text, retries=2)           → str | None
  TASK_MODELS, DEFAULT_MODEL                        (symbolic compat values)
"""

import io
import json
import os
import re
import sys
import time

# ── load .env ─────────────────────────────────────────────────────────────────
if os.path.exists('.env'):
    with open('.env', 'r', encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())


# ═══════════════════════════════════════════════════════════════════════════════
#  OPENROUTER  (large-context free models)
# ═══════════════════════════════════════════════════════════════════════════════

OPENROUTER_BASE_URL     = 'https://openrouter.ai/api/v1'
OPENROUTER_MODEL        = 'nvidia/nemotron-3-ultra-550b-a55b:free'   # 1M ctx, confirmed
OPENROUTER_MODEL_MEDIUM = 'nvidia/nemotron-3-super-120b-a12b:free'   # 262K ctx fallback
OPENROUTER_HEADERS = {
    'HTTP-Referer': 'https://github.com/mext-outreach',
    'X-Title':      'mext-outreach-tool',
}

try:
    from openai import OpenAI as _OpenAI
    _OPENAI_OK = True
except ImportError:
    _OpenAI = None
    _OPENAI_OK = False

_openrouter_client = None


def _openrouter_client_get():
    global _openrouter_client
    if not _OPENAI_OK:
        raise ImportError("openai not installed. Run: pip install openai")
    key = os.environ.get('OPEN_ROUTER_API_KEY')
    if not key:
        raise ValueError("OPEN_ROUTER_API_KEY not set in .env")
    if _openrouter_client is None:
        _openrouter_client = _OpenAI(
            api_key=key,
            base_url=OPENROUTER_BASE_URL,
            default_headers=OPENROUTER_HEADERS,
            timeout=60.0,
        )
    return _openrouter_client


def _openrouter_chat(system: str, user: str, model: str, temperature: float,
                     max_tokens: int, json_mode: bool, retries: int) -> str:
    client = _openrouter_client_get()
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user',   'content': user},
    ]
    kwargs = dict(model=model, messages=messages,
                  temperature=temperature, max_tokens=max_tokens)
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}

    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if '429' in err or 'rate_limit' in err.lower() or 'quota' in err.lower():
                print(f"  ⚠  OpenRouter rate limit / quota: {e}")
                raise
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠  OpenRouter error (attempt {attempt+1}/{retries}): {e}. "
                      f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════════════════
#  GROQ  (fast JSON, 30 RPM)
# ═══════════════════════════════════════════════════════════════════════════════

GROQ_MODEL       = 'openai/gpt-oss-20b'    # fast, high quota
GROQ_MODEL_HEAVY = 'openai/gpt-oss-120b'   # smarter

try:
    from groq import Groq as _Groq
    _GROQ_OK = True
except ImportError:
    _Groq = None
    _GROQ_OK = False

_groq_client = None


def _groq_client_get():
    global _groq_client
    if not _GROQ_OK:
        raise ImportError("groq not installed. Run: pip install groq")
    key = os.environ.get('GROQ_API_KEY')
    if not key:
        raise ValueError("GROQ_API_KEY not set in .env")
    if _groq_client is None:
        _groq_client = _Groq(api_key=key)
    return _groq_client


def _groq_chat(system: str, user: str, model: str, temperature: float,
               max_tokens: int, json_mode: bool, retries: int) -> str:
    client = _groq_client_get()
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user',   'content': user},
    ]
    kwargs = dict(model=model, messages=messages,
                  temperature=temperature, max_tokens=max_tokens)
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}

    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            # Rate limited — raise immediately so caller can fall back
            if '429' in err or 'rate_limit' in err.lower() or 'quota' in err.lower():
                print(f"  ⚠  Groq rate limit hit. Switching to fallback...")
                raise
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠  Groq error (attempt {attempt+1}/{retries}): {e}. "
                      f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════════════════
#  AI/ML API  (translation — high volume, low cost per token)
# ═══════════════════════════════════════════════════════════════════════════════

AIML_BASE_URL = 'https://api.aimlapi.com/v1'
AIML_MODEL    = 'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo'

_aiml_client = None


def _aiml_client_get():
    global _aiml_client
    if not _OPENAI_OK:
        raise ImportError("openai not installed. Run: pip install openai")
    key = os.environ.get('AI_ML_API_KEY')
    if not key:
        raise ValueError("AI_ML_API_KEY not set in .env")
    if _aiml_client is None:
        _aiml_client = _OpenAI(
            api_key=key,
            base_url=AIML_BASE_URL,
            timeout=45.0,
        )
    return _aiml_client


def _aiml_chat(system: str, user: str, model: str, temperature: float,
               max_tokens: int, json_mode: bool, retries: int) -> str:
    client = _aiml_client_get()
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user',   'content': user},
    ]
    kwargs = dict(model=model, messages=messages,
                  temperature=temperature, max_tokens=max_tokens)
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}

    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if '429' in err or 'rate_limit' in err.lower() or 'quota' in err.lower():
                print(f"  ⚠  AI/ML API rate limit / quota: {e}")
                raise
            if '403' in err or 'insufficient' in err.lower() or 'credit' in err.lower():
                print(f"  ⚠  AI/ML API billing blocked (403): {e}")
                raise
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠  AI/ML API error (attempt {attempt+1}/{retries}): {e}. "
                      f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════════════════
#  GEMINI  (last-resort fallback — gemini-flash-lite-latest)
# ═══════════════════════════════════════════════════════════════════════════════

GEMINI_MODEL = 'gemini-flash-lite-latest'

try:
    from google import genai as _genai
    from google.genai import types as _gtypes
    _GEMINI_OK = True
except ImportError:
    _genai = None
    _gtypes = None
    _GEMINI_OK = False

_gemini_client = None


def _gemini_client_get():
    global _gemini_client
    if not _GEMINI_OK:
        raise ImportError("google-genai not installed. Run: pip install google-genai")
    key = (os.environ.get('API_KEY') or
           os.environ.get('GEMINI_API_KEY') or
           os.environ.get('GOOGLE_API_KEY'))
    if not key:
        raise ValueError("No Gemini API key in .env (API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY)")
    if _gemini_client is None:
        _gemini_client = _genai.Client(api_key=key)
    return _gemini_client


def _gemini_safe_text(resp) -> str:
    try:
        parts = resp.candidates[0].content.parts or []
        texts = [p.text for p in parts
                 if hasattr(p, 'text') and p.text and not getattr(p, 'thought', False)]
        if texts:
            return ''.join(texts).strip()
    except Exception:
        pass
    return (resp.text or '').strip()


def _gemini_call(prompt: str, max_tokens: int, json_mode: bool) -> str:
    client = _gemini_client_get()
    cfg_kwargs = dict(temperature=0.2, max_output_tokens=max_tokens)
    if json_mode:
        cfg_kwargs['response_mime_type'] = 'application/json'
    cfg = _gtypes.GenerateContentConfig(**cfg_kwargs)

    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt, config=cfg)
    finally:
        sys.stderr = old_stderr
    return _gemini_safe_text(resp)


def _gemini_chat(system: str, user: str, max_tokens: int,
                 json_mode: bool, retries: int) -> str:
    prompt = f"{system}\n\n---\n\n{user}"
    for attempt in range(retries):
        try:
            return _gemini_call(prompt, max_tokens, json_mode)
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠  Gemini fallback error (attempt {attempt+1}): {e}. "
                      f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ═══════════════════════════════════════════════════════════════════════════════
#  TASK ROUTING
# ═══════════════════════════════════════════════════════════════════════════════

TASK_ROUTES = {
    'profile':     ['openrouter', 'groq', 'gemini'],
    'scoring':     ['groq', 'openrouter', 'aiml', 'gemini'],
    'translation': ['aiml', 'groq', 'openrouter', 'gemini'],
    'default':     ['groq', 'openrouter', 'aiml', 'gemini'],
}

# Symbolic model names for backward compat — callers may pass these as `model=`
# Routing always goes through TASK_ROUTES (keyed by `task=`), not these strings.
TASK_MODELS = {
    'profile':  'openrouter-default',
    'scoring':  'groq-fast',
    'default':  'groq-fast',
}

DEFAULT_MODEL = 'groq-fast'

# Map symbolic model strings back to task names so callers that pass
# model=TASK_MODELS['profile'] still get the right route.
_SYMBOLIC_MODEL_TO_TASK = {
    'openrouter-default': 'profile',
    'groq-fast':          'scoring',
}


def _resolve_task(model: str | None, task: str) -> str:
    """If task is still 'default' but model is a known symbolic string, upgrade task."""
    if task == 'default' and model and model in _SYMBOLIC_MODEL_TO_TASK:
        return _SYMBOLIC_MODEL_TO_TASK[model]
    return task


def _call_provider(provider: str, system: str, user: str, temperature: float,
                   max_tokens: int, json_mode: bool, retries: int) -> str:
    """Dispatch a single provider call. Raises on failure."""
    if provider == 'openrouter':
        return _openrouter_chat(system, user, OPENROUTER_MODEL, temperature,
                                max_tokens, json_mode, retries)
    elif provider == 'groq':
        model = GROQ_MODEL
        return _groq_chat(system, user, model, temperature,
                          max_tokens, json_mode, retries)
    elif provider == 'aiml':
        return _aiml_chat(system, user, AIML_MODEL, temperature,
                          max_tokens, json_mode, retries)
    elif provider == 'gemini':
        return _gemini_chat(system, user, max_tokens, json_mode, retries)
    else:
        raise ValueError(f"Unknown provider: {provider!r}")


def _route_call(task: str, system: str, user: str, temperature: float,
                max_tokens: int, json_mode: bool, retries: int) -> str:
    """Try providers in task order; raise last exception if all fail."""
    route = TASK_ROUTES.get(task, TASK_ROUTES['default'])
    last_exc: Exception | None = None

    for provider in route:
        try:
            result = _call_provider(provider, system, user, temperature,
                                    max_tokens, json_mode, retries)
            return result
        except Exception as e:
            print(f"  ↩  Provider '{provider}' failed ({type(e).__name__}: {e}). "
                  f"Trying next in route...")
            last_exc = e

    raise RuntimeError(
        f"All providers failed for task '{task}'. "
        f"Last error: {last_exc}"
    ) from last_exc


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$',          '', text, flags=re.MULTILINE)
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

def chat(
    system: str,
    user: str,
    model: str = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    retries: int = 3,
    task: str = 'default',
) -> str:
    """
    Route a chat request through the provider chain for `task`.

    `model` is accepted for backward compatibility but routing is always
    determined by `task`.  Callers that pass model=TASK_MODELS['profile']
    are automatically mapped to task='profile'.
    """
    resolved_task = _resolve_task(model, task)
    return _route_call(resolved_task, system, user, temperature,
                       max_tokens, json_mode=False, retries=retries)


def json_chat(
    system: str,
    user: str,
    model: str = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    retries: int = 3,
    task: str = 'default',
) -> dict:
    """
    Route a JSON chat request and parse the response.

    Falls back across providers automatically.  On JSON parse failure within
    a provider's response the next provider is tried before giving up.
    """
    resolved_task = _resolve_task(model, task)
    route = TASK_ROUTES.get(resolved_task, TASK_ROUTES['default'])
    last_exc: Exception | None = None
    last_raw = ''

    for provider in route:
        try:
            raw = _call_provider(provider, system, user, temperature,
                                 max_tokens, json_mode=True, retries=retries)
            last_raw = raw
            return json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            print(f"  ⚠  Provider '{provider}' returned non-JSON: {e}. "
                  f"Trying next in route...")
            last_exc = e
        except Exception as e:
            print(f"  ↩  Provider '{provider}' failed ({type(e).__name__}: {e}). "
                  f"Trying next in route...")
            last_exc = e

    raise ValueError(
        f"All providers failed for JSON task '{resolved_task}'. "
        f"Last raw response:\n{last_raw}\nLast error: {last_exc}"
    )


def translate_to_japanese(text: str, retries: int = 2) -> str | None:
    """
    Translate English text to academic Japanese.

    Route: AI/ML API → Groq → OpenRouter → Gemini.
    Returns None on complete failure; caller should fall back to English.
    """
    system = (
        "You are a professional Japanese academic translator. "
        "Translate the following English text to natural academic Japanese. "
        "Return ONLY the Japanese translation — no explanation, no romanisation, "
        "no extra text."
    )
    try:
        return _route_call(
            task='translation',
            system=system,
            user=text,
            temperature=0.1,
            max_tokens=256,
            json_mode=False,
            retries=retries,
        )
    except Exception as e:
        print(f"  ⚠  All translation providers failed: {e}")
        return None


# ── backward-compat alias (old modules import from openai_client) ─────────────
# openai_client.py re-exports DEFAULT_MODEL — keep it defined.


# ── self-test ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("  LLM Client — OpenRouter + Groq + AI/ML API + Gemini")
    print("=" * 60)

    print("\n[1] chat() — default task (Groq primary)...")
    r = chat(system="Reply with exactly: OK", user="Say it.", max_tokens=20)
    print(f"    → {r!r}")

    print("\n[2] json_chat() — scoring task (Groq primary)...")
    d = json_chat(system='Return JSON only.',
                  user='Return {"provider":"groq","ok":true}',
                  task='scoring', max_tokens=50)
    print(f"    → {d}")

    print("\n[3] chat() — profile task (OpenRouter primary)...")
    r2 = chat(system="Reply with exactly: PROFILE OK",
              user="Say it.", task='profile', max_tokens=20)
    print(f"    → {r2!r}")

    print("\n[4] translate_to_japanese()...")
    ja = translate_to_japanese(
        "Federated Learning for Mobile Edge Computing Applications")
    print(f"    → {ja or '(failed)'}")

    print("\n✅  Done.")
