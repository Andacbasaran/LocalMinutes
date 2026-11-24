"""Zero-dependency 100% offline extractive summarizer & note synthesizer (English & Turkish)."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Sequence

from localminutes.models import SummaryResult, TranscriptSegment

_STOPWORDS = {
    # Turkish
    "ve", "veya", "ile", "bir", "bu", "şu", "o", "da", "de", "ki", "mi", "mı", "mu", "mü",
    "ama", "fakat", "ancak", "lakin", "çünkü", "için", "gibi", "kadar", "daha", "en", "çok",
    "az", "ben", "sen", "biz", "siz", "onlar", "var", "yok", "olan", "olarak", "ise", "ya",
    "ne", "nasıl", "neden", "niye", "evet", "hayır", "tamam", "peki", "yani", "şey", "işte",
    "şimdi", "sonra", "önce", "burada", "orada", "her", "hiç", "bazı", "tüm", "bütün",
    # English
    "the", "and", "or", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "not", "but", "you", "your", "they", "their", "will", "would", "can", "could",
    "should", "about", "into", "just", "like", "then", "than", "also", "very", "here", "there",
    "our", "we", "its", "been", "all", "what", "when", "where", "how", "who",
}

_DECISION_PATTERNS = re.compile(
    r"\b("
    r"karar|kararlaştır|onaylandı|anlaştık|mutabık|kesinleşti|seçildi|kullanılacak|"
    r"uygulayacağız|geçeceğiz|böyle yapalım|netleşti|decided|agreed|approved|confirmed|"
    r"we will use|locked in|finalized|going with|ship on|aligned on"
    r")\b",
    re.IGNORECASE,
)

_ACTION_PATTERNS = re.compile(
    r"\b("
    r"yapacağım|yapacağız|yapalım|tamamlayalım|hazırlayalım|göndereceğim|paylaşacağım|"
    r"kontrol edelim|kontrol edeceğim|bitirelim|ekleyelim|düzeltelim|araştıralım|"
    r"takip edelim|gerekli|lazım|sorumlu|teslim|deadline|todo|action item|will do|need to|follow up|"
    r"assign|send|prepare|review|finish|complete|i will|i'll|let's|make sure to|draft|benchmark|update"
    r")\b",
    re.IGNORECASE,
)


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]{3,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]


def extractive_summarize(
    segments: Sequence[TranscriptSegment],
    template: str = "meeting",
    notes: str = "",
) -> SummaryResult:
    """Produce a structured offline summary using TF-IDF sentence scoring + rule-based extraction."""
    now = datetime.now().isoformat(timespec="seconds")
    if not segments:
        return SummaryResult(
            overview="No transcript segments available to summarize.",
            template=template,
            model_used="local/extractive-offline",
            generated_at=now,
        )

    candidates: list[tuple[int, TranscriptSegment, list[str]]] = []
    doc_freq: Counter[str] = Counter()

    for idx, seg in enumerate(segments):
        cleaned = seg.text.strip()
        if not cleaned:
            continue
        tokens = _tokenize(cleaned)
        candidates.append((idx, seg, tokens))
        for tok in set(tokens):
            doc_freq[tok] += 1

    total_docs = max(1, len(candidates))
    scored: list[tuple[float, int, TranscriptSegment]] = []
    decisions: list[str] = []
    action_items: list[str] = []

    for idx, seg, tokens in candidates:
        tf = Counter(tokens)
        score = 0.0
        for tok, count in tf.items():
            idf = math.log((total_docs + 1) / (doc_freq[tok] + 1)) + 1.0
            score += (count / max(1, len(tokens))) * idf

        length_bonus = min(1.0, len(tokens) / 10.0)
        bookmark_bonus = 1.65 if seg.is_bookmarked else 1.0
        final_score = score * (0.5 + 0.5 * length_bonus) * bookmark_bonus
        scored.append((final_score, idx, seg))

        text_clean = seg.text.strip()
        if _DECISION_PATTERNS.search(text_clean):
            entry = f"{seg.speaker}: {text_clean}"
            if entry not in decisions:
                decisions.append(entry)
        if _ACTION_PATTERNS.search(text_clean):
            entry = f"{seg.speaker}: {text_clean}"
            if entry not in action_items:
                action_items.append(entry)

    top_for_overview = sorted(scored, key=lambda x: x[0], reverse=True)[: min(3, len(scored))]
    top_for_overview.sort(key=lambda x: x[1])
    overview = " ".join(seg.text.strip() for _, _, seg in top_for_overview)

    top_for_points = sorted(scored, key=lambda x: x[0], reverse=True)[: min(6, len(scored))]
    top_for_points.sort(key=lambda x: x[1])
    key_points: list[str] = []
    for _, _, seg in top_for_points:
        prefix = "[Starred] " if seg.is_bookmarked else ""
        item = f"{prefix}{seg.speaker}: {seg.text.strip()}"
        if item not in key_points:
            key_points.append(item)

    if notes.strip():
        for line in notes.strip().splitlines():
            line_clean = line.strip(" -•*")
            if line_clean:
                key_points.append(f"[Not] {line_clean}")

    return SummaryResult(
        overview=overview,
        key_points=key_points[:8],
        decisions=decisions[:8],
        action_items=action_items[:10],
        template=template,
        raw_markdown=overview,
        model_used="local/extractive-offline",
        generated_at=now,
    )


def enhance_notes_offline(
    segments: Sequence[TranscriptSegment],
    notes: str,
) -> str:
    """Granola-style 100% offline note synthesis merging user jottings with grounded transcript evidence."""
    summary = extractive_summarize(segments, notes=notes)
    lines: list[str] = []
    if notes.strip():
        lines.append("### Your Notes (Preserved)")
        for raw_line in notes.strip().splitlines():
            cleaned = raw_line.strip()
            if cleaned:
                lines.append(cleaned if cleaned.startswith("-") else f"- {cleaned}")
        lines.append("")

    if summary.overview:
        lines.append("### Transcript Context")
        lines.append(summary.overview)
        lines.append("")

    if summary.decisions:
        lines.append("### Decisions Mentioned")
        for d in summary.decisions[:5]:
            lines.append(f"- {d}")
        lines.append("")

    if summary.action_items:
        lines.append("### Follow-Up Actions")
        for a in summary.action_items[:6]:
            lines.append(f"- [ ] {a}")

    return "\n".join(lines).strip()
