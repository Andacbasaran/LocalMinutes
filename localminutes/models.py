"""Core data models for LocalMinutes v1.0.0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

SpeakerRole = Literal["You", "Remote", "Sen", "Karşı Taraf"]

SUMMARY_TEMPLATES: dict[str, dict[str, str]] = {
    "meeting": {
        "label": "Genel Toplantı",
        "label_en": "General Meeting",
        "overview_title": "Genel Özet",
        "overview_title_en": "Executive Summary",
        "key_points_title": "Öne Çıkan Noktalar",
        "key_points_title_en": "Key Highlights",
        "decisions_title": "Alınan Kararlar",
        "decisions_title_en": "Key Decisions",
        "action_items_title": "Yapılacaklar (Action Items)",
        "action_items_title_en": "Action Items",
        "instruction": (
            "Bu bir iş/ekip toplantısıdır. Toplantının amacını, önemli noktaları, net alınan "
            "kararları ve sorumlu kişi/tarih belirterek aksiyon maddelerini çıkar."
        ),
        "instruction_en": (
            "This is a team/business meeting. Extract the core objective, key points, clear "
            "decisions, and concrete action items with assignees/deadlines when mentioned."
        ),
    },
    "lecture": {
        "label": "Ders / Eğitim",
        "label_en": "Lecture / Study",
        "overview_title": "Ders Özeti",
        "overview_title_en": "Lecture Overview",
        "key_points_title": "Temel Kavramlar ve Tanımlar",
        "key_points_title_en": "Core Concepts & Definitions",
        "decisions_title": "Önemli Vurgular ve Örnekler",
        "decisions_title_en": "Key Examples & Takeaways",
        "action_items_title": "Çalışma Notları ve Olası Sınav Soruları",
        "action_items_title_en": "Study Tasks & Review Questions",
        "instruction": (
            "Bu bir ders veya eğitim kaydıdır. Konunun özünü, temel kavram/tanımları, eğitmenin "
            "vurguladığı kritik örnekleri ve öğrencinin çalışması gereken soru/ödevleri çıkar."
        ),
        "instruction_en": (
            "This is a lecture or training session. Summarize the topic, core concepts/definitions, "
            "important instructor examples, and follow-up study tasks or likely exam questions."
        ),
    },
    "technical": {
        "label": "Teknik / Sprint",
        "label_en": "Engineering / Sprint",
        "overview_title": "Teknik Özet",
        "overview_title_en": "Engineering Summary",
        "key_points_title": "Mimari ve Teknik Detaylar",
        "key_points_title_en": "Architecture & Technical Notes",
        "decisions_title": "Alınan Teknik Kararlar",
        "decisions_title_en": "Technical Decisions",
        "action_items_title": "Geliştirme Görevleri ve Blokerler",
        "action_items_title_en": "Engineering Tasks & Blockers",
        "instruction": (
            "Bu bir teknik veya sprint toplantısıdır. Teknik konuları, mimari kararları, "
            "risk/blokerleri ve somut geliştirme görevlerini çıkar."
        ),
        "instruction_en": (
            "This is a technical or sprint planning meeting. Extract technical topics, architectural "
            "decisions, risks/blockers, and concrete engineering action items."
        ),
    },
    "interview": {
        "label": "Mülakat / Görüşme",
        "label_en": "Interview / 1:1",
        "overview_title": "Görüşme Özeti",
        "overview_title_en": "Interview Summary",
        "key_points_title": "Öne Çıkan Yetkinlikler ve Bilgiler",
        "key_points_title_en": "Strengths & Notable Signals",
        "decisions_title": "Değerlendirme ve Dikkat Çekenler",
        "decisions_title_en": "Evaluation & Key Observations",
        "action_items_title": "Sonraki Adımlar",
        "action_items_title_en": "Next Steps",
        "instruction": (
            "Bu bir mülakat veya birebir görüşmedir. Görüşmenin özetini, öne çıkan güçlü "
            "yönleri/bilgileri, kritik değerlendirme noktalarını ve sonraki adımları çıkar."
        ),
        "instruction_en": (
            "This is an interview or 1:1 conversation. Summarize the discussion, standout signals, "
            "evaluation highlights, and clear follow-up next steps."
        ),
    },
}


def get_template_meta(template_key: str, lang: str = "en") -> dict[str, str]:
    """Return localized template titles and instructions for 'en' or 'tr'."""
    raw = SUMMARY_TEMPLATES.get(template_key, SUMMARY_TEMPLATES["meeting"])
    if lang == "tr":
        return {
            "label": raw["label"],
            "overview_title": raw["overview_title"],
            "key_points_title": raw["key_points_title"],
            "decisions_title": raw["decisions_title"],
            "action_items_title": raw["action_items_title"],
            "instruction": raw["instruction"],
        }
    return {
        "label": raw["label_en"],
        "overview_title": raw["overview_title_en"],
        "key_points_title": raw["key_points_title_en"],
        "decisions_title": raw["decisions_title_en"],
        "action_items_title": raw["action_items_title_en"],
        "instruction": raw["instruction_en"],
    }


@dataclass
class AudioDevice:
    """Represents a microphone or system loopback audio device on Windows, macOS, or Linux."""

    index: int
    name: str
    is_loopback: bool
    channels: int
    default_sample_rate: int
    is_default: bool = False
    backend: str = "sounddevice"  # "pyaudiowpatch" | "sounddevice"

    @property
    def display_name(self) -> str:
        prefix = "[Loopback] " if self.is_loopback else "[Mic] "
        suffix = " (Default)" if self.is_default else ""
        return f"{prefix}{self.name}{suffix}"


@dataclass
class TranscriptSegment:
    """A single speaker-labeled transcript segment."""

    id: Optional[int] = None
    meeting_id: Optional[int] = None
    speaker: str = "You"
    text: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    is_bookmarked: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class ActionItem:
    """A persisted, interactive action item linked to a meeting."""

    id: Optional[int] = None
    meeting_id: Optional[int] = None
    text: str = ""
    assignee: str = ""
    due_date: str = ""
    completed: bool = False
    meeting_title: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class QACitation:
    """A grounded timestamp citation linking a Q&A answer back to a transcript segment."""

    segment_id: Optional[int]
    speaker: str
    timestamp_sec: float
    snippet: str
    score: float = 0.0


@dataclass
class QAResponse:
    """Response from LocalMinutes 'Ask This Meeting' local Q&A engine."""

    question: str
    answer: str
    citations: list[QACitation] = field(default_factory=list)
    model_used: str = "local/bm25-offline"


@dataclass
class SummaryResult:
    """Structured meeting summary with decisions and action items."""

    overview: str = ""
    key_points: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    template: str = "meeting"
    raw_markdown: str = ""
    model_used: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class Meeting:
    """A recorded meeting or lecture session."""

    id: Optional[int] = None
    title: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    duration_sec: float = 0.0
    language: str = "auto"
    template: str = "meeting"
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    summary: Optional[SummaryResult] = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)


@dataclass
class AppSettings:
    """Persistent cross-platform user configuration."""

    # UI & System
    ui_language: str = "en"  # "en" | "tr"
    air_gapped_mode: bool = False
    check_updates_on_startup: bool = True
    minimize_to_tray: bool = False
    performance_profile: str = "auto"  # "auto" | "eco" | "balanced" | "performance"

    # Audio settings
    mic_device_index: Optional[int] = None
    loopback_device_index: Optional[int] = None
    capture_mic: bool = True
    capture_loopback: bool = True
    save_wav: bool = False

    # Transcription settings
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_language: str = "auto"  # "auto", "en", "tr"
    custom_vocabulary: str = ""  # Whisper initial_prompt for domain jargon & EN/TR code-switching
    vad_silence_ms: int = 800
    chunk_max_sec: float = 12.0
    energy_threshold: float = 0.008

    # Summarization settings
    llm_provider: str = "auto"  # "auto" | "ollama" | "openai_compatible" | "local_extractive"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    api_base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    api_model: str = "gpt-4o-mini"
    summary_language: str = "English"
    default_template: str = "meeting"
