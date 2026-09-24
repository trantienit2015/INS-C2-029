# INS-C2-029 — Integration test: full graph compile + invoke.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


class FakeLLM:
    def complete(self, *a, **k):
        return "synthesis narrative"


def _ctx(session="it-1"):
    return InvocationContext(session_id=session, caller_trust_level=TrustLevel.INTERNAL, caller_id="tester")


def _agent():
    a = Graph(config={"llm": FakeLLM(), "max_retry": 1})
    a.compile()
    return a


def _payload(**overrides):
    base = {
        "claim_type": "auto",
        "documents": [
            {"doc_type": "police_report", "text": "official accident report, driver at fault"},
            {"doc_type": "repair_estimate", "text": "estimate total ¥300,000 for parts and labor"},
            {"doc_type": "witness_statement", "text": "witness saw the accident happen"},
        ],
    }
    base.update(overrides)
    return json.dumps(base)


def test_full_pipeline_success():
    result = _agent().invoke(_payload(), ctx=_ctx())
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    nh = result.get("node_history") or []
    assert len(nh) >= 5, f"expected >=5 nodes, got {len(nh)}: {nh}"
    summary = result.get("output") or {}
    assert isinstance(summary, dict)
    assert summary.get("disclaimer")
    assert "fraud_surface_flag" in summary
    assert summary["missing_documents"] == []


def test_empty_input_errors():
    result = _agent().invoke("", ctx=_ctx("it-2"))
    assert result["status"] in (
        AgentStatus.ERROR,
        AgentStatus.ERROR.value,
        AgentStatus.CANCELLED,
        AgentStatus.CANCELLED.value,
    )


def test_missing_documents_surfaced_in_checklist():
    payload = _payload(documents=[{"doc_type": "police_report", "text": "official accident report"}])
    result = _agent().invoke(payload, ctx=_ctx("it-3"))
    summary = result.get("output") or {}
    assert summary.get("missing_documents")


def test_fraud_flag_and_no_binding_verdict_in_output():
    payload = _payload(
        documents=[
            {"doc_type": "police_report", "text": "there was an accident, driver at fault"},
            {"doc_type": "witness_statement", "text": "witness states no accident occurred"},
        ]
    )
    result = _agent().invoke(payload, ctx=_ctx("it-4"))
    summary = result.get("output") or {}
    assert summary.get("fraud_surface_flag", {}).get("flagged") is True
    blob = json.dumps(result, default=str).lower()
    assert "coverage is approved" not in blob and "claim is fully covered" not in blob
    assert "sk-" not in blob and "eyj" not in blob
