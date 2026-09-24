"""AgentCore Platform v1.0 — investigation-batch domain helpers (deterministic).

Service layer: pure deterministic domain helpers (the "Tool" layer the Agent
wraps). No routing, no credentials, no side effects. LLM reasoning (when a
client is configured) refines these results in the nodes; the deterministic
result here is always the guaranteed fallback so the pipeline stays testable
without an LLM.
"""

from __future__ import annotations

from typing import Any
import re

# ── Document taxonomy ────────────────────────────────────────────────────────

POLICE_REPORT = "police_report"
MEDICAL_CERTIFICATE = "medical_certificate"
REPAIR_ESTIMATE = "repair_estimate"
WITNESS_STATEMENT = "witness_statement"

KNOWN_DOC_TYPES = (POLICE_REPORT, MEDICAL_CERTIFICATE, REPAIR_ESTIMATE, WITNESS_STATEMENT)

_DOC_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (POLICE_REPORT, ("police report", "accident report", "official record", "police station")),
    (MEDICAL_CERTIFICATE, ("diagnosis", "medical certificate", "clinic", "physician", "injury type", "傷病名")),
    (REPAIR_ESTIMATE, ("repair estimate", "parts cost", "labor cost", "estimate total", "repair shop")),
    (WITNESS_STATEMENT, ("witness statement", "i saw", "i observed", "testimony", "eyewitness")),
)


def classify_doc_type(text: str) -> str:
    """Deterministic keyword-based document-type classification.

    Returns one of KNOWN_DOC_TYPES, or "unclassified" if no keyword matches.
    """
    low = (text or "").lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS:
        if any(kw in low for kw in keywords):
            return doc_type
    return "unclassified"


# ── Per-claim_type completeness checklist ───────────────────────────────────

CHECKLISTS: dict[str, tuple[str, ...]] = {
    "auto": (POLICE_REPORT, REPAIR_ESTIMATE, WITNESS_STATEMENT),
    "property": (POLICE_REPORT, REPAIR_ESTIMATE),
    "medical": (MEDICAL_CERTIFICATE, WITNESS_STATEMENT),
    "liability": (POLICE_REPORT, WITNESS_STATEMENT, MEDICAL_CERTIFICATE),
}
DEFAULT_CHECKLIST: tuple[str, ...] = (POLICE_REPORT, WITNESS_STATEMENT)


def checklist_for(claim_type: str) -> tuple[str, ...]:
    return CHECKLISTS.get((claim_type or "").strip().lower(), DEFAULT_CHECKLIST)


# ── S-2 PII detection + redaction (要配慮個人情報 / 個人情報) ─────────────────

SENSITIVE_MEDICAL = "sensitive_medical_info"  # 要配慮個人情報 (APPI Art.17)
PERSONAL_INFO = "personal_info"  # 個人情報

_MEDICAL_KEYWORDS = (
    "diagnosis",
    "diagnosed",
    "medical history",
    "treatment",
    "prescription",
    "disease",
    "injury type",
    "既往症",
    "傷病名",
    "カルテ",
)

