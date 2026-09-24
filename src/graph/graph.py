"""AgentCore Platform v1.0 — INS-C2-029 outer graph (Cat 2).

Outer (AgentBaseGraph): initialize → pre_process(InputParse) → main(InvestigationGraphNode)
→ post_process(OutputValidate) → finalize.
Inner (BaseGraph): pii_shield → investigation_synthesize → completeness_check → fraud_surface_flag.

The GraphNode wrapper lives in THIS file (not src/nodes/) so the PB-6 invoke-order
probe does not mis-assert its deliberately-delegated lifecycle.
"""

from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.post_process_node import OutputValidateNode
from src.nodes.pre_process_node import InputParseNode
from src.schemas.state import State


class InvestigationGraphNode(GraphNode):
    """Wraps the inner investigation-synthesis workflow (main slot)."""

    # S-1: outer main-slot GraphNode — matches agent.yaml required_trust_level (INTERNAL).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def __init__(self, llm: Any = None) -> None:
        super().__init__()
        self._llm = llm

    def get_subgraph(self) -> Any:
        from src.graph.investigation_workflow_graph import InvestigationWorkflowGraph

        sg = InvestigationWorkflowGraph(config=self._parent_config())
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        # S-4: runs inside GraphNode.execute() — audit the dispatch into the inner subgraph.
        emit_trace_event(
            "investigation_workflow_dispatched",
            {"correlation_id": state.get("correlation_id")},
            state,
        )
        return cast(str, state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        # S-4: runs inside GraphNode.execute() — audit the subgraph outcome merged back out.
        emit_trace_event(
            "investigation_workflow_completed",
            {
                "correlation_id": state.get("correlation_id"),
                "fraud_flagged": (sub_result.get("fraud_surface_flag") or {}).get("flagged", False),
            },
            state,
        )
        return {
            "shielded_documents": sub_result.get("shielded_documents", []),
            "detected_pii_types": sub_result.get("detected_pii_types", []),
            "incident_timeline": sub_result.get("incident_timeline", []),
            "liability_indicators": sub_result.get("liability_indicators", []),
            "coverage_indicators": sub_result.get("coverage_indicators", []),
            "payout_estimate_range": sub_result.get("payout_estimate_range"),
            "missing_documents": sub_result.get("missing_documents", []),
            "fraud_surface_flag": sub_result.get("fraud_surface_flag"),
            "narrative_note": sub_result.get("narrative_note"),
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {"llm": self._llm}


class Graph(AgentBaseGraph):
    """INS-C2-029 — Insurance Claim Investigation Report Summarization Agent."""

    @property
    def name(self) -> str:
        return "ins-c2-029"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()
        llm = self.config.get("llm") if hasattr(self, "config") else None
        self._nodes["pre_process"] = InputParseNode()
        self._nodes["main"] = InvestigationGraphNode(llm=llm)
        self._nodes["post_process"] = OutputValidateNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
