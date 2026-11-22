"""Unit tests for media file transcription and meeting analytics."""

from pathlib import Path

import pytest

from localminutes.analytics import compute_meeting_stats
from localminutes.models import TranscriptSegment
from localminutes.transcription.file_transcriber import transcribe_media_file


class _FakeFileEngine:
    def transcribe_file_segments(
        self, file_path, on_progress=None, on_status=None, cancel_event=None
    ):
        if on_status:
            on_status("fake loading")
        if on_progress:
            on_progress(0.5)
            on_progress(1.0)
        return [(0.0, 3.5, "Merhaba dünya."), (4.0, 8.2, "Bu bir test kaydıdır.")], 10.0


def test_transcribe_media_file_and_validation(tmp_path: Path) -> None:
    audio_file = tmp_path / "ders.mp3"
    audio_file.write_bytes(b"fake-mp3-data")

    progress_values: list[float] = []
    segments, dur = transcribe_media_file(
        audio_file,
        engine=_FakeFileEngine(),
        meeting_id=7,
        speaker="Kayıt",
        on_progress=progress_values.append,
    )
    assert dur == 10.0
    assert len(segments) == 2
    assert segments[0].meeting_id == 7
    assert segments[0].speaker == "Kayıt"
    assert progress_values[-1] == 1.0

    bad_file = tmp_path / "notes.pdf"
    bad_file.write_bytes(b"pdf")
    with pytest.raises(ValueError):
        transcribe_media_file(bad_file, engine=_FakeFileEngine(), meeting_id=7)


def test_compute_meeting_stats() -> None:
    segs = [
        TranscriptSegment(speaker="Sen", text="bir iki üç dört", is_bookmarked=True),
        TranscriptSegment(speaker="Karşı Taraf", text="beş altı yedi sekiz dokuz on"),
    ]
    stats = compute_meeting_stats(segs)
    assert stats.total_segments == 2
    assert stats.total_words == 10
    assert stats.bookmarked_count == 1
    assert stats.speaker_word_share["Sen"] == 40.0
    assert stats.speaker_word_share["Karşı Taraf"] == 60.0
