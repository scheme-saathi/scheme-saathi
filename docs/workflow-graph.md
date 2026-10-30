# Workflow graph

Generated from `graph/workflow.py` by `python -m graph.diagram --write`; do not edit by hand.
Dashed arrows are conditional edges.

- `validate` is the self-correction check: a failed draft returns to `draft` (at most 3 attempts), then goes to `escalate` for a person.
- `approval` pauses with `interrupt()`. Approve must carry the hash of the exact form; edit re-runs `eligibility` and needs a new approval; anything else ends the run.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	plan(plan)
	intake(intake)
	eligibility(eligibility)
	documents(documents)
	draft(draft)
	validate(validate)
	escalate(escalate)
	approval(approval)
	submit(submit)
	__end__([<p>__end__</p>]):::last
	__start__ --> plan;
	approval -.-> __end__;
	approval -.-> eligibility;
	approval -.-> submit;
	documents --> draft;
	draft -.-> __end__;
	draft -.-> validate;
	eligibility -.-> documents;
	eligibility -.-> intake;
	intake --> eligibility;
	plan --> intake;
	validate -.-> approval;
	validate -.-> draft;
	validate -.-> escalate;
	escalate --> __end__;
	submit --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
