"""Offline speech-to-text transcription using faster-whisper (INT8 CPU + VAD)."""

from localminutes.transcription.engine import WhisperEngine, list_cached_models
from localminutes.transcription.file_transcriber import (
    SUPPORTED_MEDIA_EXTENSIONS,
    transcribe_media_file,
)
from localminutes.transcription.live_pipeline import LiveTranscriptionPipeline

__all__ = [
    "LiveTranscriptionPipeline",
    "SUPPORTED_MEDIA_EXTENSIONS",
    "WhisperEngine",
    "list_cached_models",
    "transcribe_media_file",
]
