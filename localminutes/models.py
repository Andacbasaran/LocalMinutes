"""Core data models for LocalMinutes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

SpeakerRole = Literal["Sen", "Karşı Taraf"]

SUMMARY_TEMPLATES: dict[str, dict[str, str]] = {
    "meeting": {
        "label": "Genel Toplantı",
        "overview_title": "Genel Özet",
        "key_points_title": "Öne Çıkan Noktalar",
        "decisions_title": "Alınan Kararlar",
        "action_items_title": "Yapılacaklar (Action Items)",
        "instruction": "Bu bir iş/ekip toplantısıdır. Toplantının amacını, önemli noktaları, net alınan kararları ve sorumlu kişi/tarih belirterek aksiyon maddelerini çıkar.",
    },
    "lecture": {
        "label": "Ders / Eğitim",
        "overview_title": "Ders Özeti",
        "key_points_title": "Temel Kavramlar ve Tanımlar",
        "decisions_title": "Önemli Vurgular ve Örnekler",
        "action_items_title": "Çalışma Notları ve Olası Sınav Soruları",
        "instruction": "Bu bir ders veya eğitim kaydıdır. Konunun özünü, temel kavram/tanımları, eğitmenin vurguladığı kritik örnekleri ve öğrencinin çalışması gereken soru/ödevleri çıkar.",
    },
    "technical": {
        "label": "Teknik / Sprint",
        "overview_title": "Teknik Özet",
        "key_points_title": "Mimari ve Teknik Detaylar",
        "decisions_title": "Alınan Teknik Kararlar",
        "action_items_title": "Geliştirme Görevleri ve Blokerler",
        "instruction": "Bu bir teknik veya sprint toplantısıdır. Teknik konuları, mimari kararları, risk/blokerleri ve somut geliştirme görevlerini çıkar.",
    },
    "interview": {
        "label": "Mülakat / Görüşme",
        "overview_title": "Görüşme Özeti",
        "key_points_title": "Öne Çıkan Yetkinlikler ve Bilgiler",
        "decisions_title": "Değerlendirme ve Dikkat Çekenler",
        "action_items_title": "Sonraki Adımlar",
        "instruction": "Bu bir mülakat veya birebir görüşmedir. Görüşmenin özetini, öne çıkan güçlü yönleri/bilgileri, kritik değerlendirme noktalarını ve sonraki adımları çıkar.",
    },
}


@dataclass
class AudioDevice:
    """Represents a microphone or WASAPI loopback audio device."""

    index: int
    name: str
    is_loopback: bool
    channels: int
    default_sample_rate: int
    is_default: bool = False

    @property
    def display_name(self) -> str:
        prefix = "[Sistem] " if self.is_loopback else "[Mikrofon] "
        suffix = " (Varsayılan)" if self.is_default else ""
        return f"{prefix}{self.name}{suffix}"


@dataclass
class TranscriptSegment:
    """A single speaker-labeled transcript segment."""

    id: Optional[int] = None
    meeting_id: Optional[int] = None
    speaker: str = "Sen"
    text: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    is_bookmarked: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


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
    language: str = "tr"
    template: str = "meeting"
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    summary: Optional[SummaryResult] = None
    segments: list[TranscriptSegment] = field(default_factory=list)


@dataclass
class AppSettings:
    """Persistent user configuration."""

    # Audio settings
    mic_device_index: Optional[int] = None
    loopback_device_index: Optional[int] = None
    capture_mic: bool = True
    capture_loopback: bool = True
    save_wav: bool = False

    # Transcription settings
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_language: str = "tr"  # "tr", "en", or "auto"
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
    summary_language: str = "Türkçe"
    default_template: str = "meeting"
