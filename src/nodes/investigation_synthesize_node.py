"""AgentCore Platform v1.0 — inner step 2: InvestigationSynthesize."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import claims_investigation_service as svc


class InvestigationSynthesizeNode(FunctionNode):
    """Synthesize incident timeline, liability/coverage indicators, payout range.

    Deterministic synthesis is the guaranteed fallback; an optional LLM client
    refines the narrative rationale when configured. Output is always
    non-binding (indicators + estimate range only — proposal §11 risk #3).
    """

    # S-1 (inner subgraph node, invoked via InvestigationGraphNode): ANONYMOUS.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if svc.is_upstream_error(state.get("status")):
            emit_trace_event(
                "investigation_synthesize_skipped_upstream_error",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {"status": AgentStatus.ERROR.value}

        shielded = state.get("shielded_documents") or []
        claim_type = state.get("claim_type", "")
        if not shielded:
            emit_trace_event(
                "investigation_synthesize_rejected_no_documents",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InvestigationSynthesizeNode: no shielded documents to synthesize"],
            }

        timeline = svc.build_timeline(shielded)
        liability = svc.build_liability_indicators(shielded)
        coverage = svc.build_coverage_indicators(shielded, claim_type)
        payout_range = svc.build_payout_range(shielded)

        narrative_note, error = self._llm_refine(timeline, liability)
        if error is not None:
            emit_trace_event(
                "investigation_synthesize_llm_refine_failed",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {"status": AgentStatus.ERROR.value, "error_log": [f"InvestigationSynthesizeNode: {error}"]}

        emit_trace_event(
            "investigation_synthesized",
            {
                "correlation_id": state.get("correlation_id"),
                "n_timeline_entries": len(timeline),
                "payout_range_found": payout_range is not None,
                "narrative_refined": narrative_note is not None,
            },
            state,
        )
        result = {
            "incident_timeline": timeline,
            "liability_indicators": liability,
            "coverage_indicators": coverage,
            "payout_estimate_range": payout_range,
            "status": AgentStatus.SUCCESS.value,
        }
        if narrative_note is not None:
            result["narrative_note"] = narrative_note
        return result

    @staticmethod
    def _extract_text(raw: Any) -> str:
        if isinstance(raw, dict):
            content = raw.get("content", "")
            return content if isinstance(content, str) else ""
        if isinstance(raw, str):
            return raw
        return ""

    def _llm_refine(self, timeline: list[dict[str, Any]], liability: list[str]) -> tuple[str | None, str | None]:
        """Optional LLM narrative pass.

        Returns (narrative_note, error). When no LLM is configured, this is a
        deterministic no-op: (None, None). When an LLM IS configured, a failed
        or empty completion is a real error (3m) — never silently discarded as
        SUCCESS, so callers cannot mistake "LLM refine skipped" for "LLM refine
        ran and produced nothing".
        """
        if self._llm is None:
            return None, None
        try:
            raw = self._llm.complete(
                [
                    {
                        "role": "user",
                        "content": (
                            f"Summarize this insurance investigation timeline ({len(timeline)} entries) "
                            f"with liability indicators {liability}. Non-binding indicators only."
                        ),
                    }
                ]
            )
        except Exception as exc:  # noqa: BLE001 — narrow to a domain error below
            return None, f"LLM narrative refine call failed: {exc}"
        text = self._extract_text(raw)
        if not text.strip():
            return None, "LLM narrative refine returned empty content"
        return text, None
