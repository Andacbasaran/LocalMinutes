"""'Ask This Meeting' Local Q&A Engine — grounded LLM + instant 100% offline BM25 with [MM:SS] citations."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

import httpx

from localminutes.export.exporter import format_timestamp
from localminutes.models import AppSettings, QACitation, QAResponse, TranscriptSegment

_QA_STOPWORDS = {
    "the", "and", "or", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "not", "but", "you", "your", "they", "what", "when", "where", "which",
    "who", "how", "why", "did", "does", "about", "into", "were", "will", "would", "can",
    "bir", "bu", "ve", "ile", "için", "neler", "nedir", "nasıl", "kim", "hangi", "ne",
    "oldu", "var", "mı", "mi", "mu", "mü", "da", "de", "gibi", "daha",
}

_TOKEN_RE = re.compile(r"[0-9A-Za-zçğıöşüÇĞİÖŞÜ]+", re.UNICODE)


def _tokenize_qa(text: str) -> list[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 2]
    filtered = [t for t in tokens if t not in _QA_STOPWORDS]
    return filtered or tokens


def retrieve_bm25_citations(
    question: str,
    segments: Sequence[TranscriptSegment],
    top_k: int = 5,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[QACitation]:
    """Rank transcript segments using Okapi BM25 with light Turkish/English prefix matching."""
    if not segments or not question.strip():
        return []

    q_tokens = _tokenize_qa(question)
    if not q_tokens:
        return []

    docs: list[tuple[TranscriptSegment, list[str]]] = []
    doc_freq: Counter[str] = Counter()
    total_len = 0

    for seg in segments:
        doc_tokens = _tokenize_qa(f"{seg.speaker} {seg.text}")
        docs.append((seg, doc_tokens))
        total_len += len(doc_tokens)
        for tok in set(doc_tokens):
            doc_freq[tok] += 1

    n_docs = len(docs)
    avg_dl = max(1.0, total_len / float(n_docs))

    scored: list[tuple[float, TranscriptSegment]] = []
    for seg, doc_tokens in docs:
        if not doc_tokens:
            continue
        tf = Counter(doc_tokens)
        dl = len(doc_tokens)
        score = 0.0
        for qt in q_tokens:
            # Exact term frequency + stem/prefix bonus (helps Turkish agglutinative suffixes)
            freq = tf.get(qt, 0)
            matched_term = qt
            if freq == 0 and len(qt) >= 4:
                stem = qt[:4]
                for dt, cnt in tf.items():
                    if dt.startswith(stem) or qt.startswith(dt[:4] if len(dt) >= 4 else dt):
                        freq += cnt * 0.65
                        matched_term = dt
                        break
            if freq <= 0:
                continue
            df = doc_freq.get(matched_term, 1)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            denom = freq + k1 * (1.0 - b + b * (dl / avg_dl))
            score += idf * ((freq * (k1 + 1.0)) / max(1e-6, denom))

        if score > 0:
            if seg.is_bookmarked:
                score *= 1.15
            scored.append((score, seg))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    results: list[QACitation] = []
    for score, seg in scored[: max(1, top_k)]:
        results.append(
            QACitation(
                segment_id=seg.id,
                speaker=seg.speaker,
                timestamp_sec=seg.start_sec,
                snippet=seg.text.strip(),
                score=round(score, 3),
            )
        )
    return results


def _format_offline_answer(question: str, citations: list[QACitation]) -> str:
    if not citations:
        return (
            "No exact matching transcript excerpts were found for your question. "
            "Try different keywords or inspect the bookmarked moments."
        )
    lines = ["Grounded excerpts from this meeting:"]
    for cit in citations:
        ts = format_timestamp(cit.timestamp_sec)
        lines.append(f"• [{ts}] {cit.speaker}: {cit.snippet}")
    return "\n".join(lines)


def _ask_ollama(
    question: str,
    citations: list[QACitation],
    notes: str,
    settings: AppSettings,
    timeout: float = 45.0,
) -> str:
    context_lines = [
        f"[{format_timestamp(c.timestamp_sec)}] {c.speaker}: {c.snippet}" for c in citations
    ]
    if notes.strip():
        context_lines.append(f"[NOTES] {notes.strip()[:500]}")

    prompt = (
        "Answer the user's question using ONLY the meeting excerpts below. "
        "Cite timestamps inline using [MM:SS] format. Be concise and factual.\n\n"
        "EXCERPTS:\n" + "\n".join(context_lines) + f"\n\nQUESTION: {question}"
    )
    url = settings.ollama_url.rstrip("/") + "/api/chat"
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            url,
            json={
                "model": settings.ollama_model,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": "You answer questions strictly from the provided meeting transcript excerpts with [MM:SS] citations.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        resp.raise_for_status()
        return str(resp.json().get("message", {}).get("content", "")).strip()


def _ask_openai(
    question: str,
    citations: list[QACitation],
    notes: str,
    settings: AppSettings,
    timeout: float = 45.0,
) -> str:
    context_lines = [
        f"[{format_timestamp(c.timestamp_sec)}] {c.speaker}: {c.snippet}" for c in citations
    ]
    if notes.strip():
        context_lines.append(f"[NOTES] {notes.strip()[:500]}")

    prompt = (
        "Answer the user's question using ONLY the meeting excerpts below. "
        "Cite timestamps inline using [MM:SS] format. Be concise and factual.\n\n"
        "EXCERPTS:\n" + "\n".join(context_lines) + f"\n\nQUESTION: {question}"
    )
    url = settings.api_base_url.rstrip("/") + "/chat/completions"
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {settings.api_key.strip()}"},
            json={
                "model": settings.api_model,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "system",
                        "content": "You answer questions strictly from the provided meeting transcript excerpts with [MM:SS] citations.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        resp.raise_for_status()
        choices = resp.json().get("choices", [])
        return str(choices[0].get("message", {}).get("content", "")).strip() if choices else ""


def ask_meeting(
    question: str,
    segments: Sequence[TranscriptSegment],
    settings: AppSettings,
    notes: str = "",
    top_k: int = 5,
) -> QAResponse:
    """
    Answer a question grounded in the meeting transcript with `[MM:SS]` citations.
    Always runs fast BM25 retrieval first to ground citations; if Air-Gapped or no LLM
    is reachable, instantaneously returns the grounded offline BM25 answer.
    """
    q = question.strip()
    if not q:
        return QAResponse(question="", answer="Enter a question to search this meeting.", citations=[])

    citations = retrieve_bm25_citations(q, segments, top_k=top_k)

    # If BM25 found no exact keyword overlap, include bookmarked / earliest segments as context for LLM
    context_citations = citations
    if not context_citations and segments:
        fallback_segs = [s for s in segments if s.is_bookmarked][:3] or list(segments[:top_k])
        context_citations = [
            QACitation(
                segment_id=s.id,
                speaker=s.speaker,
                timestamp_sec=s.start_sec,
                snippet=s.text.strip(),
                score=0.0,
            )
            for s in fallback_segs
        ]

    if settings.air_gapped_mode or settings.llm_provider == "local_extractive":
        label = "local/bm25-offline (Air-Gapped)" if settings.air_gapped_mode else "local/bm25-offline"
        return QAResponse(
            question=q,
            answer=_format_offline_answer(q, citations),
            citations=citations,
            model_used=label,
        )

    if settings.llm_provider in ("auto", "ollama") and context_citations:
        try:
            ans = _ask_ollama(q, context_citations, notes, settings)
            if ans:
                return QAResponse(
                    question=q,
                    answer=ans,
                    citations=citations or context_citations,
                    model_used=f"ollama/{settings.ollama_model}",
                )
        except Exception:
            pass

    if settings.llm_provider == "openai_compatible" and settings.api_key.strip() and context_citations:
        try:
            ans = _ask_openai(q, context_citations, notes, settings)
            if ans:
                return QAResponse(
                    question=q,
                    answer=ans,
                    citations=citations or context_citations,
                    model_used=f"api/{settings.api_model}",
                )
        except Exception:
            pass

    return QAResponse(
        question=q,
        answer=_format_offline_answer(q, citations),
        citations=citations,
        model_used="local/bm25-offline",
    )
