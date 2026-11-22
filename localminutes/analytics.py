"""Meeting analytics: talk-time / word-share distribution and quick stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from localminutes.models import TranscriptSegment


@dataclass
class MeetingStats:
    total_segments: int = 0
    total_words: int = 0
    bookmarked_count: int = 0
    speaker_word_share: dict[str, float] = field(default_factory=dict)
    speaker_segment_counts: dict[str, int] = field(default_factory=dict)


def compute_meeting_stats(segments: Sequence[TranscriptSegment]) -> MeetingStats:
    """Compute word counts, bookmark counts, and speaker share percentages."""
    if not segments:
        return MeetingStats()

    word_counts: dict[str, int] = {}
    seg_counts: dict[str, int] = {}
    total_words = 0
    bookmarked = 0

    for seg in segments:
        words = len(seg.text.split())
        total_words += words
        word_counts[seg.speaker] = word_counts.get(seg.speaker, 0) + words
        seg_counts[seg.speaker] = seg_counts.get(seg.speaker, 0) + 1
        if seg.is_bookmarked:
            bookmarked += 1

    share: dict[str, float] = {}
    if total_words > 0:
        for spk, cnt in word_counts.items():
            share[spk] = round((cnt / total_words) * 100.0, 1)

    return MeetingStats(
        total_segments=len(segments),
        total_words=total_words,
        bookmarked_count=bookmarked,
        speaker_word_share=share,
        speaker_segment_counts=seg_counts,
    )
