# INS-C2-029 — Unit tests (per node: success + error/edge).

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.completeness_check_node import CompletenessCheckNode
from src.nodes.fraud_surface_flag_node import FraudSurfaceFlagNode
from src.nodes.investigation_synthesize_node import InvestigationSynthesizeNode
from src.nodes.pii_shield_node import PiiShieldNode
from src.nodes.post_process_node import OutputValidateNode
from src.nodes.pre_process_node import InputParseNode
from src.services import claims_investigation_service as svc


def _s(**kw):
    st = {"node_history": [], "error_log": [], "execution_time": {}, "correlation_id": "c"}
    st.update(kw)
    return st


_SAMPLE_PAYLOAD = json.dumps(
    {
        "claim_type": "auto",
        "documents": [
            {"doc_type": "police_report", "text": "Official police report accident. Name: Taro Yamada. Phone 03-1234-5678."},
            {"doc_type": "repair_estimate", "text": "Repair estimate total ¥300,000 for parts and labor."},
            {"doc_type": "witness_statement", "text": "I saw the accident happen at the intersection."},
        ],
    }
)


class TestInputParseNode:
    def setup_method(self):
        self.node = InputParseNode()

    def test_success(self):
        r = self.node.execute(_s(user_input=_SAMPLE_PAYLOAD))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["claim_type"] == "auto"
        assert len(r["parsed_documents"]) == 3
        assert json.loads(r["validated_input"])["claim_type"] == "auto"

    def test_empty(self):
        assert self.node.execute(_s(user_input=""))["status"] == AgentStatus.ERROR

    def test_invalid_json(self):
        assert self.node.execute(_s(user_input="not json"))["status"] == AgentStatus.ERROR

    def test_missing_claim_type(self):
        p = json.dumps({"documents": [{"doc_type": "police_report", "text": "x"}]})
        assert self.node.execute(_s(user_input=p))["status"] == AgentStatus.ERROR

    def test_missing_documents(self):
        p = json.dumps({"claim_type": "auto", "documents": []})
        assert self.node.execute(_s(user_input=p))["status"] == AgentStatus.ERROR

    def test_classifies_doc_type_when_absent(self):
        p = json.dumps({"claim_type": "auto", "documents": [{"text": "diagnosis by physician at clinic"}]})
        r = self.node.execute(_s(user_input=p))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["parsed_documents"][0]["doc_type"] == svc.MEDICAL_CERTIFICATE


class TestPiiShieldNode:
    def setup_method(self):
        self.node = PiiShieldNode()

    def _inner_input(self):
        return json.dumps(
            {
                "claim_type": "auto",
                "documents": [{"doc_type": "police_report", "text": "Name: Taro Yamada. Phone 03-1234-5678."}],
            }
        )

    def test_success_redacts_and_detects(self):
        r = self.node.execute(_s(user_input=self._inner_input()))
        assert r["status"] == AgentStatus.SUCCESS
        assert svc.PERSONAL_INFO in r["detected_pii_types"]
        text = r["shielded_documents"][0]["text"]
        assert "Taro Yamada" not in text
        assert "03-1234-5678" not in text

    def test_missing_documents_errors(self):
        assert self.node.execute(_s(user_input=json.dumps({"claim_type": "auto"})))["status"] == AgentStatus.ERROR

    def test_medical_keyword_detected(self):
        p = json.dumps({"claim_type": "medical", "documents": [{"doc_type": "medical_certificate", "text": "diagnosis: fracture"}]})
        r = self.node.execute(_s(user_input=p))
        assert svc.SENSITIVE_MEDICAL in r["detected_pii_types"]


class _DictLLM:
    """Canonical BaseLLM.complete() shape: {"content": str, ...}."""

    def __init__(self, content: str):
        self._content = content

    def complete(self, messages: list) -> dict:
        assert isinstance(messages, list)
        return {"content": self._content, "tool_calls": [], "model": "fake", "usage": {}}


class _EmptyLLM:
    def complete(self, messages: list) -> dict:
        return {"content": "", "tool_calls": [], "model": "fake", "usage": {}}


class _RaisingLLM:
    def complete(self, messages: list) -> dict:
        raise RuntimeError("provider unavailable")


