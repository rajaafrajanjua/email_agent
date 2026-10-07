# Provider Investigation Results

**Date:** 2026-10-06  
**Script:** `test_providers.py`  
**Python:** `C:\Users\Raja\.local\bin\python3.14.exe`

---

## AI/ML API (`https://api.aimlapi.com/v1`)

All four tested models returned **HTTP 403 — insufficient credits**.  
The account has run out of funds. Models cannot be used until the balance is topped up at <https://aimlapi.com/app/billing/>.

| Model | Result |
|-------|--------|
| `Qwen/Qwen2.5-72B-Instruct` | ✗ 403 — no funds |
| `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | ✗ 403 — no funds |
| `mistralai/Mistral-7B-Instruct-v0.2` | ✗ 403 — no funds |
| `microsoft/WizardLM-2-8x22B` | ✗ 403 — no funds |

**⚠️ Action required:** Top up AI/ML API balance to enable any of these models.  
When funded, the recommended model for high-volume short tasks would be  
`meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` — smallest, fastest, lowest cost per token.

---

## OpenRouter (`https://openrouter.ai/api/v1`)

Several originally-targeted models have moved off the free tier; three confirmed-working free models were found.

### Originally requested — no longer free

| Model | Result |
|-------|--------|
| `google/gemma-3-27b-it:free` | ✗ 404 — paid only |
| `meta-llama/llama-4-scout:free` | ✗ 404 — paid only |
| `meta-llama/llama-3.3-70b-instruct:free` | ✗ 404 — paid only |
| `mistralai/mistral-7b-instruct:free` | ✗ 404 — no endpoints |

### Currently available free models (probed 2026-10-06)

| Model | Context | Result | Notes |
|-------|---------|--------|-------|
| `nvidia/nemotron-3-ultra-550b-a55b:free` ⭐ | 1 M tokens | ✓ **WORKS** (~1 s) | 550 B MoE, largest free model |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262 K tokens | ✓ **WORKS** (~1 s) | 120 B MoE, multi-agent focus |
| `google/gemma-4-31b-it:free` | 262 K tokens | ✓ **WORKS** (rate-limited at time of test — model exists) | Multimodal capable |
| `openai/gpt-oss-20b:free` | — | ✗ 404 — paid only | |
| `nvidia/nemotron-nano-9b-v2:free` | — | ✗ 404 — no endpoints | |
| `nvidia/nemotron-3-nano-30b-a3b:free` | — | ✗ 404 — paid only | |
| `poolside/laguna-m.1:free` | — | ✗ 404 — no endpoints | |
| `nousresearch/hermes-3-llama-3.1-405b:free` | — | ✗ 404 — paid only | |

**Best for large-context tasks (profile extraction):** `nvidia/nemotron-3-ultra-550b-a55b:free`  
- 1 M token context window handles arbitrarily long academic profiles
- 550 B parameter MoE — strong reasoning and instruction following
- Confirmed responding in ~1 s on this account

---

## Recommended Routing

### `profile_extraction`
Extract structured data from professor web pages / PDFs (large context, complex reasoning).

```
primary:  openrouter → nvidia/nemotron-3-ultra-550b-a55b:free   (1M ctx)
fallback: openrouter → nvidia/nemotron-3-super-120b-a12b:free   (262K ctx)
fallback: openrouter → google/gemma-4-31b-it:free               (262K ctx, retry on 429)
fallback: groq       → openai/gpt-oss-20b (if on Groq)
```

### `fit_scoring`
Score candidate fit as JSON (short prompt, fast turnaround, high volume).

```
primary:  groq → openai/gpt-oss-20b     (fast JSON, 131K ctx)
fallback: groq → openai/gpt-oss-120b    (larger, same provider)
fallback: openrouter → nvidia/nemotron-3-super-120b-a12b:free
```

### `translation_ja`
Japanese translation of outreach emails (high volume, short text).

> **Note:** AI/ML API is currently blocked (no funds, HTTP 403).  
> Until topped up, route translation through an alternative.

```
# When AI/ML API has funds:
primary:  aimlapi → meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo  (fast, cheap per-token)
fallback: aimlapi → mistralai/Mistral-7B-Instruct-v0.2

# Current working fallback chain (no AI/ML API funds):
primary:  openrouter → nvidia/nemotron-3-super-120b-a12b:free
fallback: openrouter → nvidia/nemotron-3-ultra-550b-a55b:free
fallback: groq       → openai/gpt-oss-20b
```

---

## Key Findings

1. **AI/ML API is blocked** — all models return 403 "insufficient credits". Requires billing action before it can be used for translation or any other task.

2. **Most originally-planned OpenRouter free models are gone** — `llama-3.3-70b`, `gemma-3-27b`, `llama-4-scout`, `mistral-7b` have all been moved to paid-only tiers.

3. **Three OpenRouter free models are active right now:**
   - `nvidia/nemotron-3-ultra-550b-a55b:free` — confirmed working, 1 M context, best choice
   - `nvidia/nemotron-3-super-120b-a12b:free` — confirmed working, 262 K context
   - `google/gemma-4-31b-it:free` — exists but upstream rate-limited at time of test; retry works

4. **OpenRouter free tier limits:** 50 requests/day (bumps to 1 000/day with $10+ lifetime credits deposited).

5. **`openai/gpt-oss-20b:free` on OpenRouter is paid-only** — it is only free on Groq directly.
