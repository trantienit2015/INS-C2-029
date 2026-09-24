"""AgentCore Platform v1.0 — INS-C2-029 inner investigation workflow (Cat 2).

Instantiated by InvestigationGraphNode.get_subgraph(). Receives only the JSON
string user_input (seeded from the outer validated_input); the first inner
node reconstructs the payload.

Pipeline: pii_shield → investigation_synthesize → completeness_check → fraud_surface_flag
"""

from typing import Any
from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.completeness_check_node import CompletenessCheckNode
from src.nodes.fraud_surface_flag_node import FraudSurfaceFlagNode
from src.nodes.investigation_synthesize_node import InvestigationSynthesizeNode
from src.nodes.pii_shield_node import PiiShieldNode
from src.schemas.state import State


class InvestigationWorkflowGraph(BaseGraph):
    """Inner multi-step investigation-synthesis workflow."""

    @property
    def name(self) -> str:
        return "ins_c2_029_investigation_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        pass

    def register_nodes(self) -> None:
        llm = self.config.get("llm") if hasattr(self, "config") else None
        self._nodes["pii_shield"] = PiiShieldNode()
        self._nodes["investigation_synthesize"] = InvestigationSynthesizeNode(llm=llm)
        self._nodes["completeness_check"] = CompletenessCheckNode()
        self._nodes["fraud_surface_flag"] = FraudSurfaceFlagNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "pii_shield")
        self._sg.add_edge("pii_shield", "investigation_synthesize")
        self._sg.add_edge("investigation_synthesize", "completeness_check")
        self._sg.add_edge("completeness_check", "fraud_surface_flag")
        self._sg.add_edge("fraud_surface_flag", END)

    def route(self, state: AgentState) -> str:
        return END if state.get("status") == AgentStatus.ERROR.value else "fraud_surface_flag"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "shielded_documents": state.get("shielded_documents", []),
            "detected_pii_types": state.get("detected_pii_types", []),
            "incident_timeline": state.get("incident_timeline", []),
            "liability_indicators": state.get("liability_indicators", []),
            "coverage_indicators": state.get("coverage_indicators", []),
            "payout_estimate_range": state.get("payout_estimate_range"),
            "missing_documents": state.get("missing_documents", []),
            "fraud_surface_flag": state.get("fraud_surface_flag"),
            "narrative_note": state.get("narrative_note"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
