"""AgentCore Platform v1.0 — inner step 3: CompletenessCheck."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import claims_investigation_service as svc


class CompletenessCheckNode(FunctionNode):
    """Match the present document batch against the per-claim_type checklist."""

    # S-1 (inner subgraph node, invoked via InvestigationGraphNode): ANONYMOUS.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if svc.is_upstream_error(state.get("status")):
            emit_trace_event(
                "completeness_check_skipped_upstream_error", {"correlation_id": state.get("correlation_id")}, state
            )
            return {"status": AgentStatus.ERROR.value}

        claim_type = state.get("claim_type", "")
        shielded = state.get("shielded_documents") or []
        present_types = {d.get("doc_type") for d in shielded}
        checklist = svc.checklist_for(claim_type)
        missing = [t for t in checklist if t not in present_types]

        emit_trace_event(
            "completeness_checked",
            {"correlation_id": state.get("correlation_id"), "n_missing": len(missing), "claim_type": claim_type},
            state,
        )
        return {"missing_documents": missing, "status": AgentStatus.SUCCESS.value}
