# Workflow graph

Generated from `graph/agent_workflow.py` by `python -m graph.diagram --write`; do not edit by hand.
Supervisor-first architecture: All requests flow through Supervisor FIRST for input validation,
language/intent detection, and routing to specialists (Intake, Eligibility, DocumentChecker, Application).
Dashed arrows are conditional edges based on Supervisor's routing decision.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	supervisor(supervisor)
	intake(intake)
	intake_question(intake_question)
	eligibility(eligibility)
	document_checker(document_checker)
	application(application)
	approval(approval)
	approval_end(approval_end)
	submit(submit)
	finish(finish)
	respond(respond)
	__end__([<p>__end__</p>]):::last
	__start__ --> supervisor;
	application -.-> approval;
	application -.-> finish;
	approval -.-> approval_end;
	approval -.-> submit;
	document_checker -.-> application;
	document_checker -.-> finish;
	eligibility -.-> document_checker;
	eligibility -.-> finish;
	eligibility -.-> intake_question;
	intake --> eligibility;
	supervisor -.-> document_checker;
	supervisor -. &nbsp;application&nbsp; .-> intake;
	supervisor -.-> respond;
	approval_end --> __end__;
	finish --> __end__;
	intake_question --> __end__;
	respond --> __end__;
	submit --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
