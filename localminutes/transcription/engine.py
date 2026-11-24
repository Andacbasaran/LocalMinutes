"""faster-whisper CPU INT8 + Silero VAD transcription engine with CTranslate2 probing & cache manager."""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from localminutes.config import get_models_dir
from localminutes.hardware import (
    get_ct2_safe_path,
    query_ct2_supported_compute_types,
    select_compute_type_candidates,
)

logger = logging.getLogger(__name__)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo"]

# Approximate disk footprint for UX guidance when not yet downloaded
WHISPER_MODEL_APPROX_MB: dict[str, int] = {
    "tiny": 75,
    "base": 145,
    "small": 485,
    "medium": 1520,
    "large-v3-turbo": 1620,
}

# Exact HuggingFace repo directory prefixes created by faster-whisper
_MODEL_REPO_SUFFIXES: dict[str, tuple[str, ...]] = {
    "tiny": ("faster-whisper-tiny", "whisper-tiny"),
    "base": ("faster-whisper-base", "whisper-base"),
    "small": ("faster-whisper-small", "whisper-small"),
    "medium": ("faster-whisper-medium", "whisper-medium"),
    "large-v3-turbo": ("faster-whisper-large-v3-turbo", "whisper-large-v3-turbo"),
}

# Common Whisper silence hallucinations to suppress
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


def _match_cached_model_paths(model_name: str, root: Path) -> list[Path]:
    """Return exact cache directories matching `model_name` without substring false positives."""
    if not root.exists():
        return []
    key = model_name.strip().lower()
    suffixes = _MODEL_REPO_SUFFIXES.get(key, (f"faster-whisper-{key}", key))
    matched: list[Path] = []

    for entry in root.iterdir():
        name_low = entry.name.lower()
        if name_low == key:
            matched.append(entry)
            continue
        for suffix in suffixes:
            if name_low == suffix or name_low.endswith(f"--{suffix}"):
                matched.append(entry)
                break
    return matched


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def list_cached_models(download_root: Optional[Path] = None) -> set[str]:
    """Return exact set of Whisper model names currently present in the local cache directory."""
    root = download_root or get_models_dir()
    cached: set[str] = set()
    for model_name in WHISPER_MODELS:
        paths = _match_cached_model_paths(model_name, root)
        if any(_dir_size_bytes(p) > 0 for p in paths):
            cached.add(model_name)
    return cached


def get_cached_model_info(download_root: Optional[Path] = None) -> dict[str, dict[str, object]]:
    """Return per-model cache status, exact disk size in MB, and approximate download size."""
    root = download_root or get_models_dir()
    info: dict[str, dict[str, object]] = {}
    for model_name in WHISPER_MODELS:
        paths = _match_cached_model_paths(model_name, root)
        total_bytes = sum(_dir_size_bytes(p) for p in paths)
        info[model_name] = {
            "cached": total_bytes > 0,
            "size_mb": round(total_bytes / (1024.0 * 1024.0), 1) if total_bytes > 0 else 0.0,
            "approx_mb": WHISPER_MODEL_APPROX_MB.get(model_name, 500),
            "paths": paths,
        }
    return info


def delete_cached_model(model_name: str, download_root: Optional[Path] = None) -> bool:
    """Delete cached directories for `model_name`. Returns True if anything was removed."""
    root = download_root or get_models_dir()
    paths = _match_cached_model_paths(model_name, root)
    removed = False
    for path in paths:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            removed = True
        except OSError as exc:
            logger.warning("Could not delete cached model path %s: %s", path, exc)
    return removed


class WhisperEngine:
    """Thread-safe wrapper around faster-whisper (adaptive CPU CTranslate2 + Silero VAD + custom vocab)."""

    def __init__(
        self,
        model_size: str = "small",
        compute_type: str = "int8",
        language: str = "auto",
        download_root: Optional[Path] = None,
        initial_prompt: str = "",
        cpu_threads: Optional[int] = None,
    ) -> None:
        self.model_size = model_size
        self.compute_type = compute_type
        self.active_compute_type = compute_type
        self.language = None if language in ("", "auto", None) else language
        self.download_root = download_root or get_models_dir()
        self.initial_prompt = (initial_prompt or "").strip()
        self.cpu_threads = cpu_threads or max(2, min(8, (os.cpu_count() or 4)))
        self._model = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, on_status: Optional[Callable[[str], None]] = None) -> None:
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            supported = query_ct2_supported_compute_types()
            candidates = select_compute_type_candidates(
                preferred=self.compute_type,
                supported_types=supported,
            )
            safe_root = get_ct2_safe_path(str(self.download_root))
            last_exc: Optional[Exception] = None

            for ctype in candidates:
                try:
                    if on_status:
                        on_status(f"Loading Whisper model ({self.model_size}, {ctype.upper()})...")
                    self._model = WhisperModel(
                        self.model_size,
                        device="cpu",
                        compute_type=ctype,
                        cpu_threads=self.cpu_threads,
                        download_root=safe_root,
                    )
                    self.active_compute_type = ctype
                    if on_status:
                        on_status(f"Whisper ready ({self.model_size}, {ctype.upper()}).")
                    return
                except Exception as exc:
                    last_exc = exc
                    logger.warning("Whisper load failed with compute_type=%s: %s", ctype, exc)

            raise RuntimeError(
                f"Failed to load Whisper '{self.model_size}' across compute types {candidates}: {last_exc}"
            ) from last_exc

    def transcribe_chunk(self, audio_16k: np.ndarray) -> str:
        """Transcribe a 16 kHz mono float32 audio array and return clean text."""
        if len(audio_16k) < 1600:  # < 100ms
            return ""
        if self._model is None:
            self.load()

        with self._lock:
            assert self._model is not None
            kwargs = {
                "language": self.language,
                "beam_size": 1,
                "best_of": 1,
                "vad_filter": True,
                "vad_parameters": {"min_silence_duration_ms": 400},
                "condition_on_previous_text": False,
                "without_timestamps": True,
            }
            if self.initial_prompt:
                kwargs["initial_prompt"] = self.initial_prompt
            segments, _info = self._model.transcribe(audio_16k, **kwargs)
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
        """Transcribe an audio/video file, yielding timestamped `(start, end, text)` tuples + duration."""
        if self._model is None:
            self.load(on_status=on_status)

        results: list[tuple[float, float, str]] = []
        with self._lock:
            assert self._model is not None
            kwargs = {
                "language": self.language,
                "beam_size": 2,
                "vad_filter": True,
                "vad_parameters": {"min_silence_duration_ms": 500},
                "condition_on_previous_text": True,
            }
            if self.initial_prompt:
                kwargs["initial_prompt"] = self.initial_prompt
            seg_iter, info = self._model.transcribe(str(file_path), **kwargs)
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
