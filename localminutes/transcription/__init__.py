"""Offline speech-to-text transcription using faster-whisper (INT8 CPU + VAD)."""

from localminutes.transcription.engine import WhisperEngine
from localminutes.transcription.live_pipeline import LiveTranscriptionPipeline

__all__ = ["LiveTranscriptionPipeline", "WhisperEngine"]
