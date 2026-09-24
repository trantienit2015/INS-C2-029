"""AgentCore Platform v1.0 — outer post_process: OutputValidate (Step 6, S-3 gate)."""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import claims_investigation_service as svc


class OutputValidateNode(FunctionNode):
    """Assemble the final investigation summary memo + S-3 deterministic gate.

    The S-3 hook re-verifies, on the node's OWN output dict, that the
    non-suppressible fraud-surface flag and the mandatory non-binding-output
    disclaimer are both present, and that no binding coverage/payout verdict
    language leaked into the memo (proposal §11 risk #3).
    """

    # S-1: outer boundary node — matches agent.yaml required_trust_level (INTERNAL).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if svc.is_upstream_error(state.get("status")):
            emit_trace_event("output_skipped_upstream_error", {"correlation_id": state.get("correlation_id")}, state)
            return {"status": AgentStatus.ERROR.value}

        fraud_flag = state.get("fraud_surface_flag") or {"flagged": False, "reasons": []}
        summary = {
            "claim_type": state.get("claim_type", ""),
            "incident_timeline": state.get("incident_timeline", []),
            "liability_indicators": state.get("liability_indicators", []),
            "coverage_indicators": state.get("coverage_indicators", []),
            "payout_estimate_range": state.get("payout_estimate_range"),
            "missing_documents": state.get("missing_documents", []),
            "fraud_surface_flag": fraud_flag,
            "narrative_note": state.get("narrative_note"),
            "disclaimer": svc.DISCLAIMER,
        }
        emit_trace_event(
            "output_validated",
            {"correlation_id": state.get("correlation_id"), "fraud_flagged": fraud_flag.get("flagged", False)},
            state,
        )
        return {
            "investigation_summary": summary,
            "formatted_output": summary,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3 preservation variant (framework-invoked; never raises).

        Re-checks the node's OWN output (`investigation_summary`) — not
        upstream state — for the two mandatory, non-suppressible elements.
        """
        summary = state.get("investigation_summary") or {}
        if not summary:
            return state
        if "fraud_surface_flag" not in summary:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputValidateNode: non-suppressible fraud-surface flag missing"],
            }
        if summary.get("disclaimer") != svc.DISCLAIMER:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputValidateNode: mandatory non-binding-output disclaimer missing"],
            }
        if svc.has_binding_verdict_language(json.dumps(summary, ensure_ascii=False)):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputValidateNode: binding coverage/payout verdict language blocked"],
            }
        return state
