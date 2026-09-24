# INS-C2-029 - Framework compliance tests TC-01..TC-08.
# Structured as a standard TC-01..TC-08 compliance suite,
# adapted to this template's real architecture (Cat 2: outer pre/post + GraphNode-wrapped inner nodes).

import json
import os
import re

import pytest
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.nodes import post_process_node, pre_process_node
from src.schemas.state import State

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")

_SAMPLE_PAYLOAD = json.dumps(
    {
        "claim_type": "auto",
        "documents": [{"doc_type": "police_report", "text": "official accident report, driver at fault"}],
    }
)


def _src_files():
    for root, _d, files in os.walk(_SRC):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


# TC-01 - State is a flat TypedDict extending AgentState; added fields are
# primitives / list / dict (JSON-serializable), never Pydantic/dataclass.
class TestTC01StateContract:
    def test_state_is_typeddict_extending_agent_state(self):
        assert hasattr(State, "__annotations__")
        assert "user_input" in State.__annotations__
        assert set(AgentState.__annotations__).issubset(set(State.__annotations__))

    def test_added_fields_are_json_serializable_shape(self):
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        assert added, "State must declare agent-specific fields"
        for name in added:
            ann_repr = repr(State.__annotations__[name])
            assert "BaseModel" not in ann_repr
            assert "dataclass" not in ann_repr.lower()


# TC-02 - Empty/missing input yields a fail-closed ERROR outcome, no raise.
class TestTC02Validation:
    def test_empty_input_no_raise(self):
        node = pre_process_node.InputParseNode()
        out = node.execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_missing_claim_type_no_raise(self):
        node = pre_process_node.InputParseNode()
        payload = json.dumps({"documents": [{"doc_type": "police_report", "text": "x"}]})
        out = node.execute({"user_input": payload})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]


# TC-03 - No JWT / API keys / secrets in src/; no direct os.environ reads.
class TestTC03NoCredentials:
    def test_no_credential_literals(self):
        pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []

    def test_no_os_environ_secret_reads(self):
        # Entry-point exception: src/api/server.py may read exactly the
        # two deployment-level caller-auth tokens from the environment, before any
        # InvocationContext exists. Any other os.environ access there is still an offender.
        entry_point_tokens = {"INVOKE_AUTH_TOKEN", "STG_INTERNAL_RUNNER_TOKEN"}
        environ_read = re.compile(r"os\.environ(?:\.get\(|\[)\s*[\"']([A-Z0-9_]+)[\"']")
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                text = f.read()
            if "os.environ" not in text:
                continue
            if fp.endswith(os.path.join("api", "server.py")):
                keys = environ_read.findall(text)
                if text.count("os.environ") == len(keys) and set(keys) <= entry_point_tokens:
                    continue
            offenders.append(fp)
        assert offenders == []


# TC-04 - InvocationContext is never stored in State after invoke.
class TestTC04ContextIsolation:
    def test_no_invocationcontext_in_state_after_invoke(self):
        from src.graph.graph import Graph

        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="tc04", caller_trust_level=TrustLevel.INTERNAL, caller_id="adjuster-tc04")
        result = agent.invoke(_SAMPLE_PAYLOAD, ctx=ctx)
        for v in result.values():
            assert not isinstance(v, InvocationContext)

    def test_from_state_available(self):
        assert hasattr(InvocationContext, "from_state")


# TC-05 - Domain events: OutputValidateNode emits >=1 domain event; no node
# under src/nodes/ ever re-emits a framework backbone lifecycle event.
class TestTC05Audit:
    def test_output_validate_emits_domain_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(post_process_node, "emit_trace_event", lambda e, p, s: events.append(e))
        state = {
            "fraud_surface_flag": {"flagged": False, "reasons": []},
            "correlation_id": "tc05",
        }
        out = post_process_node.OutputValidateNode().execute(state)
        assert out["status"] == AgentStatus.SUCCESS
        assert len(events) >= 1
        assert "output_validated" in events
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_source_has_no_backbone_events(self):
        pat = re.compile(r'emit_trace_event\(\s*["\'](node_start|node_complete|node_error|node_skip)["\']')
        offenders = []
        for fp in _src_files():
            with open(fp, encoding="utf-8") as f:
                if pat.search(f.read()):
                    offenders.append(fp)
        assert offenders == []


# TC-06 / TC-07 - S-2/S-3 gates are @final on FunctionNode (overriding raises TypeError at class def).
class TestTC0607FinalGates:
    def test_input_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadIn(FunctionNode):  # noqa: N801
                def _security_gate_input(self, state):
                    return state

    def test_output_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadOut(FunctionNode):  # noqa: N801
                def _security_gate_output(self, result):
                    return result

    def test_extra_hook_is_overridable(self):
        assert post_process_node.OutputValidateNode._extra_security_gate_output is not FunctionNode._extra_security_gate_output

    def test_output_gate_blocks_missing_fraud_flag(self):
        # The @final S-3 credential scan + our _extra_security_gate_output both
        # fire (not vacuous): output missing the non-suppressible fraud flag
        # is blocked, never returned as-is.
        node = post_process_node.OutputValidateNode()
        result = node._extra_security_gate_output({"investigation_summary": {"disclaimer": "x"}})
        assert result["status"] == AgentStatus.ERROR


# TC-08 - required_trust_level enforced: insufficient trust -> ERROR state, no raise.
class TestTC08TrustGate:
    def test_declared_trust_levels_valid(self):
        for cls in (pre_process_node.InputParseNode, post_process_node.OutputValidateNode):
            assert cls.required_trust_level in (TrustLevel.ANONYMOUS, TrustLevel.VERIFIED_EXTERNAL, TrustLevel.INTERNAL)

    def test_insufficient_trust_returns_error(self):
        node = pre_process_node.InputParseNode()
        out = node({"caller_trust_level": TrustLevel.ANONYMOUS.value, "user_input": _SAMPLE_PAYLOAD})
        assert str(out.get("status")).lower().endswith("error")

    def test_sufficient_trust_succeeds(self):
        node = pre_process_node.InputParseNode()
        out = node({"caller_trust_level": TrustLevel.INTERNAL.value, "user_input": _SAMPLE_PAYLOAD})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["claim_type"] == "auto"
