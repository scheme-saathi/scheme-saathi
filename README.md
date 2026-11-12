# Scheme Saathi

A welfare-scheme navigator for citizens and Common Service Centre (CSC) operators. A person describes their household in English, Hindi or Marathi; the agents ask only the questions that matter, a rule engine decides eligibility for each scheme with the clause it rests on, and a person approves the exact application form before anything is submitted to the (mock) portal.

The model never decides eligibility: reviewed rules in code do.

## Quick start

Run the app locally with Streamlit. You need Python 3.11 or newer (3.12 recommended), an OpenRouter API key and an Auth0 application for sign-in. Run every command from the project root.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
```
```bash
python -m pip install --upgrade pip && python -m pip install -r requirements.txt
```
```bash
cp .env.example .env
```

Fill in `.env`: at least `OPENROUTER_API_KEY`, `SUPERVISOR_MODEL` and `SPECIALIST_MODEL` (for example `openai/gpt-4.1-mini`), `MOCK_PORTAL_AUTH_SECRET` (any long random string), and the `AUTH0_*` settings. Then get the scheme database and start the app:

```bash
python -m servers.schemes_kb.embedding_demo        # downloads the BGE-M3 embedding model once (~2.3 GB)
```
```bash
python -m servers.schemes_kb.import_schemes        # builds data/chroma/ from data/schemes/ (1–2 minutes)
```
```bash
streamlit run app/app_new.py
```

The app opens on <http://localhost:8501> and starts its API on `127.0.0.1:8766`. Instead of building the database you can download the shared one; see [Setup, scheme data and running the app](docs/setup-and-data.md), which also covers Windows, Docker, and using the app screen by screen.

## How one request flows through the system

*[Placeholder: the redrawn architecture diagram, with boxes numbered 1–7 to match the steps below.]*

A son writes in Hindi: "My mother is 62, a widow, lives in Pune district, and has a BPL card. What can she get? Help me apply."

1. **Input guardrails** mask anything that looks like an Aadhaar, bank account or phone number before it reaches a model or a trace, and check the message for injection.
2. **The supervisor** routes the request and shows the citizen a plan: build the profile, find schemes, check the rules, list documents, draft the application.
3. **The intake agent** reads the facts into a typed profile and asks only the question that settles the most open verdicts. The citizen confirms the facts before any final verdict.
4. **The eligibility analyst** shortlists schemes, and the **rule engine** (an MCP server) returns eligible, not eligible or can't tell for each, with the deciding clause and any missing facts. The plan is revised from these results.
5. **The document checker** lists the documents each eligible scheme needs and flags mismatches.
6. **The application agent** drafts the form on the mock portal. The graph pauses with `interrupt()`; the person approves, edits or rejects. Approval is tied to a hash of that exact form, so any edit needs a new approval.
7. **Output guardrails** check that every eligibility claim came from the rule engine and cites a clause, and that unknowns are stated plainly.

Details: [Agents and workflows](docs/agents.md), [Tool inventory](docs/tool-list.md), [Threat model](docs/threat-model.md).

## Repository layout

| Folder | What it holds |
| --- | --- |
| `app/` | Streamlit UI (`app_new.py`) and the FastAPI service it starts (`api.py`) |
| `agents/` | Supervisor, intake, eligibility, document checker and application agents; guardrails; memory; rule extractor |
| `graph/` | LangGraph workflows: the agent team (`agent_workflow.py`), the fixed workflow (`workflow.py`), the single-agent baseline (`baseline.py`), the tool layer (`tools.py`) |
| `servers/` | MCP servers: `schemes_kb`, `rule_engine`, `doc_check`, `mock_portal` |
| `data/` | Scheme records with URL and collection date (`schemes/`), 49 reviewed rule sets (`rules/`), the frozen lesson playbook, the memory policy |
| `evaluation/` | Experiment code (rule extraction, E4, memory evaluation) |
| `observability/` | Metrics, tracing, Prometheus and Grafana |
| `tests/` | Unit and integration tests, the evaluation harness (`tests/evaluation/`) and the red-team suite (`tests/redteam/`) |
| `docs/` | The documents listed below |

## Key design choices

- **Code decides eligibility.** The rule engine is three-valued and fails closed: one unreviewed rule makes a scheme "can't tell". Every verdict cites its clause.
- **Human approval of the exact form.** Nothing is written to the portal without a signed, one-use token bound to the approved form.
- **Least privilege.** Each agent can call only the tools it needs; only the application agent can write.
- **Layered guardrails.** Input masking and injection checks, outside text kept as data, an output guard on eligibility claims, tool-call budgets and rate limits.
- **Memory only with consent.** Long-term facts expire, must be reconfirmed, and are deleted by "Forget my data".

## Results at a glance

| Question | Result | Details |
| --- | --- | --- |
| E1: does the agent team justify its cost? | Given the candidate schemes, no: the fixed workflow and a single agent got 100% of held-out verdicts right, the agent team 54% (3 runs, 50.5–56.8%). Without them, the fixed workflow needs 138 questions a case against the team's 9; the team's scheme shortlist is the gap | [Report §2](docs/evaluation-report.md) |
| E2: do the defences work? | 96 attacks: 79.2% succeed with defences off, 5.2% on (5 known gaps: requests to misstate or hide facts); 0% of legitimate cases blocked | [Report §3](docs/evaluation-report.md), [red-team report](docs/redteam-report.md) |
| E3: did the Reflexion lessons help? | On development schemes, yes; on held-out schemes, no (F1 0.880 → 0.868); the harmful lesson is named | [Report §4](docs/evaluation-report.md) |
| E4: LLM directly vs the rule engine | 91% vs 100% on 95 held-out verdicts; no boundary errors either way; planned question order 138 vs 163 questions with every scheme open | [Report §5](docs/evaluation-report.md) |
| Retrieval (Recall@5) | BM25 0.625 → hybrid 1.000 on development; held-out 0.917 → 1.000 with the query rewrite (3 runs) | [Retrieval evaluation](docs/retrieval-evaluation.md) |
| Memory on vs off | 15.9% fewer questions on a return visit; no verdict changed | [Report §7](docs/evaluation-report.md) |

## Submission documents

| Document | Where |
| --- | --- |
| Architecture diagram and numbered walkthrough | *[Placeholder: to be added]*; walkthrough above |
| Threat model | [docs/threat-model.md](docs/threat-model.md) |
| Memory policy | [docs/memory-policy.md](docs/memory-policy.md), with [document retention](docs/document-retention.md) |
| Evaluation report | [docs/evaluation-report.md](docs/evaluation-report.md) |
| Experiment log | [docs/experiment-log.md](docs/experiment-log.md) |
| Contribution log | *[Placeholder: a draft is in [docs/contribution-log.md](docs/contribution-log.md), pending team verification]* |
| Slides | *[Placeholder: to be added]* |
| Backup demo recording | *[Placeholder: to be added]* |

Supporting documents:

- [Red-team report](docs/redteam-report.md) and the [red-team suite](tests/redteam/README.md)
- [Retrieval evaluation](docs/retrieval-evaluation.md)
- [Tool inventory](docs/tool-list.md)
- [Agents and workflows](docs/agents.md)
- [Setup, scheme data and running the app](docs/setup-and-data.md)
- [Evaluation harness](tests/evaluation/README.md): E1, the claim judge, rule extraction and Reflexion, the single-agent baseline
- [Observability](docs/observability.md), its [architecture](docs/observability-architecture.md) and the [Docker Compose and Grafana quick start](docs/docker-compose-grafana-quickstart.md)
- [Docker deployment guide](docs/docker-deployment-guide.md)

## Tests and evaluations

```bash
python -m pytest -q
```

The full suite needs no model or API key. The experiments each have one runner, a config file and a held-out split that needs `--final`:

| Experiment | Command |
| --- | --- |
| E1 | `python tests/evaluation/run_eval.py --config tests/evaluation/configs/c2_agent_team.json --model <model-id>`, then `tests/evaluation/e1_report.py` |
| E2 | `python tests/redteam/run_redteam.py` (no model needed) |
| E3 | `python tests/evaluation/run_rule_extraction.py --config tests/evaluation/rule_extraction_configs/rx1_playbook_gpt41mini.json`, then `tests/evaluation/e3_report.py` |
| E4 | `python tests/evaluation/run_e4.py --config tests/evaluation/e4_configs/e4_llm_direct_gpt41mini.json` |
| Retrieval | `python -m servers.schemes_kb.evaluate_retrieval --method hybrid --rerank --rewrite --split development` |
| Memory | `python -m evaluation.memory_eval` (no model needed) |

The exact commands behind every reported number are in section 9 of the [evaluation report](docs/evaluation-report.md).

## Demos

1. **Widow pension in Hindi.** Sign in, start a new chat and type the request above in Hindi. Answer the questions, confirm the details, choose an eligible scheme, upload the requested documents and approve the draft.
2. **Refusing to misstate facts and flagging a scam page.** *[Pending: the payment-destination check blocks the scam-page cases in the red-team suite; the misstatement refusal is still being built.]*
3. **"Forget my data".** Open **Saved details**, choose **Forget my data**, and check that the remembered facts are gone.

Also shown: stopping and resuming a conversation, and an edit that invalidates an earlier approval. The screen-by-screen guide is in [Setup, scheme data and running the app](docs/setup-and-data.md).

## Configuration

All settings are environment variables in `.env`; [.env.example](.env.example) lists them.

| Setting | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Model access through OpenRouter |
| `SUPERVISOR_MODEL`, `SPECIALIST_MODEL` | Models for the supervisor and the specialist agents (`provider/model` IDs) |
| `ROUTER_MODEL` | Optional separate routing model; empty uses `SUPERVISOR_MODEL` |
| `CITIZEN_MODEL`, `JUDGE_MODEL` | Evaluation only: the simulated citizen and the claim judge, each from a different model family than the agents |
| `MOCK_PORTAL_AUTH_SECRET` | Signs the one-use approval tokens; submission is blocked without it |
| `AUTH0_*` | Sign-in |
| `SCHEME_SAATHI_CHECKPOINT_DB`, `SCHEME_SAATHI_MEMORY_DIR`, `SCHEME_SAATHI_DOCUMENT_STORE_DIR` | Where conversations, long-term memory and uploaded documents are kept; empty keeps conversations and memory in memory only |
| `OBSERVABILITY_ENABLED`, `METRICS_BEARER_TOKEN`, `TRACING_*` | Metrics and tracing, off by default; see [Observability](docs/observability.md) |
| `SPECIALIST_SCHEME_REACT` | Turns on the optional ReAct loop for general scheme questions |

## Team

*[Placeholder: names and roles, linked to the contribution log once it is in the repository.]*

## Known limits

Personas were labelled by one person, so there is no inter-annotator agreement; the held-out sets are small; the red-team suite tests code defences, not whether a model obeys injected text; and the refusal of requests to misstate facts is still to be built. The full list is in section 8 of the [evaluation report](docs/evaluation-report.md). Results are not official benefit decisions, and nothing is sent to a real government portal.
