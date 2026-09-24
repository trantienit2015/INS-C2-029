"""AgentCore Platform v1.0 — outer pre_process: InputParse (Step 1)."""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import claims_investigation_service as svc

MAX_INPUT_CHARS = 200_000


class InputParseNode(FunctionNode):
    """Load the investigation document batch, classify doc types, serialize.

    Accepts a JSON payload:
        {"claim_type": "auto", "documents": [{"doc_type": "police_report", "text": "..."}, ...]}
    `doc_type` is optional per document — when absent or not one of the known
    types, a deterministic keyword classifier assigns it. Serializes the
    normalized batch to `validated_input` (JSON string) for the inner subgraph.
    """

    # S-1: outer boundary node — matches agent.yaml required_trust_level (INTERNAL,
    # adjuster-only internal tool per proposal §10 angle 5).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        emit_trace_event("input_parse_started", {"correlation_id": state.get("correlation_id")}, state)

        if not isinstance(raw, str) or not raw.strip():
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputParseNode: empty input"]}
        if len(raw) > MAX_INPUT_CHARS:
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputParseNode: input too large"]}

        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputParseNode: payload must be valid JSON"]}
        if not isinstance(payload, dict):
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputParseNode: payload must be a JSON object"]}

        claim_type = str(payload.get("claim_type", "") or "").strip()
        if not claim_type:
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputParseNode: 'claim_type' is required"]}

        documents = payload.get("documents")
        if not isinstance(documents, list) or not documents:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputParseNode: 'documents' must be a non-empty list"],
            }

        parsed: list[dict[str, Any]] = []
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            text = str(doc.get("text", "") or "")
            if not text.strip():
                continue
            doc_type = str(doc.get("doc_type", "") or "").strip().lower()
            if doc_type not in svc.KNOWN_DOC_TYPES:
                doc_type = svc.classify_doc_type(text)
            parsed.append({"doc_type": doc_type, "text": text})

        if not parsed:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputParseNode: no valid documents after parsing"],
            }

        normalized = {"claim_type": claim_type, "documents": parsed}
        emit_trace_event(
            "input_parsed",
            {"correlation_id": state.get("correlation_id"), "n_documents": len(parsed), "claim_type": claim_type},
            state,
        )
        return {
            "claim_type": claim_type,
            "parsed_documents": parsed,
            "validated_input": json.dumps(normalized, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }
