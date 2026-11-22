# LocalMinutes

%100 offline, toplantıya bot sokmayan canlı toplantı ve ders deşifre + özet stüdyosu.

## Hedef Özellikler (MVP)
- **Çift kanallı ses yakalama:** Windows WASAPI loopback (karşı taraf) + mikrofon (kullanıcı) ayrı kanallarda kayıt
- `faster-whisper` (INT8 CPU + VAD) ile canlı ve konuşmacı etiketli (`Sen` / `Karşı Taraf`) transkript
- Toplantı/ders bitiminde lokal LLM (Ollama) veya opsiyonel API ile otomatik **özet, kararlar ve yapılacaklar listesi (action items)**
- Markdown, TXT ve SRT formatlarında tek tıkla dışa aktarma
- Toplantı arşivi ve metin içi hızlı arama

## Planlanan Teknoloji Yığını
- **Dil:** Python 3.10+
- **Arayüz:** PyQt6 Studio
- **Ses & AI:** `pyaudiowpatch` (WASAPI Loopback), `faster-whisper` (CTranslate2 INT8 + Silero VAD), `httpx` (Ollama / OpenAI-uyumlu API)
- **Depolama:** SQLite + FTS5 tam metin arama
- **Dağıtım:** PyInstaller / Inno Setup + Portable ZIP

## Kurulum ve Çalıştırma
```powershell
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Testler
```powershell
.venv\Scripts\pytest.exe -v
```
