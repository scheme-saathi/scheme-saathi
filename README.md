# Scheme Saathi

A welfare-scheme navigator for citizens and CSC operators. It identifies eligible government schemes, explains the reasons in the user's language, and prepares an application for a person to approve before submission.

## Layout

- `servers/` - MCP servers: `schemes_kb`, `rule_engine`, `doc_check`, `mock_portal`
- `agents/` - intake, eligibility, document checker, application agents
- `graph/` - LangGraph orchestration and checkpointing
- `tests/` - unit and evaluation tests
- `data/schemes/` - scheme corpus (URL and collection date recorded per scheme)
- `docs/` - tool list, threat model, memory policy

## Setup

Requires Python 3.11+. Copy `.env.example` to `.env` and add your OpenRouter key. Never commit `.env`.
