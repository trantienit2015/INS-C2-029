"""AgentCore Platform v1.0 — inner step 1: PiiShield (S-2 domain check)."""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import claims_investigation_service as svc


class PiiShieldNode(FunctionNode):
    """Detect 要配慮個人情報 (medical) + 個人情報 (personal) and redact pre-LLM.

    The inner subgraph receives only the JSON string user_input (seeded from
    the outer validated_input), so this first inner node reconstructs the
    payload. Redacted text only is ever passed downstream or logged (S-4:
    payload counts + detected-type tags only, never raw PII values).
    """

    # S-1 (inner subgraph node, invoked via InvestigationGraphNode): ANONYMOUS.
    # Caller trust is authenticated once at the outer backbone (InputParse);
    # inner nodes must not re-demand INTERNAL.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict) or not payload.get("documents"):
            emit_trace_event(
                "pii_shield_rejected_invalid_input", {"correlation_id": state.get("correlation_id")}, state
            )
            return {"status": AgentStatus.ERROR.value, "error_log": ["PiiShieldNode: missing documents in inner input"]}

        claim_type = str(payload.get("claim_type", "") or "")
        documents = payload["documents"]

        shielded: list[dict[str, Any]] = []
        detected_types: set[str] = set()
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            text = str(doc.get("text", "") or "")
            detected_types.update(svc.detect_pii_types(text))
            shielded.append({"doc_type": doc.get("doc_type", "unclassified"), "text": svc.redact_pii(text)})

        emit_trace_event(
            "pii_shielded",
            {
                "correlation_id": state.get("correlation_id"),
                "n_documents": len(shielded),
                "pii_types_detected": sorted(detected_types),
            },
            state,
        )
        return {
            "claim_type": claim_type,
            "shielded_documents": shielded,
            "detected_pii_types": sorted(detected_types),
            "status": AgentStatus.SUCCESS.value,
        }
