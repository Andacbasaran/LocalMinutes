"""Real-time dual-channel speech endpointing and transcription pipeline."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

import numpy as np

from localminutes.models import TranscriptSegment

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000


class TranscriberProtocol(Protocol):
    def load(self, on_status: Optional[Callable[[str], None]] = None) -> None: ...
    def transcribe_chunk(self, audio_16k: np.ndarray) -> str: ...


@dataclass
class _ChannelBuffer:
    chunks: list[np.ndarray] = field(default_factory=list)
    total_samples: int = 0
    speech_detected: bool = False
    silence_samples: int = 0
    start_sec: float = 0.0
    last_sec: float = 0.0

    def reset(self) -> None:
        self.chunks.clear()
        self.total_samples = 0
        self.speech_detected = False
        self.silence_samples = 0
        self.start_sec = 0.0
        self.last_sec = 0.0


class LiveTranscriptionPipeline:
    """Buffers dual-channel audio, detects speech endpoints, and transcribes asynchronously."""

    def __init__(
        self,
        engine: TranscriberProtocol,
        on_segment: Callable[[TranscriptSegment], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        meeting_id: Optional[int] = None,
        energy_threshold: float = 0.008,
        vad_silence_ms: int = 800,
        chunk_max_sec: float = 12.0,
        min_speech_sec: float = 0.45,
    ) -> None:
        self._engine = engine
        self._on_segment = on_segment
        self._on_status = on_status
        self._on_error = on_error
        self.meeting_id = meeting_id

        self._energy_threshold = energy_threshold
        self._silence_limit_samples = int(SAMPLE_RATE * (vad_silence_ms / 1000.0))
        self._max_samples = int(SAMPLE_RATE * chunk_max_sec)
        self._min_samples = int(SAMPLE_RATE * min_speech_sec)

        self._buffers: dict[str, _ChannelBuffer] = {
            "Sen": _ChannelBuffer(),
            "Karşı Taraf": _ChannelBuffer(),
        }
        self._buf_lock = threading.Lock()
        self._queue: queue.Queue[Optional[tuple[str, np.ndarray, float, float]]] = queue.Queue(
            maxsize=64
        )
        self._worker: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="WhisperWorker")
        self._worker.start()

    def push_audio(self, speaker: str, audio_16k: np.ndarray, current_sec: float) -> None:
        """Feed a 16 kHz mono float32 frame from either 'Sen' or 'Karşı Taraf'."""
        if not self._running or len(audio_16k) == 0:
            return

        rms = float(np.sqrt(np.mean(audio_16k * audio_16k)))
        is_speech = rms >= self._energy_threshold
        chunk_dur = len(audio_16k) / float(SAMPLE_RATE)

        ready_payload: Optional[tuple[str, np.ndarray, float, float]] = None

        with self._buf_lock:
            buf = self._buffers.setdefault(speaker, _ChannelBuffer())

            if is_speech:
                if not buf.speech_detected:
                    buf.speech_detected = True
                    buf.start_sec = max(0.0, current_sec - chunk_dur)
                buf.chunks.append(audio_16k.copy())
                buf.total_samples += len(audio_16k)
                buf.silence_samples = 0
                buf.last_sec = current_sec
            elif buf.speech_detected:
                buf.chunks.append(audio_16k.copy())
                buf.total_samples += len(audio_16k)
                buf.silence_samples += len(audio_16k)
                buf.last_sec = current_sec

            if buf.speech_detected and (
                buf.silence_samples >= self._silence_limit_samples
                or buf.total_samples >= self._max_samples
            ):
                if buf.total_samples >= self._min_samples:
                    audio_concat = np.concatenate(buf.chunks)
                    ready_payload = (speaker, audio_concat, buf.start_sec, buf.last_sec)
                buf.reset()

        if ready_payload is not None:
            self._enqueue(ready_payload)

    def _enqueue(self, item: tuple[str, np.ndarray, float, float]) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            logger.warning("Transcription queue full; dropping oldest chunk.")
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(item)

    def flush_all(self) -> None:
        """Flush any remaining speech buffers into the transcription queue."""
        to_flush: list[tuple[str, np.ndarray, float, float]] = []
        with self._buf_lock:
            for speaker, buf in self._buffers.items():
                if buf.speech_detected and buf.total_samples >= self._min_samples:
                    to_flush.append((speaker, np.concatenate(buf.chunks), buf.start_sec, buf.last_sec))
                buf.reset()
        for item in to_flush:
            self._enqueue(item)

    def stop(self, wait_timeout: float = 15.0) -> None:
        if not self._running:
            return
        self.flush_all()
        self._running = False
        self._queue.put(None)
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=wait_timeout)
        self._worker = None

    def _worker_loop(self) -> None:
        try:
            self._engine.load(on_status=self._on_status)
        except Exception as exc:
            logger.exception("Whisper model load failed: %s", exc)
            if self._on_error:
                self._on_error(f"Whisper modeli yüklenemedi: {exc}")
            return

        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            speaker, audio_16k, start_sec, end_sec = item
            try:
                text = self._engine.transcribe_chunk(audio_16k)
                if text:
                    segment = TranscriptSegment(
                        meeting_id=self.meeting_id,
                        speaker=speaker,
                        text=text,
                        start_sec=round(start_sec, 2),
                        end_sec=round(max(end_sec, start_sec + 0.5), 2),
                    )
                    self._on_segment(segment)
            except Exception as exc:
                logger.exception("Transcription error: %s", exc)
                if self._on_error:
                    self._on_error(f"Deşifre hatası: {exc}")
            finally:
                self._queue.task_done()
