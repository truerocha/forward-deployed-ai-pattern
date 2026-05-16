"""
A2A Context Compressor — Truncation and Summarization for Feedback Loops.

Prevents context window explosion during iterative review cycles by:
  - Extracting only actionable feedback (criticisms) instead of full report
  - Summarizing the previous report into key sections
  - Enforcing a token budget for rework payloads
  - Preserving research data in compressed form (topic + top findings)

Design:
  - Token estimation uses character-based heuristic (4 chars ≈ 1 token)
  - Compression is lossless for critical data (criticisms, artifacts)
  - Lossy compression applies only to body text (corpo_analise, introducao)
  - Compatible with Bedrock max_tokens=8192 on the Escrita agent

The δ-mem paper (arXiv:2605.12357) proposes model-level memory compression
via delta-rule learning into a fixed-size state matrix. Since we use Bedrock
API (no model internals access), we implement the equivalent at the
orchestration layer: compress historical context into a fixed-budget payload
before each agent invocation.

Ref: ADR-034 (A2A Protocol), arXiv:2605.12357 (δ-mem inspiration)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.a2a.contracts import (
    FinalReport,
    RawContent,
    ReviewFeedback,
)

logger = logging.getLogger(__name__)

# Default token budget for rework payloads (chars ≈ tokens * 4)
DEFAULT_MAX_CHARS = 24_000  # ~6000 tokens — leaves room for system prompt + output
RESEARCH_SUMMARY_MAX_FINDINGS = 5
REPORT_BODY_MAX_CHARS = 4_000
FEEDBACK_MAX_CRITICISMS = 10


def estimate_tokens(text: str) -> int:
    """Estimate token count from character length.

    Uses the standard heuristic: 1 token ≈ 4 characters for English text.

    Args:
        text: Input text string.

    Returns:
        Estimated token count.
    """
    return len(text) // 4


def compress_research_data(
    research: RawContent,
    max_findings: int = RESEARCH_SUMMARY_MAX_FINDINGS,
) -> dict[str, Any]:
    """Compress research data to essential facts for rework context.

    Keeps topico + top N fatos_encontrados + confianca. Drops fontes and
    contexto_adicional (not needed for rework — the agent already
    produced a report from this data).

    Uses the ALIAS field names (topico, fatos_encontrados, confianca) to
    maintain compatibility with the existing A2A server contracts.

    Args:
        research: Full research output from Phase 1.
        max_findings: Maximum number of findings to retain.

    Returns:
        Compressed research dict (subset of RawContent schema).
    """
    return {
        "topico": research.topic,
        "fatos_encontrados": research.findings[:max_findings],
        "confianca": research.confidence,
        "_compressed": True,
        "_original_findings_count": len(research.findings),
    }


def compress_report_for_rework(
    report: FinalReport,
    max_body_chars: int = REPORT_BODY_MAX_CHARS,
) -> dict[str, Any]:
    """Compress a report for the rework payload.

    The engineering agent needs to know WHAT it produced (to fix it),
    but doesn't need the full corpo_analise verbatim — it will rewrite it.
    We keep: titulo, truncated introducao, truncated corpo_analise, artefatos.

    Uses the ALIAS field names to maintain compatibility with the existing
    Escrita server's expected input format.

    Args:
        report: Full report from the previous engineering pass.
        max_body_chars: Maximum characters for the analysis body.

    Returns:
        Compressed report dict using existing contract field names.
    """
    body = report.analysis_body
    truncated_body = body[:max_body_chars]
    if len(body) > max_body_chars:
        truncated_body += f"\n\n[... truncado: {len(body) - max_body_chars} chars omitidos ...]"

    intro = report.introduction
    truncated_intro = intro[:1000]
    if len(intro) > 1000:
        truncated_intro += " [truncado]"

    return {
        "titulo": report.title,
        "introducao": truncated_intro,
        "corpo_analise": truncated_body,
        "conclusao": report.conclusion[:1000],
        "referencias": report.references[:5],
        "artefatos": [
            {
                "path": a.path,
                "content_hash": a.content_hash,
                "language": a.language,
                "lines_added": a.lines_added,
                "lines_modified": a.lines_modified,
            }
            for a in report.artifacts
        ],
        "aprovado": report.approved,
        "metricas": {},
        "_compressed": True,
        "_original_body_chars": len(body),
    }


def compress_feedback_for_rework(
    feedback: ReviewFeedback,
    max_criticisms: int = FEEDBACK_MAX_CRITICISMS,
) -> dict[str, Any]:
    """Compress feedback to actionable items only.

    The engineering agent needs: criticas (what to fix) and
    pontos_positivos (what to preserve). Priority order for criticisms:
    critical > major > minor > suggestion.

    Uses the ALIAS field names to maintain compatibility with the existing
    contract schema (veredicto, score_qualidade, criticas, pontos_positivos).

    Args:
        feedback: Full review feedback.
        max_criticisms: Maximum criticisms to include.

    Returns:
        Compressed feedback dict with prioritized criticisms.
    """
    severity_order = {"critical": 0, "major": 1, "minor": 2, "suggestion": 3}
    sorted_criticisms = sorted(
        feedback.criticisms,
        key=lambda c: severity_order.get(c.severidade, 4),
    )

    top_criticisms = sorted_criticisms[:max_criticisms]

    return {
        "veredicto": feedback.verdict.value,
        "score_qualidade": feedback.quality_score,
        "criticas": [
            {
                "categoria": c.categoria,
                "severidade": c.severidade,
                "descricao": c.descricao,
                "localizacao": c.localizacao,
                "sugestao_correcao": c.sugestao_correcao,
            }
            for c in top_criticisms
        ],
        "pontos_positivos": feedback.positive_points[:5],
        "recomendacoes": feedback.recomendacoes[:3],
        "aprovado": feedback.approved,
        "tentativa": feedback.tentativa,
        "_compressed": True,
        "_original_criticisms_count": len(feedback.criticisms),
    }


def build_compressed_rework_payload(
    research: RawContent,
    report: FinalReport,
    feedback: ReviewFeedback,
    max_total_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Build a token-budget-aware rework payload for the engineering agent.

    This replaces the naive approach of sending full research + full report +
    full feedback, which causes context window explosion on iteration 2+.

    Strategy (inspired by delta-mem fixed-size state compression):
      1. Compress research to topico + top findings (fixed budget)
      2. Compress report to titulo + truncated body + artefatos (adaptive budget)
      3. Compress feedback to prioritized criticas (fixed budget)
      4. If total exceeds budget, progressively truncate corpo_analise further

    The output dict uses the SAME keys as the current orchestrator rework
    payload: "dados_originais", "relatorio_anterior", "feedback".

    Args:
        research: Full research data from Phase 1.
        report: Previous report (to be reworked).
        feedback: Review feedback (what to fix).
        max_total_chars: Maximum total payload size in characters.

    Returns:
        Compressed payload dict ready for A2A invocation.
    """
    compressed_research = compress_research_data(research)
    compressed_feedback = compress_feedback_for_rework(feedback)

    # Estimate remaining budget for the report
    research_size = len(json.dumps(compressed_research, default=str))
    feedback_size = len(json.dumps(compressed_feedback, default=str))
    overhead = 200  # JSON structure overhead

    remaining_budget = max_total_chars - research_size - feedback_size - overhead
    report_body_budget = max(1000, remaining_budget - 2000)

    compressed_report = compress_report_for_rework(report, max_body_chars=report_body_budget)

    payload = {
        "dados_originais": compressed_research,
        "relatorio_anterior": compressed_report,
        "feedback": compressed_feedback,
    }

    # Final size check
    total_size = len(json.dumps(payload, default=str))
    if total_size > max_total_chars:
        # Emergency truncation: cut report body further
        emergency_budget = max(500, report_body_budget // 2)
        compressed_report = compress_report_for_rework(report, max_body_chars=emergency_budget)
        payload["relatorio_anterior"] = compressed_report
        logger.warning(
            "Rework payload exceeded budget (%d > %d chars) — emergency truncation applied",
            total_size, max_total_chars,
        )

    final_size = len(json.dumps(payload, default=str))
    logger.info(
        "Compressed rework payload: %d chars (~%d tokens) "
        "[research=%d findings, report_body=%d chars, feedback=%d criticas]",
        final_size,
        estimate_tokens(json.dumps(payload, default=str)),
        len(compressed_research.get("fatos_encontrados", [])),
        len(compressed_report.get("corpo_analise", "")),
        len(compressed_feedback.get("criticas", [])),
    )

    return payload
