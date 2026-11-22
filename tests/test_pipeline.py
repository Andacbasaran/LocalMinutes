"""Unit tests for audio resampling and dual-channel live transcription pipeline."""

import numpy as np

from localminutes.audio.capture import resample_to_16k_mono
from localminutes.models import TranscriptSegment
from localminutes.transcription.live_pipeline import LiveTranscriptionPipeline


class _FakeEngine:
    def load(self, on_status=None) -> None:
        if on_status:
            on_status("Fake ready")

    def transcribe_chunk(self, audio_16k: np.ndarray) -> str:
        return f"chunk({len(audio_16k)})"


def test_resample_to_16k_mono() -> None:
    # 1 second of 48 kHz stereo sine wave
    sr = 48_000
    t = np.linspace(0.0, 1.0, sr, endpoint=False)
    mono = (0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    stereo = np.column_stack([mono, mono]).ravel()

    out = resample_to_16k_mono(stereo.tobytes(), channels=2, sample_rate=sr)
    assert out.dtype == np.float32
    assert abs(len(out) - 16_000) <= 2
    assert np.max(np.abs(out)) <= 1.0


def test_live_pipeline_dual_channel_endpointing() -> None:
    received: list[TranscriptSegment] = []
    pipeline = LiveTranscriptionPipeline(
        engine=_FakeEngine(),
        on_segment=received.append,
        meeting_id=42,
        energy_threshold=0.01,
        vad_silence_ms=300,
        chunk_max_sec=5.0,
        min_speech_sec=0.2,
    )
    pipeline.start()
    try:
        # 0.5s speech on "Sen" + 0.4s silence -> triggers endpoint
        speech = np.full(8_000, 0.2, dtype=np.float32)
        silence = np.zeros(6_400, dtype=np.float32)
        pipeline.push_audio("Sen", speech, current_sec=0.5)
        pipeline.push_audio("Sen", silence, current_sec=0.9)

        # 0.5s speech on "Karşı Taraf" without trailing silence -> flushed on stop()
        pipeline.push_audio("Karşı Taraf", speech, current_sec=1.5)
    finally:
        pipeline.stop(wait_timeout=5.0)

    assert len(received) == 2
    speakers = {seg.speaker for seg in received}
    assert speakers == {"Sen", "Karşı Taraf"}
    assert all(seg.meeting_id == 42 for seg in received)
