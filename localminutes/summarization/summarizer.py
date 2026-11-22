"""Meeting summarization using local Ollama, OpenAI-compatible API, or built-in offline engine."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Sequence

import httpx

from localminutes.export.exporter import format_timestamp
from localminutes.models import SUMMARY_TEMPLATES, AppSettings, SummaryResult, TranscriptSegment
from localminutes.summarization.local_extractive import extractive_summarize


class SummarizerError(RuntimeError):
    """Raised when LLM summarization fails."""


def _build_system_prompt(template_key: str) -> str:
    tmpl = SUMMARY_TEMPLATES.get(template_key, SUMMARY_TEMPLATES["meeting"])
    return (
        "Sen uzman bir toplantı ve ders asistanısın.\n"
        f"{tmpl['instruction']}\n"
        "Sana konuşmacı etiketli bir transkript ve varsa kullanıcı notları verilecek. "
        "Yalnızca verilen gerçek bilgilere dayanarak net, yapılandırılmış bir özet çıkar.\n\n"
        "Yanıtını SADECE geçerli bir JSON nesnesi olarak döndür (kod bloğu veya ekstra açıklama ekleme):\n"
        "{\n"
        f'  "overview": "{tmpl["overview_title"]} (2-4 cümle)",\n'
        f'  "key_points": ["{tmpl["key_points_title"]} maddesi 1", "..."],\n'
        f'  "decisions": ["{tmpl["decisions_title"]} maddesi 1 (yoksa boş liste)"],\n'
        f'  "action_items": ["{tmpl["action_items_title"]} maddesi 1 (yoksa boş liste)"]\n'
        "}\n"
    )


def build_transcript_prompt(
    segments: Sequence[TranscriptSegment],
    language: str = "Türkçe",
    notes: str = "",
) -> str:
    """Format transcript segments and optional user notes into a clean LLM prompt."""
    lines = [
        f"Lütfen aşağıdaki kaydı {language} dilinde özetle ve istenen JSON formatında yanıt ver.",
        "",
    ]
    if notes.strip():
        lines.append("KULLANICI NOTLARI:")
        lines.append(notes.strip())
        lines.append("")

    bookmarked = [s for s in segments if s.is_bookmarked]
    if bookmarked:
        lines.append("İŞARETLENEN ÖNEMLİ ANLAR:")
        for seg in bookmarked:
            lines.append(f"- [{format_timestamp(seg.start_sec)}] {seg.speaker}: {seg.text.strip()}")
        lines.append("")

    lines.append("TRANSKRİPT:")
    for seg in segments:
        ts = format_timestamp(seg.start_sec)
        star = " [ÖNEMLİ]" if seg.is_bookmarked else ""
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
    """Parse structured JSON summary response, falling back gracefully to raw Markdown."""
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


def list_ollama_models(ollama_url: str = "http://localhost:11434", timeout: float = 3.0) -> list[str]:
    """Query local Ollama instance for installed model names."""
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
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": _build_system_prompt(template)},
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
            f"Ollama sunucusuna bağlanılamadı ({settings.ollama_url}). "
            "Ollama'nın çalıştığından emin olun veya Ayarlar'dan 'Otomatik / Yerleşik Offline' seçin."
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise SummarizerError(
            f"Ollama hatası (HTTP {exc.response.status_code}): {detail}"
        ) from exc
    except Exception as exc:
        raise SummarizerError(f"Ollama özetleme hatası: {exc}") from exc

    content = data.get("message", {}).get("content", "")
    if not content.strip():
        raise SummarizerError("Ollama boş yanıt döndürdü.")
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
        raise SummarizerError("API anahtarı ayarlanmamış. Lütfen Ayarlar > Özetleme bölümünden ekleyin.")

    url = settings.api_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.api_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _build_system_prompt(template)},
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
        raise SummarizerError(f"API hatası (HTTP {exc.response.status_code}): {detail}") from exc
    except Exception as exc:
        raise SummarizerError(f"API özetleme hatası: {exc}") from exc

    choices = data.get("choices", [])
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    if not content.strip():
        raise SummarizerError("API boş yanıt döndürdü.")
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
    """Summarize transcript segments using the configured provider with optional offline fallback."""
    if not segments:
        raise SummarizerError("Özetlenecek transkript segmenti bulunmuyor.")

    provider = settings.llm_provider
    if provider == "local_extractive":
        return extractive_summarize(segments, template=template, notes=notes)

    prompt = build_transcript_prompt(segments, language=settings.summary_language, notes=notes)

    if provider == "openai_compatible":
        return _summarize_with_openai_compatible(prompt, settings, template)

    if provider == "ollama":
        return _summarize_with_ollama(prompt, settings, template)

    # "auto": Try local Ollama first; if unreachable, seamlessly use built-in offline engine
    try:
        return _summarize_with_ollama(prompt, settings, template, timeout=120.0)
    except SummarizerError:
        result = extractive_summarize(segments, template=template, notes=notes)
        result.model_used = "local/extractive-offline (Ollama bulunamadı)"
        return result
