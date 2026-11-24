"""Cross-platform dual-channel audio capture with anti-aliased polyphase 16 kHz resampling."""

from __future__ import annotations

import logging
import math
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from localminutes.audio.devices import (
    find_device_by_index,
    get_default_loopback_device,
    get_default_mic_device,
    get_loopback_setup_hint,
)
from localminutes.models import AudioDevice

try:
    from scipy.signal import resample_poly as _scipy_resample_poly
except ImportError:  # pragma: no cover
    _scipy_resample_poly = None  # type: ignore[assignment]

try:
    import pyaudiowpatch as pyaudio
except Exception:  # pragma: no cover
    pyaudio = None  # type: ignore[assignment]

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - headless CI without PulseAudio/PortAudio server
    sd = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000


def resample_float32_to_16k_mono(
    samples: np.ndarray,
    channels: int,
    sample_rate: int,
    target_rate: int = TARGET_SAMPLE_RATE,
) -> np.ndarray:
    """
    Convert float32 audio (interleaved 1D or shape `(frames, channels)`) to anti-aliased
    16 kHz mono float32 in `[-1.0, 1.0]` using polyphase FIR filtering (`scipy.signal.resample_poly`).
    """
    if samples.size == 0:
        return np.empty(0, dtype=np.float32)

    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 2:
        mono = arr.mean(axis=1) if arr.shape[1] > 1 else arr[:, 0]
    elif channels > 1:
        usable = (len(arr) // channels) * channels
        if usable == 0:
            return np.empty(0, dtype=np.float32)
        mono = arr[:usable].reshape(-1, channels).mean(axis=1)
    else:
        mono = arr

    if sample_rate <= 0 or sample_rate == target_rate or len(mono) == 0:
        return np.clip(mono, -1.0, 1.0).astype(np.float32, copy=False)

    if _scipy_resample_poly is not None:
        g = math.gcd(int(target_rate), int(sample_rate))
        up = max(1, int(target_rate) // g)
        down = max(1, int(sample_rate) // g)
        # Guard against exotic non-standard rates with huge prime ratios
        if up <= 1024 and down <= 1024:
            out = _scipy_resample_poly(mono, up, down).astype(np.float32, copy=False)
            return np.clip(out, -1.0, 1.0)

    # Fallback anti-aliased boxcar pre-filter + decimation/interpolation if scipy unavailable
    if sample_rate > target_rate:
        ratio = max(1, int(round(sample_rate / float(target_rate))))
        if ratio > 1 and len(mono) >= ratio:
            kernel = np.ones(ratio, dtype=np.float32) / float(ratio)
            mono = np.convolve(mono, kernel, mode="same")

    duration = len(mono) / float(sample_rate)
    target_len = max(1, int(round(duration * target_rate)))
    x_old = np.linspace(0.0, 1.0, num=len(mono), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
    return np.clip(np.interp(x_new, x_old, mono), -1.0, 1.0).astype(np.float32)


def resample_to_16k_mono(
    pcm_int16: bytes,
    channels: int,
    sample_rate: int,
    target_rate: int = TARGET_SAMPLE_RATE,
) -> np.ndarray:
    """Convert raw int16 interleaved PCM bytes to anti-aliased 16 kHz mono float32 in [-1.0, 1.0]."""
    if not pcm_int16:
        return np.empty(0, dtype=np.float32)
    samples = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
    return resample_float32_to_16k_mono(
        samples=samples,
        channels=channels,
        sample_rate=sample_rate,
        target_rate=target_rate,
    )


class DualAudioCapture:
    """
    Cross-platform concurrent dual-channel audio capture:
      - Microphone channel (default speaker label: 'You')
      - System loopback channel (default speaker label: 'Remote')
    Supports Windows WASAPI (`pyaudiowpatch`), macOS CoreAudio + BlackHole (`sounddevice`),
    and Linux PipeWire/PulseAudio `.monitor` (`sounddevice`), with clean single-channel mic
    fallback and continuous `time_offset_sec` support for resumed meetings.
    """

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
        time_offset_sec: float = 0.0,
        mic_speaker: str = "You",
        loopback_speaker: str = "Remote",
    ) -> None:
        self._on_audio = on_audio
        self._on_level = on_level
        self._on_error = on_error
        self._mic_device_index = mic_device_index
        self._loopback_device_index = loopback_device_index
        self._capture_mic = capture_mic
        self._capture_loopback = capture_loopback
        self._wav_dir = wav_dir
        self._time_offset_sec = max(0.0, float(time_offset_sec))
        self._mic_speaker = mic_speaker
        self._loopback_speaker = loopback_speaker

        self._pa = None
        self._pa_streams: list[object] = []
        self._sd_streams: list[object] = []
        self._wav_files: dict[str, wave.Wave_write] = {}
        self._running = False
        self._paused = False
        self._start_monotonic: float = 0.0
        self._pause_started: float = 0.0
        self._paused_total: float = 0.0
        self._lock = threading.Lock()
        self.active_channels: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def elapsed_seconds(self) -> float:
        """Return total meeting elapsed seconds including any `time_offset_sec` from prior sessions."""
        if not self._running:
            return self._time_offset_sec
        now = self._pause_started if self._paused else time.monotonic()
        session_elapsed = max(0.0, now - self._start_monotonic - self._paused_total)
        return self._time_offset_sec + session_elapsed

    def start(self) -> None:
        if pyaudio is None and sd is None:
            raise RuntimeError(
                "No audio capture backend installed. Install 'sounddevice' (macOS/Linux/Windows) "
                "or 'pyaudiowpatch' (Windows WASAPI)."
            )
        if self._running:
            return

        self._pa_streams = []
        self._sd_streams = []
        self._wav_files = {}
        self.active_channels = []
        self._start_monotonic = time.monotonic()
        self._paused_total = 0.0
        self._paused = False
        self._running = True

        warnings: list[str] = []

        if self._capture_mic:
            try:
                mic_dev = (
                    find_device_by_index(self._mic_device_index, is_loopback=False)
                    if self._mic_device_index is not None
                    else get_default_mic_device()
                )
                if mic_dev is not None:
                    self._open_device_stream(mic_dev, speaker=self._mic_speaker)
                    self.active_channels.append(self._mic_speaker)
                else:
                    warnings.append("No default microphone device detected.")
            except Exception as exc:
                warnings.append(f"Microphone failed to open: {exc}")

        if self._capture_loopback:
            try:
                lb_dev = (
                    find_device_by_index(self._loopback_device_index, is_loopback=True)
                    if self._loopback_device_index is not None
                    else get_default_loopback_device()
                )
                if lb_dev is not None:
                    self._open_device_stream(lb_dev, speaker=self._loopback_speaker)
                    self.active_channels.append(self._loopback_speaker)
                else:
                    warnings.append(get_loopback_setup_hint())
            except Exception as exc:
                warnings.append(f"System loopback failed to open: {exc}")

        if not self.active_channels:
            self.stop()
            raise RuntimeError("Could not start any audio input channel. " + " ".join(warnings))

        if warnings and self._on_error:
            self._on_error(" | ".join(warnings))

    def _prepare_wav_writer(self, speaker: str) -> None:
        if self._wav_dir is None:
            return
        self._wav_dir.mkdir(parents=True, exist_ok=True)
        fname = "mic.wav" if speaker == self._mic_speaker else "system.wav"
        target = self._wav_dir / fname
        # If resuming into an existing directory, avoid overwriting earlier session audio
        if target.exists():
            stamp = int(time.time())
            target = self._wav_dir / f"{target.stem}_{stamp}.wav"
        wf = wave.open(str(target), "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TARGET_SAMPLE_RATE)
        self._wav_files[speaker] = wf

    def _emit_audio_16k(self, speaker: str, audio_16k: np.ndarray) -> None:
        if len(audio_16k) == 0:
            return
        rms = float(np.sqrt(np.mean(audio_16k * audio_16k)))
        if self._on_level:
            self._on_level(speaker, min(1.0, rms * 6.5))
        if speaker in self._wav_files:
            pcm_out = np.clip(audio_16k * 32767.0, -32768, 32767).astype(np.int16)
            self._wav_files[speaker].writeframes(pcm_out.tobytes())
        self._on_audio(speaker, audio_16k, self.elapsed_seconds)

    def _open_device_stream(self, device: AudioDevice, speaker: str) -> None:
        self._prepare_wav_writer(speaker)
        if device.backend == "pyaudiowpatch" and pyaudio is not None:
            self._open_pyaudio_stream(device, speaker)
        elif sd is not None:
            self._open_sounddevice_stream(device, speaker)
        else:
            raise RuntimeError(f"Audio backend '{device.backend}' is unavailable.")

    def _open_pyaudio_stream(self, device: AudioDevice, speaker: str) -> None:
        assert pyaudio is not None
        if self._pa is None:
            self._pa = pyaudio.PyAudio()
        info = self._pa.get_device_info_by_index(device.index)
        sample_rate = int(info["defaultSampleRate"])
        channels = max(1, min(2, int(info["maxInputChannels"])))
        frames_per_buffer = max(512, int(sample_rate * 0.05))

        def _callback(in_data, _frame_count, _time_info, _status_flags):
            if not self._running:
                return (None, pyaudio.paComplete)
            if self._paused or not in_data:
                if self._on_level:
                    self._on_level(speaker, 0.0)
                return (None, pyaudio.paContinue)
            try:
                audio_16k = resample_to_16k_mono(in_data, channels, sample_rate)
                self._emit_audio_16k(speaker, audio_16k)
            except Exception as exc:
                logger.exception("PyAudio callback error (%s): %s", speaker, exc)
            return (None, pyaudio.paContinue)

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=device.index,
            frames_per_buffer=frames_per_buffer,
            stream_callback=_callback,
        )
        stream.start_stream()
        self._pa_streams.append(stream)

    def _open_sounddevice_stream(self, device: AudioDevice, speaker: str) -> None:
        assert sd is not None
        sample_rate = max(8_000, int(device.default_sample_rate or 48_000))
        channels = max(1, min(2, int(device.channels or 1)))
        blocksize = max(512, int(sample_rate * 0.05))

        def _callback(indata, _frames, _time_info, status):
            if status:
                logger.debug("sounddevice status (%s): %s", speaker, status)
            if not self._running:
                return
            if self._paused or indata is None or len(indata) == 0:
                if self._on_level:
                    self._on_level(speaker, 0.0)
                return
            try:
                audio_16k = resample_float32_to_16k_mono(indata, channels, sample_rate)
                self._emit_audio_16k(speaker, audio_16k)
            except Exception as exc:
                logger.exception("sounddevice callback error (%s): %s", speaker, exc)

        stream = sd.InputStream(
            device=device.index,
            channels=channels,
            samplerate=sample_rate,
            blocksize=blocksize,
            dtype="float32",
            callback=_callback,
        )
        stream.start()
        self._sd_streams.append(stream)

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

        for stream in self._pa_streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        self._pa_streams.clear()

        for stream in self._sd_streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._sd_streams.clear()

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
