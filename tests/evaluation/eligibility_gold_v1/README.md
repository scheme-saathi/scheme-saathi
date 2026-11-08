# Eligibility gold set v1

71 synthetic persona cases in 22 families, with human-labelled expected verdicts for every candidate scheme. They are used to evaluate eligibility outcomes (L13). All personas and facts are fictional; no case contains an ID number.

| Split | Families | Cases | Verdicts |
| --- | --- | --- | --- |
| `development/` | 6 (F02, F04, F08, F10, F13, F18) | 21 | 39 (32 labelled, 7 copied to language versions) |
| `held_out/` | 16 | 50 | 95 (71 labelled, 24 copied to language versions) |

Languages: 58 English, 9 Marathi, 4 Hindi. A Hindi or Marathi case (`variant_of` set) copies its source case's profile and labels, so the same household must get the same verdicts in every language.

## What a case holds

- `opening_message`: the citizen's first message, for a simulated citizen.
- `hidden_profile`: the facts the simulated citizen knows, as rule-engine fields. It holds exactly the fields of the case's `candidate_scheme_ids`. `null` means the citizen doesn't know.
- `expected`: one verdict per candidate scheme, `eligible`, `not_eligible` or `cant_tell`. `review_item` links a verdict to the label review below.

## How it was built

1. **Rules.** The 15 rule files in `data/rules/` were drafted by Saurabh and verified rule by rule against the myScheme text by Sharika (7 Nov 2026). Seven interpretation decisions were recorded. C30 is a scheme for colleges, so it is not used here.
2. **Fields.** The persona field list was frozen at 47 fields on 7 Nov. `age_nearer_birthday` was added on 8 Nov for C02's "70 years (age nearer birthday)" limit.
3. **Cases.** Families were designed around rule boundaries (for example age 40 vs 41, income ₹15,000 vs ₹15,001), exclusions, multi-scheme households and unknown answers. Each case passed a field and consistency check (11 rules).
4. **Labels.** Sharika labelled every case from the scheme source sentences, without running the engine.
5. **Label review.** The 103 labels were compared once with the rule engine on 8 Nov, before any agent run. Three labels were corrected after rereading the source (R1 F05a, R2 F13c, R3 F19b). One rule was fixed (R4: C04 now requires auto-debit consent, found through F10b in the development split). Three ambiguous cases were rewritten and relabelled (R5 F12a, R6 F14d, R7 F16b). No label was copied from the engine.

## Known limits

- **One labeller.** The brief asks for two independent labellers. Only one labelled these cases because of time, so no inter-annotator agreement (Cohen's kappa) is reported. A second labelling of the held-out split would add it.
- **C17 wording.** "notified on or after April 1, 2018, including those who are already being treated" can also mean that patients on treatment on that date qualify even if notified earlier. The rule follows the first reading only, and F16b avoids the ambiguous zone.
- **Rule-based truth.** Labels follow the myScheme text captured on 28 Oct 2026, not current official policy.

## Using it

```bash
python tests/evaluation/check_eligibility_gold.py --split development
python -m pytest -q tests/test_eligibility_gold.py
```

To score a whole system against the gold set, run an experiment config:

```bash
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c0_fixed_workflow.json
```

Each config in `tests/evaluation/configs/` is one experiment. The runner writes `cases.jsonl` and `summary.json` to the git-ignored `data/evaluation-runs/`. The summary holds verdict accuracy, case success, can't-tell rate, a confusion table, per-scheme accuracy, Hindi/Marathi consistency, questions, tool calls, latency and errors. Only each case's candidate schemes are scored. The held-out split needs `--final`.

| Config | System | Development result (8 Nov) |
| --- | --- | --- |
| `c0_fixed_workflow` | C0, fixed workflow, no model, candidate schemes | 39/39 verdicts, 4.5 questions per case, 218 ms median |
| `c0_fixed_workflow_all_schemes` | C0 checking all 15 live schemes | 39/39 verdicts, 45.8 questions per case, 1.8 s median |

`c2_agent_team` runs the real supervisor and specialist agents against the simulated citizen in `tests/evaluation/simulated_citizen.py`: a model that knows only the case's hidden profile and answers only what it is asked, in the case's language. Set `SUPERVISOR_MODEL`, `SPECIALIST_MODEL`, `CITIZEN_MODEL` (a different model family, as the brief requires) and `OPENROUTER_API_KEY` in `.env`, then:

```bash
python tests/evaluation/run_eval.py --config tests/evaluation/configs/c2_agent_team.json --limit 3
```

For a conversation, a verdict counts only once the person was given the rule engine's answer on confirmed facts. Candidate schemes the system checked but never answered score `no_final_answer`; ones it never checked score `not_evaluated`. The summary separates these: `shortlist_recall` (candidates checked at all), `answered_rate` and `accuracy_when_answered`. `cases_with_unbacked_eligibility_claims` counts conversations where an agent told the person they qualify (or don't) without the rule engine. That is a keyword check, so an LLM judge should confirm the flagged cases. To score a saved run again under the current rules without calling a model, use `python tests/evaluation/run_eval.py --rescore data/evaluation-runs/<run>`.

On top of the C0 measures, C2 also records the team's shortlist, facts it confirmed wrongly against the hidden profile, tokens by model and the full transcript of each case. The single-agent system (C1) is listed in the runner but not built yet.

The pytest checks both splits for structure and consistency, but compares the rule engine with the gold labels only on `development`. Run `--split held_out` only in the final evaluation, and never tune rules, prompts or the playbook on held-out results. Agents and MCP servers must not read this folder.
