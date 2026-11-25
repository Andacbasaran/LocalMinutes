"""Exporters (.md, Obsidian YAML .md, .txt, .srt, .vtt, .json), JSON importer, and Demo Meeting builder."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from localminutes.models import (
    ActionItem,
    Meeting,
    SummaryResult,
    TranscriptSegment,
    get_template_meta,
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f\u0080-\u009f]+")
_SAFE_BARE_YAML_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")
_YAML_RESERVED_WORDS = frozenset(
    {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"}
)


def _clean_yaml_text(value: str) -> str:
    """Strip ASCII/C1 control characters and collapse newlines to a single space."""
    return _CONTROL_CHAR_RE.sub(" ", str(value or "")).strip()


def _yaml_scalar(value: str) -> str:
    """Serialize a YAML string scalar safely via json.dumps after stripping control characters."""
    return json.dumps(_clean_yaml_text(value), ensure_ascii=False)


def _yaml_tag_scalar(tag: str) -> str:
    """Keep simple Obsidian tags unquoted while json.dumps-quoting any special/injectable tag."""
    clean = _clean_yaml_text(tag)
    if (
        clean
        and _SAFE_BARE_YAML_TAG_RE.fullmatch(clean)
        and clean.lower() not in _YAML_RESERVED_WORDS
    ):
        return clean
    return json.dumps(clean, ensure_ascii=False)


def _sanitize_srt_text(text: str) -> str:
    """Prevent cue injection in SubRip (.srt) files by collapsing blank lines and '-->'."""
    norm = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    norm = re.sub(r"\n{2,}", "\n", norm)
    return norm.replace("-->", "->").strip()


def _sanitize_vtt_speaker(speaker: str) -> str:
    """Sanitize WebVTT <v speaker> voice tag against tag breakout and cue spoofing."""
    clean = _CONTROL_CHAR_RE.sub(" ", str(speaker or "Speaker")).replace("-->", "->")
    clean = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "")
    return clean.strip() or "Speaker"


def _sanitize_vtt_text(text: str) -> str:
    """Sanitize WebVTT cue text (collapse blank lines, neutralize '-->', escape '&' and '<')."""
    norm = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    norm = re.sub(r"\n{2,}", "\n", norm)
    norm = norm.replace("-->", "->")
    norm = norm.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return norm.strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        num = float(value)
        if not math.isfinite(num):
            return default
        return max(0.0, num)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _safe_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    return []


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_srt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm for SubRip (.srt)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm for WebVTT (.vtt)."""
    return _format_srt_time(seconds).replace(",", ".")


