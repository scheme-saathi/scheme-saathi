# Rule review status

A rule file gives live verdicts only when every rule in it is `reviewed`, and `reviewed` means a person compared each rule with the scheme sentence it cites. Draft rules always give `cant_tell`. They can still be previewed with `--include-draft`, but never in citizen answers.

## Reviewed: 15 schemes, the gold standard for rule extraction

C01, C02, C04, C05, C06, C10, C13, C17, C19, C23, C30, C38, M13, M16, M18.

- Drafted by Saurabh and verified rule by rule against the myScheme text by Sharika on 7 Nov 2026. Seven interpretation decisions were recorded; D1 and D3 removed one rule each.
- Corrected on 8 Nov 2026 while labelling the persona gold set: C02's upper age uses age nearer birthday, and C04 requires auto-debit consent.

## Reviewed: 7 AI-drafted schemes, checked by a person (Step 4)

C03, C14, C29, M01, M02, M19, M20. Checked rule by rule against their source sentences by Sharika on 8 Nov 2026 (48 checks, decisions E1–E5).

- C03 and C14 were approved as drafted. C03 reuses M13's "anyone in the family" exclusion fields, which is slightly stricter than its own text; this is accepted and recorded (E5).
- M01 and M02: "BPL **or** family income ≤ ₹21,000" is now decided in code (`household_below_bpl` or `annual_family_income`), not packed into one yes/no question. M01's "below 65" limit applies to the destitute category only.
- C29: "disability more than 80% **or** dwarfism".
- M19: only one unmarried woman per family.
- M20: categories C, D and E added; the white-card rule cites category B.

The fixes use the rule engine's one level of OR (`or_conditions`, E1).

## Draft: 27 schemes, AI-drafted and not yet checked by a person

C07, C09, C11, C15, C16, C18, C21, C22, C24, C25, C26, C27, C28, C31, C32, C33, C36, M05, M06, M07, M08, M09, M10, M11, M12, M14, M21.

Added in PR #61 (8 Nov 2026), drafted by an AI from `data/schemes/`. That PR's notes file, `data/rules/REVIEW_NOTES.md`, is git-ignored and exists only on its author's machine. They were first marked `reviewed` without a check, then returned to `draft` on 8 Nov 2026, because the brief requires a person to review extracted rules before they go live.

To return a scheme to `reviewed`, check every rule against its cited sentence, as in Steps 1 and 4: the clause, field, operator and value, the `all`/`any` logic, any `or_conditions`, and the boundary cases. Then set its rules' status to `reviewed` and add it to `AI_DRAFTED_REVIEWED_IDS` in `tests/test_scheme_gold_set.py`.
