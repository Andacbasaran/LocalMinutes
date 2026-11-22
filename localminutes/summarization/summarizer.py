"""Meeting summarization using local Ollama or an optional OpenAI-compatible API."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Sequence

import httpx

from localminutes.export.exporter import format_timestamp
from localminutes.models import AppSettings, SummaryResult, TranscriptSegment


class SummarizerError(RuntimeError):
    """Raised when LLM summarization fails."""


SYSTEM_PROMPT = """Sen uzman bir toplantı ve ders asistanısın.
Sana konuşmacı etiketli ("Sen" ve "Karşı Taraf") bir toplantı veya ders transkripti verilecek.
Görevin, yalnızca transkriptteki gerçek bilgilere dayanarak net, yapılandırılmış bir özet çıkarmaktır.

Yanıtını SADECE geçerli bir JSON nesnesi olarak döndür (kod bloğu veya ekstra açıklama ekleme):
{
  "overview": "Toplantının veya dersin 2-4 cümlelik genel özeti.",
  "key_points": ["Önemli nokta 1", "Önemli nokta 2"],
  "decisions": ["Alınan karar 1 (yoksa boş liste)"],
  "action_items": ["Sorumlu kişi varsa belirterek yapılacak görev 1 (yoksa boş liste)"]
}
"""


def build_transcript_prompt(segments: Sequence[TranscriptSegment], language: str = "Türkçe") -> str:
    """Format transcript segments into a clean LLM prompt."""
    lines = [
        f"Lütfen aşağıdaki transkripti {language} dilinde özetle ve istenen JSON formatında yanıt ver.",
        "",
        "TRANSKRİPT:",
    ]
    for seg in segments:
        ts = format_timestamp(seg.start_sec)
        lines.append(f"[{ts}] {seg.speaker}: {seg.text.strip()}")
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


def parse_summary_response(raw_text: str, model_used: str = "") -> SummaryResult:
    """Parse structured JSON summary response, falling back gracefully to raw Markdown."""
    now = datetime.now().isoformat(timespec="seconds")
    candidate = _extract_json_block(raw_text)
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            overview = str(data.get("overview", "")).strip()
            key_points = _ensure_str_list(data.get("key_points"))
            decisions = _ensure_str_list(data.get("decisions"))
            action_items = _ensure_str_list(data.get("action_items"))
            return SummaryResult(
                overview=overview,
                key_points=key_points,
                decisions=decisions,
                action_items=action_items,
                raw_markdown=raw_text.strip(),
                model_used=model_used,
                generated_at=now,
            )
    except json.JSONDecodeError:
        pass

    # Fallback: treat raw text as overview
    return SummaryResult(
        overview=raw_text.strip(),
        key_points=[],
        decisions=[],
        action_items=[],
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


def _summarize_with_ollama(prompt: str, settings: AppSettings, timeout: float = 180.0) -> SummaryResult:
    url = settings.ollama_url.rstrip("/") + "/api/chat"
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
            "Ollama'nın çalıştığından emin olun veya Ayarlar'dan API sağlayıcısı seçin."
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
    return parse_summary_response(content, model_used=f"ollama/{settings.ollama_model}")


def _summarize_with_openai_compatible(
    prompt: str, settings: AppSettings, timeout: float = 120.0
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
            {"role": "system", "content": SYSTEM_PROMPT},
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
    return parse_summary_response(content, model_used=f"api/{settings.api_model}")


def summarize_meeting(
    segments: Sequence[TranscriptSegment],
    settings: AppSettings,
) -> SummaryResult:
    """Summarize transcript segments using the configured LLM provider."""
    if not segments:
        raise SummarizerError("Özetlenecek transkript segmenti bulunmuyor.")

    prompt = build_transcript_prompt(segments, language=settings.summary_language)
    if settings.llm_provider == "openai_compatible":
        return _summarize_with_openai_compatible(prompt, settings)
    return _summarize_with_ollama(prompt, settings)
