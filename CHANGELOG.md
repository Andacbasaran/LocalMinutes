# Changelog

All notable changes to **LocalMinutes** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-24

### Added
- **Studio 2.0 Flagship Desktop UI (PyQt6 Fusion Dark):**
  - 3-View Studio workspace: **Meeting Studio** (live dual-channel transcript + 4-tab Intelligence Dock), **Tasks & Insights Hub** (cross-meeting action items & archive KPIs), and **Settings & Telemetry**.
  - Interactive tag chips, 1-click **Load Demo** bilingual Sprint Planning session, live dual-channel emerald/sky waveform meter, system tray integration, single-instance lock, and `crash.log` diagnostics.
  - Full bilingual **English (EN) & Turkish (TR)** runtime interface localization (`localminutes/i18n.py`).
- **Cross-Platform Bot-Free Dual-Channel Audio Capture:**
  - Native **Windows WASAPI** loopback (`pyaudiowpatch`), **macOS CoreAudio + BlackHole 2ch** detection (`sounddevice`), and **Linux PipeWire / PulseAudio `.monitor`** auto-detection (`sounddevice`), with seamless single-channel mic fallback.
  - Anti-aliased polyphase FIR downsampling (`scipy.signal.resample_poly`, `60.3 dB` SNR vs `2.2 dB` naive linear interpolation at `0.78 ms` per 1s stereo audio).
  - Continuous timestamp offset when pausing or resuming an existing meeting.
- **Offline Transcription & Hardware-Adaptive Engine:**
  - `faster-whisper` (CTranslate2 INT8, `0 MB VRAM`) with automatic CPU core/SIMD/Apple Silicon detection (`localminutes/hardware.py`), compute-type fallback chain, Silero VAD endpointing, custom vocabulary `initial_prompt`, and cancellable drag-and-drop media import (`MP3`, `MP4`, `WAV`, `M4A`, `MKV`, `WEBM`, `OGG`, `FLAC`).
  - Built-in Whisper model cache manager (download / delete cached models directly from Settings).
- **Meeting Intelligence, Local Q&A & Persistent Action Items:**
  - **Ask This Meeting (`localminutes/summarization/qa.py`):** Grounded Q&A powered by Okapi BM25 (`9.09 ms` over 600 segments) + optional local Ollama / OpenAI-compatible LLM, returning clickable `[MM:SS]` citations that jump straight to the transcript card.
  - **Granola-Style Private Notes:** Auto-saved timestamped notes (`Ctrl+T`) with **Enhance My Notes** and race-free debounce flushing on meeting switch or app shutdown.
  - **Persisted Action Items:** Dedicated SQLite `action_items` table synced with summaries, toggleable inline or in the cross-meeting Tasks Hub, and exported as Markdown checklists.
  - **Strict Air-Gapped Privacy Mode:** One-click toggle that guarantees **0 outbound HTTP requests** across summarization, Q&A, Ollama probing, and update checks.
- **Sub-Millisecond SQLite WAL + FTS5 Archive & Exporters:**
  - `unicode61` FTS5 indexing (`25.1 ms` for 5,000 segments; `0.063 ms` avg / `0.083 ms` p95 search latency) with punctuation-safe fallback for queries like `C++` and Turkish Unicode.
  - Exporters for **Markdown (`.md`)**, **Obsidian YAML Frontmatter Markdown**, **SubRip (`.srt`)**, **WebVTT (`.vtt`)**, **Plain Text (`.txt`)**, and round-trip **JSON Full Backup (`.json`)** import/export.
- **Cross-Platform Releases & Packaging:**
  - Automated CI/CD (`.github/workflows/ci.yml`, `release.yml`), Windows Inno Setup + Portable ZIP, macOS Apple Silicon `.dmg`, Linux `.tar.gz` + AppDir, plus Winget, Scoop, and Homebrew Cask manifests.
