"""Offline audio/video file transcription into timestamped TranscriptSegments."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional, Protocol

from localminutes.models import TranscriptSegment

SUPPORTED_MEDIA_EXTENSIONS = (
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".flac",
    ".aac",
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
)


class FileTranscriberEngine(Protocol):
    def transcribe_file_segments(
        self,
        file_path: Path | str,
        on_progress: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> tuple[list[tuple[float, float, str]], float]: ...


def transcribe_media_file(
    file_path: Path | str,
    engine: FileTranscriberEngine,
    meeting_id: int,
    speaker: str = "Kayıt",
    on_progress: Optional[Callable[[float], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[list[TranscriptSegment], float]:
    """Transcribe a local audio/video file and return TranscriptSegment list + duration_sec."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {path}")
    if path.suffix.lower() not in SUPPORTED_MEDIA_EXTENSIONS:
        raise ValueError(
            f"Desteklenmeyen dosya uzantısı: {path.suffix}. "
            f"Desteklenenler: {', '.join(SUPPORTED_MEDIA_EXTENSIONS)}"
        )

    raw_segments, duration = engine.transcribe_file_segments(
        path,
        on_progress=on_progress,
        on_status=on_status,
        cancel_event=cancel_event,
    )

    segments = [
        TranscriptSegment(
            meeting_id=meeting_id,
            speaker=speaker,
            text=text,
            start_sec=start_sec,
            end_sec=end_sec,
        )
        for start_sec, end_sec, text in raw_segments
    ]
    return segments, duration