# Deterministic (non-LLM) PII-shaped patterns.
_PHONE_RE = re.compile(r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b")
_POSTAL_RE = re.compile(r"\b〒?\d{3}-\d{4}\b")
_DOB_RE = re.compile(r"\b\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?\b")
_NAME_LABEL_RE = re.compile(r"((?:name|氏名)\s*[:：]\s*)([^\n,、。]{1,40})", re.IGNORECASE)


def detect_pii_types(text: str) -> list[str]:
    """Return the set of PII categories present in text (no raw values)."""
    low = (text or "").lower()
    types: list[str] = []
    if any(kw.lower() in low for kw in _MEDICAL_KEYWORDS):
        types.append(SENSITIVE_MEDICAL)
    if (
        _PHONE_RE.search(text or "")
        or _POSTAL_RE.search(text or "")
        or _DOB_RE.search(text or "")
        or _NAME_LABEL_RE.search(text or "")
    ):
        types.append(PERSONAL_INFO)
    return types


def redact_pii(text: str) -> str:
    """Redact deterministic PII-shaped spans. Never persists raw matches (S-4)."""
    redacted = text or ""
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    redacted = _POSTAL_RE.sub("[REDACTED_POSTAL]", redacted)
    redacted = _DOB_RE.sub("[REDACTED_DOB]", redacted)
    redacted = _NAME_LABEL_RE.sub(r"\1[REDACTED_NAME]", redacted)
    return redacted


# ── Investigation synthesis ──────────────────────────────────────────────────

_LIABILITY_KEYWORDS = ("fault", "negligen", "responsible for", "at-fault")
_CURRENCY_RE = re.compile(r"[¥￥]\s?([\d,]{3,})|([\d,]{3,})\s?(?:円|yen)", re.IGNORECASE)


def build_timeline(shielded_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One deterministic timeline entry per shielded document, in batch order."""
    timeline = []
    for doc in shielded_documents:
        text = str(doc.get("text", ""))
        timeline.append(
            {
                "source_doc_type": doc.get("doc_type", "unclassified"),
                "excerpt": text[:160],
            }
        )
    return timeline


def build_liability_indicators(shielded_documents: list[dict[str, Any]]) -> list[str]:
    for doc in shielded_documents:
        low = str(doc.get("text", "")).lower()
        if any(kw in low for kw in _LIABILITY_KEYWORDS):
            return ["possible_liability_signal_detected"]
    return ["no_liability_signal_detected"]


def build_coverage_indicators(shielded_documents: list[dict[str, Any]], claim_type: str) -> list[str]:
    present_types = {d.get("doc_type") for d in shielded_documents}
    indicators = [f"claim_type_{(claim_type or 'unspecified').lower()}_pathway"]
    if REPAIR_ESTIMATE in present_types:
        indicators.append("repair_cost_within_scope_pending_adjuster_review")
    if MEDICAL_CERTIFICATE in present_types:
        indicators.append("medical_treatment_cost_pending_adjuster_review")
    return indicators


def build_payout_range(shielded_documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Extract a non-binding estimate range from repair-estimate currency mentions."""
    for doc in shielded_documents:
        if doc.get("doc_type") != REPAIR_ESTIMATE:
            continue
        text = str(doc.get("text", ""))
        match = _CURRENCY_RE.search(text)
        if not match:
            continue
        raw = (match.group(1) or match.group(2) or "").replace(",", "")
        if not raw.isdigit():
            continue
        amount = int(raw)
        return {
            "low": round(amount * 0.9),
            "high": round(amount * 1.15),
            "currency": "JPY",
        }
    return None


# ── Non-suppressible fraud-surface flag ─────────────────────────────────────

_CONTRADICTION_PAIRS = (
    ("no accident", "accident"),
    ("did not witness", "witness"),
    ("denies fault", "admits fault"),
    ("no injury", "injury"),
)


def detect_inconsistencies(shielded_documents: list[dict[str, Any]]) -> list[str]:
    """Deterministic factual-inconsistency surface across the document batch."""
    corpus = " || ".join(str(d.get("text", "")).lower() for d in shielded_documents)
    reasons: list[str] = []
    for negative, positive in _CONTRADICTION_PAIRS:
        if negative in corpus and positive in corpus:
            reasons.append(f"conflicting statements: '{negative}' vs '{positive}'")
    return reasons


# ── Output-scope guardrail (proposal §11 risk #3) ───────────────────────────

DISCLAIMER = (
    "This summary presents indicators and a non-binding estimate range only. It "
    "is not a coverage or payout determination. Final adjudication requires a "
    "licensed adjuster review against full policy data."
)

_BINDING_VERDICT_PHRASES = (
    "coverage is approved",
    "claim is covered",
    "payout is guaranteed",
    "definitively liable",
    "coverage is denied",
    "claim is fully covered",
)


def has_binding_verdict_language(text: str) -> bool:
    low = (text or "").lower()
    return any(phrase in low for phrase in _BINDING_VERDICT_PHRASES)


def is_upstream_error(status: object) -> bool:
    """Whether a prior node already set a terminal ERROR status."""
    return status in ("error", "ERROR") or (status is not None and getattr(status, "value", None) == "error")
