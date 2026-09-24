# INS-C2-029 — Insurance Claim Investigation Report Summarization Agent

> **Category**: Cat 2 (orchestrates multiple steps to accomplish a specific use case)
> **Industry**: INS

## Overview

Summarises a batch of insurance claim investigation documents into a structured, non-binding
memo for a claims adjuster. The input is a JSON object with a required claim_type (for example
auto, property, medical or liability) and a non-empty documents list, where each document has
text and an optional doc_type (police_report, medical_certificate, repair_estimate or
witness_statement). Input that is empty, larger than 200,000 characters, not valid JSON, or has
no usable documents is rejected. The entry node requires an internal-level caller.

Documents without a known type are classified by keywords. Each document is scanned for medical
keywords and for phone numbers, postal codes, dates of birth and labelled names; those values
are masked before any further processing. The agent then builds an incident timeline (one
excerpt per document), a liability signal, coverage indicators, and a payout estimate range
derived from the first yen amount in a repair estimate (90% to 115% of that amount). It lists
documents missing from a fixed per-claim-type checklist and raises a fraud-surface flag when
statements contradict each other (for example "no injury" alongside "injury"). The memo
contains all of these plus a fixed disclaimer stating that it is not a coverage or payout
decision; output containing definitive coverage or payout wording is blocked. No knowledge base
is used.

A language model is optional. When a client is supplied through the graph configuration it
writes a short narrative note from the timeline and liability indicators; a failed or empty
reply ends the run with an error. Without a client the memo is produced deterministically and
has no narrative note. The bundled HTTP entry point does not supply a client.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | 3.11 or later |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specification
```

See `docs/02_design.md` for the design and `docs/03_test_spec.md` for the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
