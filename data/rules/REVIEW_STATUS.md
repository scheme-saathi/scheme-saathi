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

## Reviewed: 27 AI-drafted schemes, checked by a person (Step 5)

C07, C09, C11, C15, C16, C18, C21, C22, C24, C25, C26, C27, C28, C31, C32, C33, C36, M05, M06, M07, M08, M09, M10, M11, M12, M14, M21.

Added in PR #61 (8 Nov 2026), drafted by an AI from `data/schemes/`; kept as draft from 8 Nov until this review. Checked against their source sentences by Sharika on 9 Nov 2026. A script first confirmed that every rule cites the right clause and every clause matches the source word for word. Twelve were approved as drafted (C18, C21, C22, C28, C32, C33, C36, M06, M07, M10, M11, M21). Fifteen were fixed:

- **A condition was missing** (someone failing it was told "eligible"): C07 proven impact; C09 duration, software-only, basic research and patenting-only; C15 unfunded deemed universities; M05 recognised institution; C25 the two categories (age 57+ and 20 publications unless temporary); M08 and M09 BPL or the NSFDC rural/urban income limit; M12 the rural, municipal-council and corporation income limits.
- **A condition was too strict** (an eligible person was told "not eligible"): C24 and C26 the 5-year age relaxation for SC/ST/OBC, women and persons with disability; M14 the relaxation (SC/ST, women, ex-servicemen, disability) and schooling only for projects over ₹10 lakh (class 7) and ₹25 lakh (class 10).
- **An OR was packed into one question**, now decided in code: C11 woman or SC/ST; C31 state artist pension ≥ ₹500 a month or a Zonal Cultural Centre recommendation.

Decisions:

- **F1.** A rule may cite the scheme's Details text when the eligibility list leaves out who the scheme is for. Clause `det-1` holds that sentence word for word: C16 (OBC or EBC), C27 (six notified minorities), M12 (SC or Nav-Buddha).
- **F2.** C15 follows the strict reading of "only girl child": no sisters except a twin, and no brothers.
- **F3.** M08's 7/12 land extract applies only "for agricultural project loans", so it is not a rule; it stays on the documents list.
- **F4.** C21's "Senior Citizen" means 60 or older (the national definition).
- **F5.** C28's minimum is 17.5 years, but people give whole years, so someone aged 17 years 8 months is told "not eligible". Accepted as a known limit.
- **F6.** C11 and M14 are closed on myScheme. Their rules are live, and the eligibility answer adds "Applications for this scheme are closed on myScheme right now."

`religion` (C27) is never stored in memory, like `social_category`.

## Adding a new AI-drafted rule set

Keep its rules `draft` and list it in `AI_DRAFTED_IDS` in `tests/test_scheme_gold_set.py`. To make it live, check every rule against its cited sentence, as in Steps 1, 4 and 5: the clause, field, operator and value, the `all`/`any` logic, any `or_conditions`, and the boundary cases. Then set its rules' status to `reviewed` and move it to `AI_DRAFTED_REVIEWED_IDS`.
