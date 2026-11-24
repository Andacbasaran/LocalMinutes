"""Dual-channel live audio waveform meter (backwards-compatible export of DualWaveformMeter)."""

from __future__ import annotations

from localminutes.ui.studio_widgets import DualWaveformMeter


class DualLevelMeter(DualWaveformMeter):
    """Alias for Studio 2.0 DualWaveformMeter preserving the DualLevelMeter API."""
