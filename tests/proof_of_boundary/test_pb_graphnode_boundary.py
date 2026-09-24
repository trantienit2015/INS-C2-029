# INS-C2-029 - GraphNode boundary test (Cat 2 outer main-slot wrapper).
#
# Why this test exists: PB-6 (test_pb_invoke_order.py) only self-discovers plain
# BaseNode subclasses under src/nodes/. InvestigationGraphNode lives under
# src/graph/graph.py (deliberately, per its own docstring: "so the PB-6
# invoke-order probe does not mis-assert its deliberately-delegated
# lifecycle"). That placement does not exempt the outer GraphNode from test
# coverage. This is the exact test-scope blind spot pattern flagged by
# post-release audit (review-scan-checklist.md 3d): the outer GraphNode is a
# real security boundary (first node to receive the caller's validated input)
# that no PB-6 probe reaches.
#
# framework/nodes/graph_node.py: GraphNode extends BaseNode directly (not
# FunctionNode), so it has no _security_gate_input/_security_gate_output at
# all - S-2/S-3 gating is delegated entirely to the outer InputParseNode /
# OutputValidateNode and the inner subgraph's own FunctionNode chain (starting
# with PiiShieldNode). This test proves that delegation is real, not absent.

from framework.nodes.function_node import FunctionNode
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import InvestigationGraphNode
from src.nodes.pii_shield_node import PiiShieldNode
from src.nodes.pre_process_node import InputParseNode


def _node():
    return InvestigationGraphNode(llm=None)


class TestGraphNodeS1TrustGate:
    """S-1: the outer main-slot GraphNode declares the trust gate like any BaseNode."""

    def test_declares_required_trust_level(self):
        assert isinstance(InvestigationGraphNode.required_trust_level, TrustLevel)

    def test_matches_sibling_outer_pre_process_node(self):
        # Outer nodes on the backbone (pre_process = InputParseNode) declare
        # INTERNAL per config/agent.yaml required_trust_level. The outer
        # GraphNode wrapper (main slot) must stay consistent with that level,
        # not silently diverge.
        assert InvestigationGraphNode.required_trust_level == InputParseNode.required_trust_level


class TestGraphNodeBoundaryMapping:
    """Boundary mapping: extract_input()/merge_output() do not leak raw state/subgraph dicts."""

    def test_extract_input_only_reads_validated_input(self):
        node = _node()
        state = {
            "validated_input": '{"claim_type": "auto", "documents": []}',
            "user_input": "raw caller text should not leak",
            "unrelated_secret_field": "must-not-appear",
            "correlation_id": "c",
        }
        extracted = node.extract_input(state)

        assert isinstance(extracted, str)
        assert "unrelated_secret_field" not in extracted
        assert "must-not-appear" not in extracted

    def test_merge_output_maps_fields_explicitly_no_raw_passthrough(self):
        node = _node()
        state = {"correlation_id": "c"}
        sub_result = {
            "shielded_documents": [{"doc_type": "police_report", "text": "redacted"}],
            "detected_pii_types": ["personal_info"],
            "incident_timeline": [{"source_doc_type": "police_report", "excerpt": "x"}],
            "liability_indicators": [],
            "coverage_indicators": [],
            "payout_estimate_range": None,
            "missing_documents": [],
            "fraud_surface_flag": {"flagged": False, "reasons": []},
            "narrative_note": None,
            "status": "success",
            # A field the subgraph might carry internally that must NOT leak
            # into the outer state unless merge_output() explicitly maps it.
            "internal_debug_trace": "should-not-be-copied",
        }
        merged = node.merge_output(state, sub_result)

        assert "internal_debug_trace" not in merged
        assert merged["status"] == "success"
        assert merged["shielded_documents"] == sub_result["shielded_documents"]


class TestGraphNodeDelegatesGatingToInnerSubgraph:
    """Delegation has a real target: the inner subgraph's entry node runs S-1/S-2/S-3."""

    def test_inner_entry_node_is_a_function_node_with_security_gates(self):
        # PiiShieldNode is the inner subgraph's entry point
        # (investigation_workflow_graph.py: START -> pii_shield). It is a
        # FunctionNode, so the framework's @final S-2/S-3 gates run on every
        # invocation of the inner subgraph - this is where the GraphNode's
        # skipped lifecycle is actually enforced, not omitted.
        assert issubclass(PiiShieldNode, FunctionNode)
        assert hasattr(PiiShieldNode, "required_trust_level")
