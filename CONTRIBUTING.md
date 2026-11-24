# Contributing to LocalMinutes

Thank you for your interest in contributing to **LocalMinutes**! Every bug report, audio compatibility note, localization improvement, and pull request helps make 100% offline, bot-free meeting transcription better for everyone.

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Andacbasaran/LocalMinutes.git
   cd LocalMinutes
   ```

2. **Create a virtual environment and install dependencies (Python 3.10+):**
   ```bash
   python -m venv .venv
   # Windows: .\.venv\Scripts\activate
   # macOS / Linux: source .venv/bin/activate
   pip install --prefer-binary -r requirements.txt
   pip install pytest ruff
   ```
   On Ubuntu/Debian Linux, make sure PortAudio and Qt runtime libraries are present:
   ```bash
   sudo apt-get install -y libportaudio2 libegl1 libgl1 libxkbcommon0 libdbus-1-3
   ```

3. **Run LocalMinutes locally:**
   ```bash
   python main.py
   ```

## Code Quality & Testing

Before opening a pull request, please make sure linting and all unit + offscreen UI tests pass cleanly:

```bash
# 1. Lint with Ruff (must report 0 errors)
ruff check .

# 2. Run the full test suite (headless / offscreen Qt safe)
QT_QPA_PLATFORM=offscreen pytest -v

# 3. Optional: run the local DSP, FTS5, Summarizer & BM25 Q&A benchmark
QT_QPA_PLATFORM=offscreen python scripts/benchmark.py
```

## Contribution Guidelines

- **Privacy First:** Never introduce telemetry, analytics beacons, or unsolicited outbound network calls. Any optional HTTP feature (Ollama, OpenAI-compatible API, GitHub update check) **must** respect `settings.air_gapped_mode == True`.
- **Cross-Platform Parity:** Keep Windows (`pyaudiowpatch` WASAPI), macOS (`sounddevice` CoreAudio / BlackHole 2ch), and Linux (`sounddevice` PipeWire / PulseAudio `.monitor`) working cleanly without platform-specific import crashes.
- **Bilingual UI Strings:** When adding or modifying user-facing UI text, update both `"en"` and `"tr"` dictionaries in [`localminutes/i18n.py`](localminutes/i18n.py).
- **Small, Focused PRs:** Include unit tests for bug fixes or new features and update `CHANGELOG.md` when appropriate.

## Reporting Bugs & Compatibility

- Use the [Bug Report](https://github.com/Andacbasaran/LocalMinutes/issues/new?template=bug_report.yml) template for crashes or transcription glitches.
- Share tested meeting apps, virtual audio routers, or local Ollama models via the [Audio / App Compatibility Report](https://github.com/Andacbasaran/LocalMinutes/issues/new?template=compatibility_report.yml) template or a PR to [`COMPATIBILITY.md`](COMPATIBILITY.md).
