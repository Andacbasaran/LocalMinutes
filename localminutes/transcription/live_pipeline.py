"""Real-time dual-channel speech endpointing and asynchronous transcription pipeline."""

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
        time_offset_sec: float = 0.0,
        queue_maxsize: int = 64,
    ) -> None:
        self._engine = engine
        self._on_segment = on_segment
        self._on_status = on_status
        self._on_error = on_error
        self.meeting_id = meeting_id
        self._time_offset_sec = max(0.0, float(time_offset_sec))

        self._energy_threshold = energy_threshold
        self._silence_limit_samples = int(SAMPLE_RATE * (vad_silence_ms / 1000.0))
        self._max_samples = int(SAMPLE_RATE * chunk_max_sec)
        self._min_samples = int(SAMPLE_RATE * min_speech_sec)

        self._buffers: dict[str, _ChannelBuffer] = {}
        self._buf_lock = threading.Lock()
        self._queue: queue.Queue[Optional[tuple[str, np.ndarray, float, float]]] = queue.Queue(
            maxsize=max(1, int(queue_maxsize))
        )
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self.dropped_chunks: int = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="WhisperWorker")
        self._worker.start()

    def push_audio(self, speaker: str, audio_16k: np.ndarray, current_sec: float) -> None:
        """Feed a 16 kHz mono float32 frame from any speaker channel."""
        if not self._running or len(audio_16k) == 0:
            return

        effective_sec = max(0.0, float(current_sec)) + self._time_offset_sec
        rms = float(np.sqrt(np.mean(audio_16k * audio_16k)))
        is_speech = rms >= self._energy_threshold
        chunk_dur = len(audio_16k) / float(SAMPLE_RATE)

        ready_payload: Optional[tuple[str, np.ndarray, float, float]] = None

        with self._buf_lock:
            buf = self._buffers.setdefault(speaker, _ChannelBuffer())

            if is_speech:
                if not buf.speech_detected:
                    buf.speech_detected = True
                    buf.start_sec = max(self._time_offset_sec, effective_sec - chunk_dur)
                buf.chunks.append(audio_16k.copy())
                buf.total_samples += len(audio_16k)
                buf.silence_samples = 0
                buf.last_sec = effective_sec
            elif buf.speech_detected:
                buf.chunks.append(audio_16k.copy())
                buf.total_samples += len(audio_16k)
                buf.silence_samples += len(audio_16k)
                buf.last_sec = effective_sec

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
            self.dropped_chunks += 1
            logger.warning("Transcription queue full; dropping oldest chunk (dropped=%d).", self.dropped_chunks)
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except (queue.Empty, ValueError):
                pass
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self.dropped_chunks += 1

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
        self._running = False
        self.flush_all()
        worker = self._worker
        if worker is not None and worker.is_alive():
            # Guarantee sentinel fits even if queue is completely saturated
            try:
                self._queue.put(None, timeout=1.0)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except (queue.Empty, ValueError):
                    pass
                if worker.is_alive():
                    try:
                        self._queue.put(None, timeout=1.0)
                    except queue.Full:
                        pass
            worker.join(timeout=wait_timeout)
        self._worker = None

    def _worker_loop(self) -> None:
        try:
            self._engine.load(on_status=self._on_status)
        except Exception as exc:
            logger.exception("Whisper model load failed: %s", exc)
            if self._on_error:
                self._on_error(f"Whisper model failed to load: {exc}")
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
                    self._on_error(f"Transcription error: {exc}")
            finally:
                self._queue.task_done()
