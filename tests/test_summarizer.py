"""Unit tests for LLM summary response parsing and offline extractive summarizer."""

from localminutes.models import AppSettings, TranscriptSegment
from localminutes.summarization.local_extractive import extractive_summarize
from localminutes.summarization.summarizer import parse_summary_response, summarize_meeting


def test_parse_clean_json() -> None:
    raw = """
    {
      "overview": "Kısa bir teknik toplantı yapıldı.",
      "key_points": ["Hız optimizasyonu", "Bellek kullanımı"],
      "decisions": ["INT8 kuantizasyon seçildi"],
      "action_items": ["Benchmark raporunu paylaş"]
    }
    """
    res = parse_summary_response(raw, model_used="ollama/qwen2.5:7b", template="technical")
    assert res.overview == "Kısa bir teknik toplantı yapıldı."
    assert res.key_points == ["Hız optimizasyonu", "Bellek kullanımı"]
    assert res.decisions == ["INT8 kuantizasyon seçildi"]
    assert res.action_items == ["Benchmark raporunu paylaş"]
    assert res.template == "technical"


def test_parse_fenced_json_and_fallback() -> None:
    fenced = 'İşte özet:\n```json\n{"overview": "Özet metni", "decisions": ["Karar A"]}\n```'
    res = parse_summary_response(fenced)
    assert res.overview == "Özet metni"
    assert res.decisions == ["Karar A"]
    assert res.action_items == []

    plain = "Düz metin özet yanıtı."
    fallback = parse_summary_response(plain)
    assert fallback.overview == "Düz metin özet yanıtı."


def test_local_extractive_summarizer_and_auto_fallback() -> None:
    segments = [
        TranscriptSegment(
            speaker="Sen",
            text="Proje mimarisi için PyQt6 ve SQLite FTS5 kullanılmasına karar verdik.",
            start_sec=1.0,
            end_sec=5.0,
            is_bookmarked=True,
        ),
        TranscriptSegment(
            speaker="Karşı Taraf",
            text="Ben yarın akşama kadar ses yakalama testlerini tamamlayacağım ve raporu paylaşacağım.",
            start_sec=6.0,
            end_sec=12.0,
        ),
        TranscriptSegment(
            speaker="Sen",
            text="Harika, haftalık toplantı notlarını da Markdown olarak dışa aktaralım.",
            start_sec=13.0,
            end_sec=17.0,
        ),
    ]

    offline = extractive_summarize(segments, template="meeting", notes="Cuma günü demo var")
    assert offline.overview
    assert len(offline.decisions) >= 1
    assert len(offline.action_items) >= 1
    assert any("[Not] Cuma günü demo var" in kp for kp in offline.key_points)

    # Auto mode falls back seamlessly to local extractive when Ollama is unreachable
    settings = AppSettings(llm_provider="auto", ollama_url="http://127.0.0.1:19999")
    auto_res = summarize_meeting(segments, settings, template="meeting")
    assert auto_res.overview
    assert "extractive-offline" in auto_res.model_used
