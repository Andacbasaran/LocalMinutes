"""Meeting analytics: talk-time, speaking pace (WPM), word share, and bookmark stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from localminutes.models import TranscriptSegment


@dataclass
class MeetingStats:
    total_segments: int = 0
    total_words: int = 0
    bookmarked_count: int = 0
    total_talk_sec: float = 0.0
    words_per_minute: float = 0.0
    speaker_word_share: dict[str, float] = field(default_factory=dict)
    speaker_segment_counts: dict[str, int] = field(default_factory=dict)
    speaker_talk_sec: dict[str, float] = field(default_factory=dict)
    speaker_wpm: dict[str, float] = field(default_factory=dict)


def compute_meeting_stats(segments: Sequence[TranscriptSegment]) -> MeetingStats:
    """Compute word counts, talk durations, WPM pace, bookmark counts, and speaker shares."""
    if not segments:
        return MeetingStats()

    word_counts: dict[str, int] = {}
    seg_counts: dict[str, int] = {}
    talk_sec: dict[str, float] = {}
    total_words = 0
    total_talk = 0.0
    bookmarked = 0

    for seg in segments:
        words = len(seg.text.split())
        dur = max(0.4, float(seg.end_sec) - float(seg.start_sec)) if seg.end_sec > seg.start_sec else max(0.5, words / 2.5)
        total_words += words
        total_talk += dur
        word_counts[seg.speaker] = word_counts.get(seg.speaker, 0) + words
        seg_counts[seg.speaker] = seg_counts.get(seg.speaker, 0) + 1
        talk_sec[seg.speaker] = round(talk_sec.get(seg.speaker, 0.0) + dur, 1)
        if seg.is_bookmarked:
            bookmarked += 1

    share: dict[str, float] = {}
    spk_wpm: dict[str, float] = {}
    if total_words > 0:
        for spk, cnt in word_counts.items():
            share[spk] = round((cnt / total_words) * 100.0, 1)
            sec = talk_sec.get(spk, 0.0)
            spk_wpm[spk] = round((cnt / sec) * 60.0, 1) if sec > 0 else 0.0

    overall_wpm = round((total_words / total_talk) * 60.0, 1) if total_talk > 0 else 0.0

    return MeetingStats(
        total_segments=len(segments),
        total_words=total_words,
        bookmarked_count=bookmarked,
        total_talk_sec=round(total_talk, 1),
        words_per_minute=overall_wpm,
        speaker_word_share=share,
        speaker_segment_counts=seg_counts,
        speaker_talk_sec=talk_sec,
        speaker_wpm=spk_wpm,
    )
