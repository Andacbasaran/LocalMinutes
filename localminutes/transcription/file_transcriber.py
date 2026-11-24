"""Offline audio/video file transcription with live cancellation and optional ffmpeg fallback."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional, Protocol

from localminutes.models import TranscriptSegment

logger = logging.getLogger(__name__)

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


def _transcode_with_ffmpeg(src_path: Path, dst_wav: Path) -> bool:
    """Use system ffmpeg (if installed) to transcode tricky containers to 16 kHz mono WAV."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(src_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(dst_wav),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        return proc.returncode == 0 and dst_wav.exists() and dst_wav.stat().st_size > 44
    except Exception as exc:
        logger.warning("ffmpeg fallback transcode failed: %s", exc)
        return False


def transcribe_media_file(
    file_path: Path | str,
    engine: FileTranscriberEngine,
    meeting_id: int,
    speaker: str = "Recording",
    on_progress: Optional[Callable[[float], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[list[TranscriptSegment], float]:
    """Transcribe a local audio/video file and return `(TranscriptSegments, duration_sec)`."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Media file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_MEDIA_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension: {path.suffix}. "
            f"Supported: {', '.join(SUPPORTED_MEDIA_EXTENSIONS)}"
        )

    if cancel_event and cancel_event.is_set():
        return [], 0.0

    tmp_wav: Optional[Path] = None
    try:
        try:
            raw_segments, duration = engine.transcribe_file_segments(
                path,
                on_progress=on_progress,
                on_status=on_status,
                cancel_event=cancel_event,
            )
        except Exception as primary_exc:
            if cancel_event and cancel_event.is_set():
                return [], 0.0
            # Attempt optional system ffmpeg fallback for tricky codecs/containers
            tmp_dir = Path(tempfile.mkdtemp(prefix="localminutes_ffmpeg_"))
            tmp_wav = tmp_dir / "normalized_16k.wav"
            if on_status:
                on_status("Direct decode failed; transcoding via system ffmpeg...")
            if not _transcode_with_ffmpeg(path, tmp_wav):
                raise primary_exc
            raw_segments, duration = engine.transcribe_file_segments(
                tmp_wav,
                on_progress=on_progress,
                on_status=on_status,
                cancel_event=cancel_event,
            )
    finally:
        if tmp_wav is not None:
            shutil.rmtree(tmp_wav.parent, ignore_errors=True)

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