class TestInvestigationSynthesizeNode:
    def setup_method(self):
        self.node = InvestigationSynthesizeNode()

    def _shielded(self):
        return [
            {"doc_type": "police_report", "text": "official accident report, driver at fault"},
            {"doc_type": "repair_estimate", "text": "estimate total ¥300,000 parts and labor"},
        ]

    def test_success(self):
        r = self.node.execute(_s(shielded_documents=self._shielded(), claim_type="auto"))
        assert r["status"] == AgentStatus.SUCCESS
        assert len(r["incident_timeline"]) == 2
        assert r["liability_indicators"] == ["possible_liability_signal_detected"]
        assert r["payout_estimate_range"]["currency"] == "JPY"

    def test_no_documents_errors(self):
        assert self.node.execute(_s(shielded_documents=[]))["status"] == AgentStatus.ERROR

    def test_upstream_error_propagates(self):
        assert self.node.execute(_s(status=AgentStatus.ERROR.value))["status"] == AgentStatus.ERROR

    def test_no_llm_configured_deterministic_success_no_narrative(self):
        r = self.node.execute(_s(shielded_documents=self._shielded(), claim_type="auto"))
        assert r["status"] == AgentStatus.SUCCESS
        assert "narrative_note" not in r

    def test_llm_configured_two_different_completions_produce_two_different_notes(self):
        node_a = InvestigationSynthesizeNode(llm=_DictLLM("Narrative A"))
        node_b = InvestigationSynthesizeNode(llm=_DictLLM("Narrative B"))
        r_a = node_a.execute(_s(shielded_documents=self._shielded(), claim_type="auto"))
        r_b = node_b.execute(_s(shielded_documents=self._shielded(), claim_type="auto"))
        assert r_a["status"] == AgentStatus.SUCCESS
        assert r_b["status"] == AgentStatus.SUCCESS
        assert r_a["narrative_note"] == "Narrative A"
        assert r_b["narrative_note"] == "Narrative B"
        assert r_a["narrative_note"] != r_b["narrative_note"]

    def test_llm_configured_raises_is_error_not_silent_success(self):
        node = InvestigationSynthesizeNode(llm=_RaisingLLM())
        r = node.execute(_s(shielded_documents=self._shielded(), claim_type="auto"))
        assert r["status"] == AgentStatus.ERROR
        assert r["error_log"]

    def test_llm_configured_empty_content_is_error_not_silent_success(self):
        node = InvestigationSynthesizeNode(llm=_EmptyLLM())
        r = node.execute(_s(shielded_documents=self._shielded(), claim_type="auto"))
        assert r["status"] == AgentStatus.ERROR
        assert r["error_log"]


class TestCompletenessCheckNode:
    def setup_method(self):
        self.node = CompletenessCheckNode()

    def test_missing_documents_reported(self):
        shielded = [{"doc_type": "police_report", "text": "x"}]
        r = self.node.execute(_s(claim_type="auto", shielded_documents=shielded))
        assert r["status"] == AgentStatus.SUCCESS
        assert set(r["missing_documents"]) == {svc.REPAIR_ESTIMATE, svc.WITNESS_STATEMENT}

    def test_all_present_no_missing(self):
        shielded = [
            {"doc_type": svc.POLICE_REPORT, "text": "x"},
            {"doc_type": svc.REPAIR_ESTIMATE, "text": "x"},
            {"doc_type": svc.WITNESS_STATEMENT, "text": "x"},
        ]
        r = self.node.execute(_s(claim_type="auto", shielded_documents=shielded))
        assert r["missing_documents"] == []

    def test_upstream_error(self):
        assert self.node.execute(_s(status="error"))["status"] == AgentStatus.ERROR


class TestFraudSurfaceFlagNode:
    def setup_method(self):
        self.node = FraudSurfaceFlagNode()

    def test_no_inconsistency(self):
        shielded = [{"doc_type": "police_report", "text": "accident occurred at intersection"}]
        r = self.node.execute(_s(shielded_documents=shielded))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["fraud_surface_flag"]["flagged"] is False

    def test_inconsistency_detected(self):
        shielded = [
            {"doc_type": "police_report", "text": "there was an accident"},
            {"doc_type": "witness_statement", "text": "witness states no accident occurred"},
        ]
        r = self.node.execute(_s(shielded_documents=shielded))
        assert r["fraud_surface_flag"]["flagged"] is True
        assert r["fraud_surface_flag"]["reasons"]

    def test_upstream_error(self):
        assert self.node.execute(_s(status="ERROR"))["status"] == AgentStatus.ERROR


class TestOutputValidateNode:
    def setup_method(self):
        self.node = OutputValidateNode()

    def test_success(self):
        r = self.node.execute(
            _s(
                claim_type="auto",
                incident_timeline=[{"source_doc_type": "police_report", "excerpt": "x"}],
                fraud_surface_flag={"flagged": False, "reasons": []},
            )
        )
        assert r["status"] == AgentStatus.SUCCESS
        assert r["investigation_summary"]["disclaimer"] == svc.DISCLAIMER
        assert "fraud_surface_flag" in r["investigation_summary"]

    def test_upstream_error(self):
        assert self.node.execute(_s(status="error"))["status"] == AgentStatus.ERROR

    def test_s3_gate_missing_fraud_flag_blocked(self):
        bad = _s(investigation_summary={"disclaimer": svc.DISCLAIMER})
        assert self.node._extra_security_gate_output(bad)["status"] == AgentStatus.ERROR

    def test_s3_gate_missing_disclaimer_blocked(self):
        bad = _s(investigation_summary={"fraud_surface_flag": {"flagged": False, "reasons": []}})
        assert self.node._extra_security_gate_output(bad)["status"] == AgentStatus.ERROR

    def test_s3_gate_binding_verdict_blocked(self):
        bad_summary = {
            "fraud_surface_flag": {"flagged": False, "reasons": []},
            "disclaimer": svc.DISCLAIMER,
            "note": "coverage is approved",
        }
        assert self.node._extra_security_gate_output(_s(investigation_summary=bad_summary))["status"] == AgentStatus.ERROR

    def test_s3_gate_passes_valid(self):
        good_summary = {"fraud_surface_flag": {"flagged": False, "reasons": []}, "disclaimer": svc.DISCLAIMER}
        good = _s(investigation_summary=good_summary)
        assert self.node._extra_security_gate_output(good) is good
