"""AgentCore Platform v1.0 — inner step 4: FraudSurfaceFlag (non-suppressible)."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import claims_investigation_service as svc


class FraudSurfaceFlagNode(FunctionNode):
    """Surface factual inconsistencies across the document batch.

    Always appends a fraud_surface_flag dict (flagged: bool + reasons: list),
    even when no inconsistency is found — this key's presence is re-verified,
    non-suppressibly, by the outer OutputValidateNode S-3 hook (per 改正犯収法
    2026 / proposal §2-3), so an override cannot silently drop it downstream.
    """

    # S-1 (inner subgraph node, invoked via InvestigationGraphNode): ANONYMOUS.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if svc.is_upstream_error(state.get("status")):
            emit_trace_event(
                "fraud_surface_flag_skipped_upstream_error", {"correlation_id": state.get("correlation_id")}, state
            )
            return {"status": AgentStatus.ERROR.value}

        shielded = state.get("shielded_documents") or []
        reasons = svc.detect_inconsistencies(shielded)
        flag = {"flagged": bool(reasons), "reasons": reasons}

        emit_trace_event(
            "fraud_surface_evaluated",
            {"correlation_id": state.get("correlation_id"), "flagged": flag["flagged"]},
            state,
        )
        return {"fraud_surface_flag": flag, "status": AgentStatus.SUCCESS.value}
