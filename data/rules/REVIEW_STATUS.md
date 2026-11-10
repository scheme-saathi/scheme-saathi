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

## Step 6: Snehal Patel's findings added (9 Nov 2026), signed off by Sharika

Sharika kept the Step 5 rules and added what Snehal found on `fix/rule-phase` (his checks against the official sources, F7, and the rule changes in his `docs/gold-relabel-review.md`). Sharika checked each change against its source and signed them off on 9 Nov 2026, except C02 (below).

- **Missed in Step 5:** C27 also accepts EWS candidates (det-2, details-20). M11 needs an unemployed applicant (det-1). C33's orthopedic disability is permanent (elig-1).
- **Official sources (F7):** C15 single-child family only, twins excluded, age at PG admission ≤ 30 (replaces Step 5 F2). C16 family income. C19 Bal Vatika / pre-school children are covered (ben-7); local body schools are not. M14's relaxation also covers VJNT (VJ-A, NT-B, NT-C, NT-D), OBC and the six minorities (ben-11).
- **Gold rules:** C23 only in Assam, Jammu and Kashmir, Bihar, Karnataka and Andaman and Nicobar Islands (det-1). M13 needs a PM-KISAN beneficiary (det-3) holding farmland in Maharashtra (det-2, a team decision); its exclusions are about anyone in the family, and the MTS / Class IV / Group D exception is its own question. M18: "VJNT" is VJ-A, NT-B, NT-C and NT-D, and the Motor Vehicle Act condition is age ≥ 18 and medically fit.
- **Reverted at sign-off:** C02 keeps age nearer birthday ≤ 70. Snehal's answer that 70 is not included was not adopted, so gold case F09c (70 years 2 months, age nearer birthday 70) stays eligible.
- **Gold labels (Step 6 relabel):** C23 F01a–c become not eligible (Pune is outside the pilot); F17a, F17b, F17e, F18a–d and F20a become can't tell (no state given). M13 profiles F13a, F13d and F14c say PM-KISAN beneficiary: yes, and F14c holds farmland in Maharashtra: yes, so their labels stay eligible. F18b and F18c no longer say the person is a woman. The labels came from Sharika's reading of the source; the engine agrees on every verdict afterwards.
- **Not added:** M08's land extract (Step 5 F3); C21, C22 and C28 questions his branch leaves open; renames across schemes (one income field, bank field, per-scheme "already got it" fields); skipping organisation schemes in intake; C03's family renames (its text is about the person, Step 4 E5).

## PR #67 review (Saurabh, 9 Nov 2026)

Two conditions were added because a verdict of "eligible" overstated what the rules checked; both give "can't tell" until the person answers:

- **M08 (elig-6):** the 7/12 land extract (own, joint with husband, or husband's name) is needed for agricultural project loans only: not an agricultural loan, OR has the extract. This replaces Step 5 decision F3.
- **C24 (elig-5, elig-6) and C26 (elig-5, elig-6):** the mentor's conditions. C24: a mentor with a regular position and a PhD in science or engineering, who has at most one NPDF fellow now (a mentor may not have more than two). C26: a mentor at Associate Professor / Scientist E level or higher, with no other TARE candidate.
- **M08 and M09:** the NSFDC limit is "rural" or "urban" in the source, so the urban limit now asks `lives_in_urban_area` instead of matching two municipality names; an answer of "urban" was refused before. M12 keeps its three area types, which its source names.

## Engine and intake support (from `fix/rule-phase`, 9 Nov 2026)

These change how rules are read and asked, not any rule's meaning.

- **`applicant_type`:** an optional rule-file key (`individual` by default). The citizen scheme list leaves out `institution` schemes (C07, C21, C22, C30), which can still be checked by id. C10 and C11 are `mixed` and stay.
- **Shared values:** `data/field_values.json` holds the one spelling of `social_category` and `area_type`. A rule file that uses another value fails to load, and intake offers the whole list as choices.
- **Citations:** a rule that passes cites one reason, the first condition that held. A failing or undecided rule cites every condition it tried.
- **Ages from the date of birth:** `age`, `age_nearer_birthday` and `age_in_months` are worked out from `date_of_birth` (YYYY-MM-DD; shown and typed as DD/MM/YYYY). Intake asks for the date of birth instead of an age that needs more than whole years, and asks the age field itself only if the person can't give the date. C28 can use `age_in_months` for its 17.5-year minimum (F5 on this file).
- **Income-tax questions:** the four income-tax fields carry their exact meaning to the question writer ("ever paid", "pays now", "anyone in the family", "last assessment year"). An answer that follows from another is filled in: never paid income tax means not paying it now, and paying now means having paid.

## Adding a new AI-drafted rule set

Keep its rules `draft` and list it in `AI_DRAFTED_IDS` in `tests/test_scheme_gold_set.py`. To make it live, check every rule against its cited sentence, as in Steps 1, 4 and 5: the clause, field, operator and value, the `all`/`any` logic, any `or_conditions`, and the boundary cases. Then set its rules' status to `reviewed` and move it to `AI_DRAFTED_REVIEWED_IDS`.