def format_markdown(meeting: Meeting, obsidian_frontmatter: bool = False) -> str:
    """Render a full meeting (summary, action items, notes, bookmarks, transcript) as Markdown."""
    lang = "tr" if meeting.language.lower().startswith("tr") else "en"
    tmpl = get_template_meta(meeting.template, lang=lang)
    lines: list[str] = []

    if obsidian_frontmatter:
        clean_created = _clean_yaml_text(meeting.created_at)
        date_part = clean_created[:10]
        lines.append("---")
        lines.append(f"title: {_yaml_scalar(meeting.title)}")
        lines.append(f"date: {_yaml_scalar(date_part)}")
        lines.append(f"created_at: {_yaml_scalar(clean_created)}")
        lines.append(f"duration: {_yaml_scalar(format_timestamp(meeting.duration_sec))}")
        lines.append(f"template: {_yaml_scalar(meeting.template)}")
        lines.append(f"language: {_yaml_scalar(meeting.language)}")
        if meeting.tags:
            lines.append("tags:")
            for tag in meeting.tags:
                lines.append(f"  - {_yaml_tag_scalar(tag)}")
        else:
            lines.append("tags: [localminutes, meeting]")
        lines.append("source: LocalMinutes")
        lines.append("---")
        lines.append("")

    if lang == "tr":
        lines.extend(
            [
                f"# {meeting.title}",
                "",
                f"- **Tarih:** {meeting.created_at}",
                f"- **Süre:** {format_timestamp(meeting.duration_sec)}",
                f"- **Şablon:** {tmpl['label']}",
                f"- **Dil:** {meeting.language}",
            ]
        )
        if meeting.tags:
            lines.append(f"- **Etiketler:** {', '.join(f'`{t}`' for t in meeting.tags)}")
    else:
        lines.extend(
            [
                f"# {meeting.title}",
                "",
                f"- **Date:** {meeting.created_at}",
                f"- **Duration:** {format_timestamp(meeting.duration_sec)}",
                f"- **Template:** {tmpl['label']}",
                f"- **Language:** {meeting.language}",
            ]
        )
        if meeting.tags:
            lines.append(f"- **Tags:** {', '.join(f'`{t}`' for t in meeting.tags)}")
    lines.append("")

    if meeting.summary:
        s = meeting.summary
        s_tmpl = get_template_meta(s.template, lang=lang)
        lines.append(f"## {s_tmpl['overview_title']}")
        lines.append("")
        if s.overview:
            lines.append(s.overview.strip())
            lines.append("")
        if s.key_points:
            lines.append(f"### {s_tmpl['key_points_title']}")
            for item in s.key_points:
                lines.append(f"- {item}")
            lines.append("")
        if s.decisions:
            lines.append(f"### {s_tmpl['decisions_title']}")
            for item in s.decisions:
                lines.append(f"- {item}")
            lines.append("")
        if meeting.action_items:
            lines.append(f"### {s_tmpl['action_items_title']}")
            for ai in meeting.action_items:
                box = "x" if ai.completed else " "
                owner = f"**{ai.assignee}:** " if ai.assignee else ""
                lines.append(f"- [{box}] {owner}{ai.text}")
            lines.append("")
        elif s.action_items:
            lines.append(f"### {s_tmpl['action_items_title']}")
            for item in s.action_items:
                lines.append(f"- [ ] {item}")
            lines.append("")
    elif meeting.action_items:
        lines.append(f"## {tmpl['action_items_title']}")
        lines.append("")
        for ai in meeting.action_items:
            box = "x" if ai.completed else " "
            owner = f"**{ai.assignee}:** " if ai.assignee else ""
            lines.append(f"- [{box}] {owner}{ai.text}")
        lines.append("")

    if meeting.notes.strip():
        lines.append("## Toplantı Notları" if lang == "tr" else "## Meeting Notes")
        lines.append("")
        lines.append(meeting.notes.strip())
        lines.append("")

    bookmarked = [seg for seg in meeting.segments if seg.is_bookmarked]
    if bookmarked:
        lines.append("## ⭐ İşaretlenen Anlar" if lang == "tr" else "## Bookmarked Moments")
        lines.append("")
        for seg in bookmarked:
            ts = format_timestamp(seg.start_sec)
            lines.append(f"- **[{ts}] {seg.speaker}:** {seg.text.strip()}")
        lines.append("")

    lines.append("## Transkript" if lang == "tr" else "## Transcript")
    lines.append("")
    if not meeting.segments:
        lines.append("_Henüz transkript kaydı bulunmuyor._" if lang == "tr" else "_No transcript recorded yet._")
    else:
        for seg in meeting.segments:
            ts = format_timestamp(seg.start_sec)
            star = "⭐ " if seg.is_bookmarked else ""
            lines.append(f"{star}**[{ts}] {seg.speaker}:** {seg.text.strip()}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_txt(meeting: Meeting) -> str:
    """Render a meeting as clean plain text."""
    lang = "tr" if meeting.language.lower().startswith("tr") else "en"
    lines: list[str] = [
        meeting.title,
        "=" * len(meeting.title),
        (
            f"Tarih: {meeting.created_at} | Süre: {format_timestamp(meeting.duration_sec)}"
            if lang == "tr"
            else f"Date: {meeting.created_at} | Duration: {format_timestamp(meeting.duration_sec)}"
        ),
        "",
    ]

    if meeting.summary:
        s = meeting.summary
        lines.append("ÖZET" if lang == "tr" else "SUMMARY")
        lines.append("-" * 40)
        if s.overview:
            lines.append(s.overview.strip())
            lines.append("")
        if s.key_points:
            lines.append("Öne Çıkan Noktalar:" if lang == "tr" else "Key Points:")
            for item in s.key_points:
                lines.append(f"  * {item}")
            lines.append("")
        if s.decisions:
            lines.append("Alınan Kararlar:" if lang == "tr" else "Decisions:")
            for item in s.decisions:
                lines.append(f"  * {item}")
            lines.append("")
        if meeting.action_items:
            lines.append("Yapılacaklar:" if lang == "tr" else "Action Items:")
            for ai in meeting.action_items:
                box = "x" if ai.completed else " "
                owner = f"{ai.assignee}: " if ai.assignee else ""
                lines.append(f"  [{box}] {owner}{ai.text}")
            lines.append("")
        elif s.action_items:
            lines.append("Yapılacaklar:" if lang == "tr" else "Action Items:")
            for item in s.action_items:
                lines.append(f"  [ ] {item}")
            lines.append("")

    if meeting.notes.strip():
        lines.append("NOTLAR" if lang == "tr" else "NOTES")
        lines.append("-" * 40)
        lines.append(meeting.notes.strip())
        lines.append("")

    lines.append("TRANSKRİPT" if lang == "tr" else "TRANSCRIPT")
    lines.append("-" * 40)
    for seg in meeting.segments:
        ts = format_timestamp(seg.start_sec)
        star = "[*] " if seg.is_bookmarked else ""
        lines.append(f"{star}[{ts}] {seg.speaker}: {seg.text.strip()}")

    return "\n".join(lines).rstrip() + "\n"


def format_srt(meeting: Meeting) -> str:
    """Render transcript segments as SubRip (.srt) subtitles."""
    blocks: list[str] = []
    for idx, seg in enumerate(meeting.segments, start=1):
        start = _format_srt_time(seg.start_sec)
        end_sec = seg.end_sec if seg.end_sec > seg.start_sec else seg.start_sec + 2.0
        end = _format_srt_time(end_sec)
        safe_speaker = _CONTROL_CHAR_RE.sub(" ", str(seg.speaker or "Speaker")).replace("-->", "->").strip()
        safe_body = _sanitize_srt_text(seg.text)
        blocks.append(f"{idx}\n{start} --> {end}\n{safe_speaker}: {safe_body}\n")
    return "\n".join(blocks)


def format_vtt(meeting: Meeting) -> str:
    """Render transcript segments as WebVTT (.vtt) subtitles."""
    blocks: list[str] = ["WEBVTT", ""]
    for idx, seg in enumerate(meeting.segments, start=1):
        start = _format_vtt_time(seg.start_sec)
        end_sec = seg.end_sec if seg.end_sec > seg.start_sec else seg.start_sec + 2.0
        end = _format_vtt_time(end_sec)
        safe_speaker = _sanitize_vtt_speaker(seg.speaker)
        safe_body = _sanitize_vtt_text(seg.text)
        blocks.append(f"{idx}\n{start} --> {end}\n<v {safe_speaker}>{safe_body}\n")
    return "\n".join(blocks).rstrip() + "\n"


def format_json(meeting: Meeting) -> str:
    """Render full meeting data (including tags, summary, segments, and action items) as JSON backup."""
    return json.dumps(asdict(meeting), ensure_ascii=False, indent=2) + "\n"


def parse_meeting_json(raw_json: str) -> Meeting:
    """Parse a JSON backup exported by LocalMinutes back into a Meeting model safely."""
    data = json.loads(raw_json)
    if not isinstance(data, dict):
        raise ValueError("Invalid LocalMinutes JSON backup: root payload must be a JSON object.")
    raw_title = data.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        raise ValueError("Invalid LocalMinutes JSON backup: missing meeting 'title'.")

    now_iso = datetime.now().isoformat(timespec="seconds")
    summary_raw = data.get("summary")
    summary = None
    if isinstance(summary_raw, dict):
        summary = SummaryResult(
            overview=_safe_str(summary_raw.get("overview"), ""),
            key_points=_safe_str_list(summary_raw.get("key_points")),
            decisions=_safe_str_list(summary_raw.get("decisions")),
            action_items=_safe_str_list(summary_raw.get("action_items")),
            template=_safe_str(summary_raw.get("template"), "meeting") or "meeting",
            raw_markdown=_safe_str(summary_raw.get("raw_markdown"), ""),
            model_used=_safe_str(summary_raw.get("model_used"), ""),
            generated_at=_safe_str(summary_raw.get("generated_at"), ""),
        )

    segments: list[TranscriptSegment] = []
    raw_segments = data.get("segments")
    if isinstance(raw_segments, list):
        for raw_seg in raw_segments:
            if not isinstance(raw_seg, dict):
                continue
            seg_text = _safe_str(raw_seg.get("text"), "").strip()
            if not seg_text:
                continue
            start_s = _safe_float(raw_seg.get("start_sec"), 0.0)
            end_s = _safe_float(raw_seg.get("end_sec"), start_s)
            if end_s < start_s:
                end_s = start_s
            segments.append(
                TranscriptSegment(
                    speaker=_safe_str(raw_seg.get("speaker"), "You").strip() or "You",
                    text=seg_text,
                    start_sec=start_s,
                    end_sec=end_s,
                    is_bookmarked=bool(raw_seg.get("is_bookmarked", False)),
                    created_at=_safe_str(raw_seg.get("created_at"), now_iso) or now_iso,
                )
            )

    action_items: list[ActionItem] = []
    raw_action_items = data.get("action_items")
    if isinstance(raw_action_items, list):
        for raw_ai in raw_action_items:
            if not isinstance(raw_ai, dict):
                continue
            ai_text = _safe_str(raw_ai.get("text"), "").strip()
            if not ai_text:
                continue
            action_items.append(
                ActionItem(
                    text=ai_text,
                    assignee=_safe_str(raw_ai.get("assignee"), ""),
                    due_date=_safe_str(raw_ai.get("due_date"), ""),
                    completed=bool(raw_ai.get("completed", False)),
                )
            )

    return Meeting(
        title=raw_title.strip(),
        created_at=_safe_str(data.get("created_at"), now_iso) or now_iso,
        duration_sec=_safe_float(data.get("duration_sec"), 0.0),
        language=_safe_str(data.get("language"), "auto") or "auto",
        template=_safe_str(data.get("template"), "meeting") or "meeting",
        tags=_safe_str_list(data.get("tags")),
        notes=_safe_str(data.get("notes"), ""),
        summary=summary,
        segments=segments,
        action_items=action_items,
    )


def export_meeting(meeting: Meeting, output_path: Path | str, fmt: str) -> Path:
    """Write a meeting to disk in 'md', 'obsidian_md', 'txt', 'srt', 'vtt', or 'json' format."""
    path = Path(output_path)
    fmt_clean = fmt.lower().lstrip(".")
    if fmt_clean in ("md", "markdown"):
        content = format_markdown(meeting, obsidian_frontmatter=False)
    elif fmt_clean in ("obsidian", "obsidian_md"):
        content = format_markdown(meeting, obsidian_frontmatter=True)
    elif fmt_clean == "txt":
        content = format_txt(meeting)
    elif fmt_clean == "srt":
        content = format_srt(meeting)
    elif fmt_clean == "vtt":
        content = format_vtt(meeting)
    elif fmt_clean == "json":
        content = format_json(meeting)
    else:
        raise ValueError(f"Unsupported export format: {fmt}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def build_demo_meeting() -> Meeting:
    """Build a realistic bilingual (EN/TR) Sprint Planning demo meeting for instant onboarding."""
    now = datetime.now().isoformat(timespec="seconds")
    segments = [
        TranscriptSegment(
            speaker="You",
            text="Welcome everyone to our v1.0 release sprint planning. Let's lock in the cross-platform audio pipeline and launch date today.",
            start_sec=4.0,
            end_sec=13.5,
            is_bookmarked=True,
        ),
        TranscriptSegment(
            speaker="Selin (PM)",
            text="Harika! Windows WASAPI loopback zaten sıfır kurulumla çalışıyor. macOS Apple Silicon tarafında BlackHole 2ch algılaması ve tek kanallı mikrofon yedek akışı tamamlandı mı?",
            start_sec=15.0,
            end_sec=28.2,
        ),
        TranscriptSegment(
            speaker="You",
            text="Yes — sounddevice handles CoreAudio on macOS and PipeWire monitor sinks on Linux, and we replaced naive interpolation with scipy polyphase resampling to eliminate aliasing.",
            start_sec=30.0,
            end_sec=43.8,
            is_bookmarked=True,
        ),
        TranscriptSegment(
            speaker="Mert (Infra)",
            text="SQLite FTS5 aramasını 5.000 segmentlik sentetik veri setinde test ettim; ortalama arama gecikmesi 1 milisaniyenin altında ve C++ gibi özel karakterler sorunsuz eşleşiyor.",
            start_sec=45.5,
            end_sec=59.0,
        ),
        TranscriptSegment(
            speaker="Selin (PM)",
            text="We agreed to ship LocalMinutes v1.0.0 this Friday with Strict Air-Gapped Privacy Mode enabled as a first-class toggle so enterprise teams can verify zero outbound HTTP traffic.",
            start_sec=61.0,
            end_sec=74.5,
            is_bookmarked=True,
        ),
        TranscriptSegment(
            speaker="Mert (Infra)",
            text="I will finalize the macOS arm64 DMG signing script, Inno Setup Windows installer, and unified SHA256SUMS release workflow by Thursday afternoon.",
            start_sec=76.2,
            end_sec=88.4,
        ),
        TranscriptSegment(
            speaker="You",
            text="Perfect. I'll publish the benchmark infographic and Obsidian YAML exporter docs right after the test suite hits 100% green across all three platforms.",
            start_sec=90.0,
            end_sec=102.5,
        ),
    ]
    summary = SummaryResult(
        overview=(
            "The team aligned on shipping LocalMinutes v1.0.0 this Friday with native Windows WASAPI, "
            "macOS CoreAudio/BlackHole, and Linux PipeWire audio capture, polyphase anti-aliased resampling, "
            "sub-millisecond SQLite FTS5 indexing, and Strict Air-Gapped Privacy Mode."
        ),
        key_points=[
            "Cross-platform capture verified across Windows WASAPI, macOS Apple Silicon (CoreAudio + BlackHole 2ch), and Linux PipeWire.",
            "Audio downsampling upgraded to scipy.signal.resample_poly to eliminate aliasing artifacts.",
            "SQLite FTS5 handles 5,000+ transcript segments in < 1 ms including special symbols like C++ and Turkish Unicode.",
            "Strict Air-Gapped Privacy Mode guarantees 0 outbound HTTP requests using built-in offline summarization and BM25 Q&A.",
        ],
        decisions=[
            "Ship LocalMinutes v1.0.0 on Friday across Windows x64, macOS arm64, and Linux x86_64.",
            "Include Strict Air-Gapped Privacy Mode toggle directly in Settings & Telemetry.",
            "Bundle Obsidian YAML frontmatter Markdown and WebVTT (.vtt) alongside standard exporters.",
        ],
        action_items=[
            "Mert (Infra): Finalize macOS arm64 DMG, Windows Inno Setup installer, and unified SHA256SUMS workflow by Thursday.",
            "You: Publish performance benchmark infographic and Obsidian YAML export documentation after 3-OS CI passes.",
            "Selin (PM): Validate BlackHole 2ch onboarding copy and bilingual EN/TR release notes.",
        ],
        template="technical",
        model_used="local/extractive-offline",
        generated_at=now,
    )
    action_items = [
        ActionItem(
            text="Finalize macOS arm64 DMG, Windows Inno Setup installer, and SHA256SUMS workflow",
            assignee="Mert (Infra)",
            due_date="Thu",
            completed=False,
        ),
        ActionItem(
            text="Publish benchmark infographic and Obsidian YAML export documentation",
            assignee="You",
            due_date="Fri",
            completed=False,
        ),
        ActionItem(
            text="Validate BlackHole 2ch setup copy and bilingual EN/TR release notes",
            assignee="Selin (PM)",
            due_date="Thu",
            completed=True,
        ),
    ]
    return Meeting(
        title="Q4 Product & Engineering Sprint — LocalMinutes v1.0 Launch",
        created_at=now,
        duration_sec=1980.0,
        language="en",
        template="technical",
        tags=["sprint", "v1.0-launch", "privacy", "cross-platform"],
        notes=(
            "- [00:04] Confirm Friday launch readiness across Win / macOS / Linux\n"
            "- [00:30] Polyphase resampling eliminates 48k -> 16k aliasing artifacts\n"
            "- [01:01] Highlight Air-Gapped Mode + 0 Bots badge in README & landing page"
        ),
        summary=summary,
        segments=segments,
        action_items=action_items,
    )
