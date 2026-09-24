"""AgentCore Platform v1.0 — INS-C2-029 state schema."""

# Flat TypedDict only (msgpack-safe). Extend AgentState with agent-specific
# fields; no credentials, secrets, or Pydantic models in State.

from typing import NotRequired

from framework.schemas.agent_state import AgentState


# Type-check note: the wheel ships no py.typed, so mypy resolves AgentState to Any
# and reports every NotRequired below as valid-type. The fields are correct (the state
# contract requires NotRequired) -- the report is a packaging artifact, suppressed per field.
# Drop these ignores once the wheel ships py.typed.
class State(AgentState):
    """Insurance Claim Investigation Report Summarization Agent state.

    Shared fields (user_input, validated_input, status, node_history, result,
    formatted_output, ...) are inherited from AgentState. All agent-specific
    fields are NotRequired[...] (state-safety contract) and read via state.get(...).
    """

    # Outer pre_process (InputParse) output.
    claim_type: NotRequired[str]  # type: ignore[valid-type]
    parsed_documents: NotRequired[list[dict]]  # type: ignore[valid-type]

    # Inner step 1: PiiShield output.
    shielded_documents: NotRequired[list[dict]]  # type: ignore[valid-type]
    detected_pii_types: NotRequired[list[str]]  # type: ignore[valid-type]

    # Inner step 2: InvestigationSynthesize output.
    incident_timeline: NotRequired[list[dict]]  # type: ignore[valid-type]
    liability_indicators: NotRequired[list[str]]  # type: ignore[valid-type]
    coverage_indicators: NotRequired[list[str]]  # type: ignore[valid-type]
    payout_estimate_range: NotRequired[dict]  # type: ignore[valid-type]
    narrative_note: NotRequired[str]  # type: ignore[valid-type]

    # Inner step 3: CompletenessCheck output.
    missing_documents: NotRequired[list[str]]  # type: ignore[valid-type]

    # Inner step 4: FraudSurfaceFlag output (non-suppressible — re-verified at S-3).
    fraud_surface_flag: NotRequired[dict]  # type: ignore[valid-type]

    # Outer post_process (OutputValidate) assembled final memo.
    investigation_summary: NotRequired[dict]  # type: ignore[valid-type]
