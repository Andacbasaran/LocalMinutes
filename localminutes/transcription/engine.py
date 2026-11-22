"""faster-whisper INT8 CPU + VAD transcription engine and local model cache helpers."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from localminutes.config import get_models_dir

logger = logging.getLogger(__name__)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo"]

# Common Whisper silence hallucinations to filter out
_HALLUCINATION_PHRASES = {
    "altyazı",
    "izlediğiniz için teşekkürler",
    "izlediğiniz için teşekkür ederim",
    "abone olmayı unutmayın",
    "thanks for watching",
    "thank you for watching",
    "you",
    ".",
    "...",
}


def list_cached_models(download_root: Optional[Path] = None) -> set[str]:
    """Return set of Whisper model names already present in the local cache directory."""
    root = download_root or get_models_dir()
    if not root.exists():
        return set()
    cached: set[str] = set()
    entries = [p.name.lower() for p in root.iterdir()]
    for model_name in WHISPER_MODELS:
        token = model_name.lower()
        if any(token in name for name in entries):
            cached.add(model_name)
    return cached


class WhisperEngine:
    """Thread-safe wrapper around faster-whisper WhisperModel (CPU INT8 + Silero VAD)."""

    def __init__(
        self,
        model_size: str = "small",
        compute_type: str = "int8",
        language: str = "tr",
        download_root: Optional[Path] = None,
    ) -> None:
        self.model_size = model_size
        self.compute_type = compute_type
        self.language = None if language in ("", "auto", None) else language
        self.download_root = download_root or get_models_dir()
        self._model = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, on_status: Optional[Callable[[str], None]] = None) -> None:
        with self._lock:
            if self._model is not None:
                return
            if on_status:
                on_status(f"Whisper modeli yükleniyor ({self.model_size}, {self.compute_type})...")
            from faster_whisper import WhisperModel

            cpu_threads = max(2, min(8, (os.cpu_count() or 4)))
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type=self.compute_type,
                cpu_threads=cpu_threads,
                download_root=str(self.download_root),
            )
            if on_status:
                on_status(f"Whisper modeli hazır ({self.model_size}).")

    def transcribe_chunk(self, audio_16k: np.ndarray) -> str:
        """Transcribe a 16 kHz mono float32 audio array and return clean text."""
        if len(audio_16k) < 1600:  # < 100ms
            return ""
        if self._model is None:
            self.load()

        with self._lock:
            assert self._model is not None
            segments, _info = self._model.transcribe(
                audio_16k,
                language=self.language,
                beam_size=1,
                best_of=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            texts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]

        joined = " ".join(texts).strip()
        if not joined:
            return ""
        if joined.lower().strip(" .!?,") in _HALLUCINATION_PHRASES:
            return ""
        return joined

    def transcribe_file_segments(
        self,
        file_path: Path | str,
        on_progress: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> tuple[list[tuple[float, float, str]], float]:
        """Transcribe an audio/video file, yielding timestamped (start, end, text) tuples + duration."""
        if self._model is None:
            self.load(on_status=on_status)

        results: list[tuple[float, float, str]] = []
        with self._lock:
            assert self._model is not None
            seg_iter, info = self._model.transcribe(
                str(file_path),
                language=self.language,
                beam_size=2,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=True,
            )
            duration = float(getattr(info, "duration", 0.0) or 0.0)
            for seg in seg_iter:
                if cancel_event and cancel_event.is_set():
                    break
                text = (seg.text or "").strip()
                if text and text.lower().strip(" .!?,") not in _HALLUCINATION_PHRASES:
                    results.append((round(float(seg.start), 2), round(float(seg.end), 2), text))
                if on_progress and duration > 0:
                    on_progress(min(1.0, float(seg.end) / duration))

        if on_progress and not (cancel_event and cancel_event.is_set()):
            on_progress(1.0)
        return results, duration
