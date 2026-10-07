# openai_client.py — compatibility shim
# All modules now use llm_client.py (Groq + Gemini + HuggingFace).
# This file re-exports the same names so old imports keep working.
from llm_client import chat, json_chat, translate_to_japanese, DEFAULT_MODEL
