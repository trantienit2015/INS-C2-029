# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `Graph` (src/graph/graph.py — outer) + `InvestigationGraphNode` (same file) + `InvestigationWorkflowGraph` (src/graph/investigation_workflow_graph.py — inner)
- **L1 Base**: AgentBaseGraph (outer) — Cat 2, three-layer composition
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

Cat 2 pattern: outer `AgentBaseGraph` backbone wraps the domain workflow behind
a `GraphNode` in the `main` slot; the inner `BaseGraph` subgraph carries the
4 core business steps.

```
OUTER (AgentBaseGraph):
  initialize → pre_process(InputParse) → main(InvestigationGraphNode) → post_process(OutputValidate) → finalize
                                              │ get_subgraph().invoke(extract_input(state), ctx)
                                              ▼
INNER (BaseGraph — investigation_workflow_graph.py):
  START → pii_shield → investigation_synthesize → completeness_check → fraud_surface_flag → END
```

### Node Configuration

| Node | Layer | Responsibility | Input State | Output State | Inherits/Overrides |
|------|-------|-----------------|--------------|--------------|---------------------|
| initialize | outer | schema_version, session_id, trust_level | — | — | InitializeNode (default) |
| pre_process (`InputParseNode`) | outer | Load doc batch, classify doc types, serialize `validated_input` | `user_input` (JSON: claim_type + documents) | `claim_type`, `parsed_documents`, `validated_input` | FunctionNode |
| main (`InvestigationGraphNode`) | outer | Wrap inner workflow; S-4 dispatch/completion events | `validated_input` | merged inner outputs | GraphNode |
| ↳ pii_shield (`PiiShieldNode`) | inner | Detect 要配慮個人情報/個人情報, redact pre-LLM (Step 2) | inner `user_input` (JSON) | `shielded_documents`, `detected_pii_types` | FunctionNode |
| ↳ investigation_synthesize (`InvestigationSynthesizeNode`) | inner | Timeline, liability/coverage indicators, non-binding payout range (Step 3) | `shielded_documents`, `claim_type` | `incident_timeline`, `liability_indicators`, `coverage_indicators`, `payout_estimate_range` | FunctionNode |
| ↳ completeness_check (`CompletenessCheckNode`) | inner | Per-`claim_type` checklist → missing docs (Step 4) | `shielded_documents`, `claim_type` | `missing_documents` | FunctionNode |
| ↳ fraud_surface_flag (`FraudSurfaceFlagNode`) | inner | Non-suppressible factual-inconsistency flag (Step 5) | `shielded_documents` | `fraud_surface_flag` | FunctionNode |
| post_process (`OutputValidateNode`) | outer | Assemble final memo; S-3 non-suppressible re-check (Step 6) | merged fields | `investigation_summary`, `formatted_output` | FunctionNode |
| finalize | outer | response_metadata, total_time_ms | — | — | FinalizeNode (default) |

### Data Flow

```
START → initialize → pre_process → main(GraphNode→inner subgraph) → post_process → finalize → END
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `claim_type` | `NotRequired[str]` | Selects the per-claim completeness checklist | No |
| `parsed_documents` | `NotRequired[list[dict]]` | Outer InputParse output (doc_type + text) | No |
| `shielded_documents` | `NotRequired[list[dict]]` | Inner PiiShield output (redacted text) | No |
| `detected_pii_types` | `NotRequired[list[str]]` | PII category tags (no raw values) | No |
| `incident_timeline` | `NotRequired[list[dict]]` | Synthesized timeline entries | No |
| `liability_indicators` | `NotRequired[list[str]]` | Non-binding liability signal tags | No |
| `coverage_indicators` | `NotRequired[list[str]]` | Non-binding coverage-applicability tags | No |
| `payout_estimate_range` | `NotRequired[dict]` | `{low, high, currency}` non-binding estimate | No |
| `missing_documents` | `NotRequired[list[str]]` | Checklist gaps vs `claim_type` | No |
| `fraud_surface_flag` | `NotRequired[dict]` | `{flagged, reasons}` — non-suppressible (S-3 re-checked) | No |
| `investigation_summary` | `NotRequired[dict]` | Final assembled memo (post_process output) | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [x] ConnectionPolicy (retry/timeout strategy) — `max_retry` in `config/agent.yaml`
- [ ] SecurityViolationError — not raised directly; fail-closed via `AgentStatus.ERROR` dict returns
- [x] S-2: PII detection is implemented as explicit business logic in `PiiShieldNode.execute()`
      (Step 2 of the workflow, not the `_extra_security_gate_input()` hook — this mirrors the
      deterministic-scan pattern used by sibling INS templates, since PII shielding here IS the
      named business step, not a supplementary domain check)
- [x] S-3: `_extra_security_gate_output()` on `OutputValidateNode` — preservation variant:
      re-verifies the non-suppressible `fraud_surface_flag` key + mandatory disclaimer are present
      in the node's own output, and blocks binding coverage/payout verdict language
      (**MUST NOT override `_security_gate_output()`** — `TypeError` at class definition)
- [x] S-4: `emit_trace_event()` — at least one domain-specific event inside each `execute()`
      of every node (including the `GraphNode` wrapper's `extract_input()`/`merge_output()` hooks)
      (**mandatory**; do NOT emit `node_start` / `node_complete` / `node_error` —
      `BaseNode.__call__()` emits these automatically; duplicates corrupt audit trail)

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — `InvestigationGraphNode` wraps `InvestigationWorkflowGraph`
- **Composition target**: `src/graph/investigation_workflow_graph.py` (inner `BaseGraph`)
- **Error propagation strategy**: propagate (`error_strategy = "propagate"`, fail-fast on inner error)

## Security Model (S-1 trust levels)

- `agent.yaml required_trust_level`: `INTERNAL` (adjuster-only internal tool, proposal §10 angle 5)
- Outer nodes (`InputParseNode`, `OutputValidateNode`): `INTERNAL` — matches agent boundary default
- Inner subgraph nodes (`PiiShieldNode`, `InvestigationSynthesizeNode`, `CompletenessCheckNode`,
  `FraudSurfaceFlagNode`): `ANONYMOUS` — trust is authenticated once at the outer backbone; inner
  nodes must not re-demand `INTERNAL` (privilege-escalation anti-pattern)

## Output-Scope Guardrail (proposal §11 risk #3)

The synthesized memo surfaces **indicators and a non-binding estimate range only** —
never a binding coverage/payout determination. `OutputValidateNode._extra_security_gate_output()`
blocks any output containing binding-verdict phrasing (e.g. "coverage is approved",
"claim is fully covered") and requires the mandatory disclaimer to be present verbatim.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Fixed multi-step pipeline, no autonomous loop needed |
| Composition pattern | Standalone flat nodes | GraphNode + inner BaseGraph | GraphNode + inner BaseGraph | Cat 2 mandate — `gate-composition` requires GraphNode-wrapped inner workflow, not a flat MainNode |
| PII shield placement | `_extra_security_gate_input()` hook | Explicit business-logic node (`PiiShieldNode`) | Explicit business-logic node | PII shielding is a named business step in the proposal (Step 2), not a supplementary check |
| Fraud flag enforcement | Best-effort node output | Non-suppressible S-3 re-check | Non-suppressible S-3 re-check | 改正犯収法 2026 requires the flag to survive any downstream override attempt |
