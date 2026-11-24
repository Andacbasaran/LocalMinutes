"""Meeting summarization and Granola-style Note Enhancement with strict Air-Gapped Privacy support."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Sequence

import httpx

from localminutes.export.exporter import format_timestamp
from localminutes.models import (
    AppSettings,
    SummaryResult,
    TranscriptSegment,
    get_template_meta,
)
from localminutes.summarization.local_extractive import (
    enhance_notes_offline,
    extractive_summarize,
)


class SummarizerError(RuntimeError):
    """Raised when LLM summarization fails."""


def _build_system_prompt(template_key: str, lang: str = "en") -> str:
    tmpl = get_template_meta(template_key, lang=lang)
    return (
        "You are an expert meeting & lecture intelligence assistant.\n"
        f"{tmpl['instruction']}\n"
        "You will receive a speaker-labeled transcript and optional user notes. "
        "Base your response strictly on facts present in the transcript and notes.\n\n"
        "Return ONLY a valid JSON object (no markdown fences or commentary):\n"
        "{\n"
        f'  "overview": "{tmpl["overview_title"]} (2-4 concise sentences)",\n'
        f'  "key_points": ["{tmpl["key_points_title"]} item 1", "..."],\n'
        f'  "decisions": ["{tmpl["decisions_title"]} item 1 (or empty list)"],\n'
        f'  "action_items": ["Owner: concrete action item (or empty list)"]\n'
        "}\n"
    )


def build_transcript_prompt(
    segments: Sequence[TranscriptSegment],
    language: str = "English",
    notes: str = "",
) -> str:
    """Format transcript segments and optional user notes into a clean LLM prompt."""
    lines = [
        f"Summarize the following recording in {language} and respond using the required JSON schema.",
        "",
    ]
    if notes.strip():
        lines.append("USER NOTES:")
        lines.append(notes.strip())
        lines.append("")

    bookmarked = [s for s in segments if s.is_bookmarked]
    if bookmarked:
        lines.append("BOOKMARKED MOMENTS:")
        for seg in bookmarked:
            lines.append(f"- [{format_timestamp(seg.start_sec)}] {seg.speaker}: {seg.text.strip()}")
        lines.append("")

    lines.append("TRANSCRIPT:")
    for seg in segments:
        ts = format_timestamp(seg.start_sec)
        star = " [BOOKMARKED]" if seg.is_bookmarked else ""
        lines.append(f"[{ts}] {seg.speaker}{star}: {seg.text.strip()}")
    return "\n".join(lines)


def _extract_json_block(text: str) -> str:
    """Extract JSON payload even if wrapped in markdown fences or prose."""
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _ensure_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def parse_summary_response(
    raw_text: str,
    model_used: str = "",
    template: str = "meeting",
) -> SummaryResult:
    """Parse structured JSON summary response, falling back gracefully to plain overview."""
    now = datetime.now().isoformat(timespec="seconds")
    candidate = _extract_json_block(raw_text)
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return SummaryResult(
                overview=str(data.get("overview", "")).strip(),
                key_points=_ensure_str_list(data.get("key_points")),
                decisions=_ensure_str_list(data.get("decisions")),
                action_items=_ensure_str_list(data.get("action_items")),
                template=template,
                raw_markdown=raw_text.strip(),
                model_used=model_used,
                generated_at=now,
            )
    except json.JSONDecodeError:
        pass

    return SummaryResult(
        overview=raw_text.strip(),
        key_points=[],
        decisions=[],
        action_items=[],
        template=template,
        raw_markdown=raw_text.strip(),
        model_used=model_used,
        generated_at=now,
    )


def list_ollama_models(
    ollama_url: str = "http://localhost:11434",
    timeout: float = 3.0,
    air_gapped_mode: bool = False,
) -> list[str]:
    """Query local Ollama instance for installed model names (0 HTTP when `air_gapped_mode=True`)."""
    if air_gapped_mode:
        return []
    url = ollama_url.rstrip("/") + "/api/tags"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            return [m["name"] for m in payload.get("models", []) if "name" in m]
    except Exception:
        return []


def _summarize_with_ollama(
    prompt: str,
    settings: AppSettings,
    template: str,
    timeout: float = 180.0,
) -> SummaryResult:
    url = settings.ollama_url.rstrip("/") + "/api/chat"
    lang = "tr" if settings.summary_language.lower().startswith("türk") else "en"
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": _build_system_prompt(template, lang=lang)},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError as exc:
        raise SummarizerError(
            f"Could not connect to Ollama at {settings.ollama_url}. "
            "Start Ollama or choose 'Auto / Built-in Offline' in Settings."
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise SummarizerError(f"Ollama HTTP {exc.response.status_code}: {detail}") from exc
    except Exception as exc:
        raise SummarizerError(f"Ollama summarization error: {exc}") from exc

    content = data.get("message", {}).get("content", "")
    if not content.strip():
        raise SummarizerError("Ollama returned an empty response.")
    return parse_summary_response(
        content,
        model_used=f"ollama/{settings.ollama_model}",
        template=template,
    )


def _summarize_with_openai_compatible(
    prompt: str,
    settings: AppSettings,
    template: str,
    timeout: float = 120.0,
) -> SummaryResult:
    if not settings.api_key.strip():
        raise SummarizerError("API key is not configured. Add it in Settings > Summarization.")

    url = settings.api_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.api_key.strip()}",
        "Content-Type": "application/json",
    }
    lang = "tr" if settings.summary_language.lower().startswith("türk") else "en"
    payload = {
        "model": settings.api_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _build_system_prompt(template, lang=lang)},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise SummarizerError(f"API HTTP {exc.response.status_code}: {detail}") from exc
    except Exception as exc:
        raise SummarizerError(f"API summarization error: {exc}") from exc

    choices = data.get("choices", [])
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    if not content.strip():
        raise SummarizerError("API returned an empty response.")
    return parse_summary_response(
        content,
        model_used=f"api/{settings.api_model}",
        template=template,
    )


def summarize_meeting(
    segments: Sequence[TranscriptSegment],
    settings: AppSettings,
    template: str = "meeting",
    notes: str = "",
) -> SummaryResult:
    """Summarize transcript segments. Guarantees 0 outbound HTTP when `air_gapped_mode=True`."""
    if not segments:
        raise SummarizerError("No transcript segments available to summarize.")

    if settings.air_gapped_mode or settings.llm_provider == "local_extractive":
        res = extractive_summarize(segments, template=template, notes=notes)
        if settings.air_gapped_mode:
            res.model_used = "local/extractive-offline (Air-Gapped)"
        return res

    prompt = build_transcript_prompt(segments, language=settings.summary_language, notes=notes)

    if settings.llm_provider == "openai_compatible":
        return _summarize_with_openai_compatible(prompt, settings, template)

    if settings.llm_provider == "ollama":
        return _summarize_with_ollama(prompt, settings, template)

    # "auto": Try local Ollama first; if unreachable, seamlessly use built-in offline engine
    try:
        return _summarize_with_ollama(prompt, settings, template, timeout=120.0)
    except SummarizerError:
        result = extractive_summarize(segments, template=template, notes=notes)
        result.model_used = "local/extractive-offline (Auto fallback)"
        return result


def enhance_meeting_notes(
    segments: Sequence[TranscriptSegment],
    notes: str,
    settings: AppSettings,
) -> tuple[str, str]:
    """
    Granola-style note enhancement: weave user shorthand notes with transcript facts.
    Returns `(enhanced_markdown, model_used)`. Respects `air_gapped_mode`.
    """
    if settings.air_gapped_mode or settings.llm_provider == "local_extractive":
        label = "local/extractive-offline (Air-Gapped)" if settings.air_gapped_mode else "local/extractive-offline"
        return enhance_notes_offline(segments, notes), label

    prompt = (
        f"Enhance and expand the user's brief meeting notes in {settings.summary_language} "
        "by weaving in accurate details, decisions, and action items from the transcript. "
        "Preserve every point the user wrote and add concise Markdown headings.\n\n"
        f"USER NOTES:\n{notes.strip() or '(No manual notes yet)'}\n\n"
        "TRANSCRIPT:\n"
        + "\n".join(
            f"[{format_timestamp(s.start_sec)}] {s.speaker}: {s.text.strip()}"
            for s in segments[:200]
        )
    )

    if settings.llm_provider in ("auto", "ollama"):
        try:
            url = settings.ollama_url.rstrip("/") + "/api/chat"
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    url,
                    json={
                        "model": settings.ollama_model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": "You are a concise meeting notes editor."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                content = resp.json().get("message", {}).get("content", "").strip()
                if content:
                    return content, f"ollama/{settings.ollama_model}"
        except Exception:
            if settings.llm_provider == "ollama":
                raise SummarizerError("Ollama unreachable while enhancing notes.")

    if settings.llm_provider == "openai_compatible" and settings.api_key.strip():
        try:
            url = settings.api_base_url.rstrip("/") + "/chat/completions"
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.api_key.strip()}"},
                    json={
                        "model": settings.api_model,
                        "temperature": 0.2,
                        "messages": [
                            {"role": "system", "content": "You are a concise meeting notes editor."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                choices = resp.json().get("choices", [])
                content = choices[0].get("message", {}).get("content", "").strip() if choices else ""
                if content:
                    return content, f"api/{settings.api_model}"
        except Exception as exc:
            raise SummarizerError(f"API error while enhancing notes: {exc}") from exc

    return enhance_notes_offline(segments, notes), "local/extractive-offline"
