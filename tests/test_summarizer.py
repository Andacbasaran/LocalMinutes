"""Unit tests for LLM summary response parsing."""

from localminutes.summarization.summarizer import parse_summary_response


def test_parse_clean_json() -> None:
    raw = """
    {
      "overview": "Kısa bir teknik toplantı yapıldı.",
      "key_points": ["Hız optimizasyonu", "Bellek kullanımı"],
      "decisions": ["INT8 kuantizasyon seçildi"],
      "action_items": ["Benchmark raporunu paylaş"]
    }
    """
    res = parse_summary_response(raw, model_used="ollama/qwen2.5:7b")
    assert res.overview == "Kısa bir teknik toplantı yapıldı."
    assert res.key_points == ["Hız optimizasyonu", "Bellek kullanımı"]
    assert res.decisions == ["INT8 kuantizasyon seçildi"]
    assert res.action_items == ["Benchmark raporunu paylaş"]
    assert res.model_used == "ollama/qwen2.5:7b"


def test_parse_fenced_json_and_fallback() -> None:
    fenced = 'İşte özet:\n```json\n{"overview": "Özet metni", "decisions": ["Karar A"]}\n```'
    res = parse_summary_response(fenced)
    assert res.overview == "Özet metni"
    assert res.decisions == ["Karar A"]
    assert res.action_items == []

    plain = "Düz metin özet yanıtı."
    fallback = parse_summary_response(plain)
    assert fallback.overview == "Düz metin özet yanıtı."
