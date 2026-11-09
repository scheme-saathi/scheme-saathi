# Rule review status

A rule file gives live verdicts only when every rule in it is `reviewed`, and `reviewed` means a person compared each rule with the scheme sentence it cites. Draft rules always give `cant_tell`. They can still be previewed with `--include-draft`, but never in citizen answers.

## Reviewed: 15 schemes, the gold standard for rule extraction

C01, C02, C04, C05, C06, C10, C17, C19, C30, C38 are live. C13, C23, M13, M16 and M18 are waiting for re-review (see below).

- Drafted by Saurabh and verified rule by rule against the myScheme text by Sharika on 7 Nov 2026. Seven interpretation decisions were recorded; D1 and D3 removed one rule each.
- Corrected on 8 Nov 2026 while labelling the persona gold set: C02's upper age uses age nearer birthday, and C04 requires auto-debit consent.

## Reviewed: 7 AI-drafted schemes, checked by a person (Step 4)

M02 is live. C03, C14, C29, M01, M19 and M20 are waiting for re-review (see below). These were checked rule by rule against their source sentences by Sharika on 8 Nov 2026 (48 checks, decisions E1–E5).

- C03 and C14 were approved as drafted. C03 reuses M13's "anyone in the family" exclusion fields, which is slightly stricter than its own text; this is accepted and recorded (E5).
- M01 and M02: "BPL **or** family income ≤ ₹21,000" is now decided in code (`household_below_bpl` or `annual_family_income`), not packed into one yes/no question. M01's "below 65" limit applies to the destitute category only.
- C29: "disability more than 80% **or** dwarfism".
- M19: only one unmarried woman per family.
- M20: categories C, D and E added; the white-card rule cites category B.

The fixes use the rule engine's one level of OR (`or_conditions`, E1).

## Waiting for re-review: 11 schemes changed by an AI (Phase 1 of `docs/rule-fix-plan.md`, 9 Nov 2026)

C03, C13, C14, C23, C29, M01, M13, M16, M18, M19, M20. Each changed or added rule is `draft`, so these schemes give `cant_tell` until a person checks the draft rules against their cited sentences and sets them back to `reviewed`. Unchanged rules stay `reviewed`.

- **M01:** the disease category reads "a serious disease (e.g. tb, cancer, aids, leprosy)", because the source says "diseases like". Orphan child needs age below 18 (elig-6). Unmarried woman needs age above 35 (elig-14). The category list now puts the most specific categories first and "destitute below 65" last, so the question lists them in that order.
- **M13 and C03:** the exclusions are about anyone in the family, so the fields are now named `family_has_…`. "Excluding MTS / Class IV / Group D" is now its own question, both for employees and for pensioners on ₹10,000 or more (pensioners in M13 only). M13 adds `is_pm_kisan_beneficiary` (details-3). C03 adds `covered_by_other_statutory_social_security_scheme` for the "etc." in excl-1.
- **M19:** only *regular/permanent* government employees and pensioners exclude the family (`family_has_regular_government_employee_or_pensioner`).
- **C29:** a person with dwarfism also passes the "has a disability" rule (elig-6).
- **C23:** limited to the pilot states and UTs: Assam, Jammu and Kashmir, Bihar, Karnataka, Andaman and Nicobar Islands (details-1).
- **C14:** the farmer must cultivate the insured land (`farmer_applicant_category`, elig-4). "Notified crop" and "notified area" are two questions.
- **C13:** the three categories are one rule with alternatives, and `rule_logic` is `all`.
- **M18:** "meets the Motor Vehicle Act conditions" is now `age ≥ 18` and `is_medically_fit_to_drive`.
- **M20:** PHH ration cards count as category A.
- **M16:** the board field is spelled `registered_with_mbocww_board`, as in M20.

The reviewer should check two interpretations in particular. Is the M13 requirement "a PM-KISAN beneficiary" or only "eligible for PM-KISAN"? Should PHH count as M20 category A?

**Gold set.** Profiles were updated for the renamed and split fields. These labels need a person to look at them again, because the new rules need facts the cases don't state: M13 in F13a, F13d and F14c (`is_pm_kisan_beneficiary`); C23 in F17a, F17b, F17e, F18a–d and F20a (`state_of_residence`); C23 in F01a–c (the mother lives in Pune, so she is outside the pilot states). `test_c0_fixed_workflow_matches_gold_on_development` is marked as an expected failure until then.

**Not done in Phase 1, waiting on a decision:** C30 (F1), C02 age 70 and age nearer birthday (F7, Phase 3.5), C06 widows aged 80+, C19 Bal Vatika and the "local body" school type, M18's VJ-A and NT-B/C/D values (F2), M01 citations per category (Phase 3.3), and the Maharashtra-farmland rule for M13 (no source sentence says it).

## Draft: 27 schemes, AI-drafted and not yet checked by a person

C07, C09, C11, C15, C16, C18, C21, C22, C24, C25, C26, C27, C28, C31, C32, C33, C36, M05, M06, M07, M08, M09, M10, M11, M12, M14, M21.

Added in PR #61 (8 Nov 2026), drafted by an AI from `data/schemes/`. That PR's notes file, `data/rules/REVIEW_NOTES.md`, is git-ignored and exists only on its author's machine. They were first marked `reviewed` without a check, then returned to `draft` on 8 Nov 2026, because the brief requires a person to review extracted rules before they go live.

To return a scheme to `reviewed`, check every rule against its cited sentence, as in Steps 1 and 4: the clause, field, operator and value, the `all`/`any` logic, any `or_conditions`, and the boundary cases. Then set its rules' status to `reviewed` and add it to `AI_DRAFTED_REVIEWED_IDS` in `tests/test_scheme_gold_set.py`.
