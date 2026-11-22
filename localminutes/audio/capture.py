"""Dual-channel Windows WASAPI loopback + microphone audio capture."""

from __future__ import annotations

import logging
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from localminutes.audio.devices import get_default_loopback_device, get_default_mic_device

try:
    import pyaudiowpatch as pyaudio
except ImportError:  # pragma: no cover
    pyaudio = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000


def resample_to_16k_mono(
    pcm_int16: bytes,
    channels: int,
    sample_rate: int,
    target_rate: int = TARGET_SAMPLE_RATE,
) -> np.ndarray:
    """Convert raw int16 interleaved PCM bytes to 16 kHz mono float32 in [-1.0, 1.0]."""
    if not pcm_int16:
        return np.empty(0, dtype=np.float32)

    samples = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        usable = (len(samples) // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)

    if sample_rate == target_rate or len(samples) == 0:
        return samples.astype(np.float32, copy=False)

    duration = len(samples) / float(sample_rate)
    target_len = max(1, int(round(duration * target_rate)))
    x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


class DualAudioCapture:
    """Captures microphone ('Sen') and WASAPI loopback ('Karşı Taraf') concurrently."""

    def __init__(
        self,
        on_audio: Callable[[str, np.ndarray, float], None],
        on_level: Optional[Callable[[str, float], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        mic_device_index: Optional[int] = None,
        loopback_device_index: Optional[int] = None,
        capture_mic: bool = True,
        capture_loopback: bool = True,
        wav_dir: Optional[Path] = None,
    ) -> None:
        self._on_audio = on_audio
        self._on_level = on_level
        self._on_error = on_error
        self._mic_device_index = mic_device_index
        self._loopback_device_index = loopback_device_index
        self._capture_mic = capture_mic
        self._capture_loopback = capture_loopback
        self._wav_dir = wav_dir

        self._pa = None
        self._streams: list[object] = []
        self._wav_files: dict[str, wave.Wave_write] = {}
        self._running = False
        self._paused = False
        self._start_monotonic: float = 0.0
        self._pause_started: float = 0.0
        self._paused_total: float = 0.0
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def elapsed_seconds(self) -> float:
        if not self._running:
            return 0.0
        now = self._pause_started if self._paused else time.monotonic()
        return max(0.0, now - self._start_monotonic - self._paused_total)

    def start(self) -> None:
        if pyaudio is None:
            raise RuntimeError("pyaudiowpatch yüklü değil. Lütfen 'pip install pyaudiowpatch' çalıştırın.")
        if self._running:
            return

        self._pa = pyaudio.PyAudio()
        self._streams = []
        self._wav_files = {}
        self._start_monotonic = time.monotonic()
        self._paused_total = 0.0
        self._paused = False
        self._running = True

        started_any = False
        errors: list[str] = []

        if self._capture_mic:
            try:
                mic_idx = self._mic_device_index
                if mic_idx is None:
                    default_mic = get_default_mic_device()
                    mic_idx = default_mic.index if default_mic else None
                if mic_idx is not None:
                    self._open_stream(mic_idx, speaker="Sen")
                    started_any = True
                else:
                    errors.append("Varsayılan mikrofon bulunamadı.")
            except Exception as exc:
                errors.append(f"Mikrofon açılamadı: {exc}")

        if self._capture_loopback:
            try:
                lb_idx = self._loopback_device_index
                if lb_idx is None:
                    default_lb = get_default_loopback_device()
                    lb_idx = default_lb.index if default_lb else None
                if lb_idx is not None:
                    self._open_stream(lb_idx, speaker="Karşı Taraf")
                    started_any = True
                else:
                    errors.append("Varsayılan WASAPI loopback cihazı bulunamadı.")
            except Exception as exc:
                errors.append(f"Sistem sesi (loopback) açılamadı: {exc}")

        if not started_any:
            self.stop()
            raise RuntimeError("Hiçbir ses kanalı başlatılamadı. " + " ".join(errors))

        if errors and self._on_error:
            self._on_error(" | ".join(errors))

    def _open_stream(self, device_index: int, speaker: str) -> None:
        assert self._pa is not None
        info = self._pa.get_device_info_by_index(device_index)
        sample_rate = int(info["defaultSampleRate"])
        channels = max(1, min(2, int(info["maxInputChannels"])))
        frames_per_buffer = max(512, int(sample_rate * 0.05))  # ~50 ms

        if self._wav_dir is not None:
            self._wav_dir.mkdir(parents=True, exist_ok=True)
            fname = "mic.wav" if speaker == "Sen" else "system.wav"
            wf = wave.open(str(self._wav_dir / fname), "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TARGET_SAMPLE_RATE)
            self._wav_files[speaker] = wf

        def _callback(in_data, frame_count, time_info, status_flags):
            if not self._running:
                return (None, pyaudio.paComplete)
            if self._paused or not in_data:
                if self._on_level:
                    self._on_level(speaker, 0.0)
                return (None, pyaudio.paContinue)

            try:
                audio_16k = resample_to_16k_mono(in_data, channels, sample_rate)
                if len(audio_16k) > 0:
                    rms = float(np.sqrt(np.mean(audio_16k * audio_16k)))
                    if self._on_level:
                        # Normalize softly for visual meter [0.0, 1.0]
                        self._on_level(speaker, min(1.0, rms * 6.0))
                    if speaker in self._wav_files:
                        pcm_out = np.clip(audio_16k * 32767.0, -32768, 32767).astype(np.int16)
                        self._wav_files[speaker].writeframes(pcm_out.tobytes())
                    self._on_audio(speaker, audio_16k, self.elapsed_seconds)
            except Exception as exc:
                logger.exception("Audio callback error (%s): %s", speaker, exc)
            return (None, pyaudio.paContinue)

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=frames_per_buffer,
            stream_callback=_callback,
        )
        stream.start_stream()
        self._streams.append(stream)

    def pause(self) -> None:
        with self._lock:
            if self._running and not self._paused:
                self._paused = True
                self._pause_started = time.monotonic()

    def resume(self) -> None:
        with self._lock:
            if self._running and self._paused:
                self._paused_total += time.monotonic() - self._pause_started
                self._paused = False

    def stop(self) -> None:
        self._running = False
        self._paused = False
        for stream in self._streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        self._streams.clear()

        for wf in self._wav_files.values():
            try:
                wf.close()
            except Exception:
                pass
        self._wav_files.clear()

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
