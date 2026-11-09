# Rule review status

A rule file gives live verdicts only when every rule in it is `reviewed`, and `reviewed` means a person compared each rule with the scheme sentence it cites. Draft rules always give `cant_tell`. They can still be previewed with `--include-draft`, but never in citizen answers.

## Reviewed: 15 schemes, the gold standard for rule extraction

C01, C04, C05, C06, C10, C17, C30, C38 are live (C30 for organisations only, F1). C02, C13, C19, C23, M13, M16 and M18 are waiting for re-review (see below).

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

## Waiting for re-review: 13 schemes changed by an AI (Phase 1 of `docs/rule-fix-plan.md`, 9 Nov 2026)

C02, C03, C13, C14, C19, C23, C29, M01, M13, M16, M18, M19, M20. Each changed or added rule is `draft`, so these schemes give `cant_tell` until a person checks the draft rules against their cited sentences and sets them back to `reviewed`. Unchanged rules stay `reviewed`.

- **M01:** the disease category reads "a serious disease (e.g. tb, cancer, aids, leprosy)", because the source says "diseases like". Orphan child needs age below 18 (elig-6). Unmarried woman needs age above 35 (elig-14). The category list now puts the most specific categories first and "destitute below 65" last, so the question lists them in that order.
- **M13 and C03:** the exclusions are about anyone in the family, so the fields are now named `family_has_…`. "Excluding MTS / Class IV / Group D" is now its own question, both for employees and for pensioners on ₹10,000 or more (pensioners in M13 only). M13 adds `is_pm_kisan_beneficiary` (details-3). C03 adds `covered_by_other_statutory_social_security_scheme` for the "etc." in excl-1.
- **M19:** only *regular/permanent* government employees and pensioners exclude the family (`family_has_regular_government_employee_or_pensioner`).
- **C29:** a person with dwarfism also passes the "has a disability" rule (elig-6).
- **C23:** limited to the pilot states and UTs: Assam, Jammu and Kashmir, Bihar, Karnataka, Andaman and Nicobar Islands (details-1).
- **C14:** the farmer must cultivate the insured land (`farmer_applicant_category`, elig-4). "Notified crop" and "notified area" are two questions.
- **C13:** the three categories are one rule with alternatives, and `rule_logic` is `all`.
- **M18:** "meets the Motor Vehicle Act conditions" is now `age ≥ 18` and `is_medically_fit_to_drive`. Its categories follow F2: "VJNT" is now VJ-A, NT-B, NT-C and NT-D (gold case F19c uses VJ-A for "VJNT").
- **M20:** PHH ration cards count as category A.
- **M01 citations** (Phase 1 leftover): each category cites its own clause (elig-5 to elig-16) instead of elig-4. The age checks for orphans, unmarried women and the destitute below 65 cite elig-4 when they don't apply.
- **C19** (Phase 1 leftover, decided 9 Nov 2026): Bal Vatika (pre-school) children in primary schools pass the class rules (`is_in_bal_vatika_or_pre_school_class`, benefits-7), because the benefits text names them. The government or aided school rule still applies. "Local body" schools are not covered (checked against the official sources, see F7 answers).
- **C02** (F7 answer): age 70 is not included, so `age_nearer_birthday < 70`. The age nearer birthday is worked out from the date of birth (Phase 3).
- **M13** (Phase 1 leftover, decided 9 Nov 2026): `holds_farmland_in_maharashtra` is required. It cites the Government Resolution sentence (details-2), which names the state resolution but does not state the condition itself.
- **M16:** the board field is spelled `registered_with_mbocww_board`, as in M20.

The reviewer should check two interpretations in particular. Is the M13 requirement "a PM-KISAN beneficiary" or only "eligible for PM-KISAN"? Should PHH count as M20 category A?

**Gold set.** Profiles were updated for the renamed and split fields. These labels need a person to look at them again, because the new rules need facts the cases don't state: M13 in F13a, F13d and F14c (`is_pm_kisan_beneficiary`, and for F14c also `holds_farmland_in_maharashtra`); C23 in F17a, F17b, F17e, F18a–d and F20a (`state_of_residence`); C23 in F01a–c (the mother lives in Pune, so she is outside the pilot states); C02 in F09c (age nearer birthday 70, labelled eligible, but 70 is not included). `test_c0_fixed_workflow_matches_gold_on_development` is marked as an expected failure until then.

**Not done in Phase 1, waiting on the official guidelines (F7):** C06 widows aged 80+. C30 is handled by F1.

## Draft: 27 schemes, AI-drafted and not yet checked by a person

C07, C09, C11, C15, C16, C18, C21, C22, C24, C25, C26, C27, C28, C31, C32, C33, C36, M05, M06, M07, M08, M09, M10, M11, M12, M14, M21.

Added in PR #61 (8 Nov 2026), drafted by an AI from `data/schemes/`. That PR's notes file, `data/rules/REVIEW_NOTES.md`, is git-ignored and exists only on its author's machine. They were first marked `reviewed` without a check, then returned to `draft` on 8 Nov 2026, because the brief requires a person to review extracted rules before they go live.

To return a scheme to `reviewed`, check every rule against its cited sentence, as in Steps 1 and 4: the clause, field, operator and value, the `all`/`any` logic, any `or_conditions`, and the boundary cases. Then set its rules' status to `reviewed` and add it to `AI_DRAFTED_REVIEWED_IDS` in `tests/test_scheme_gold_set.py`.

## Decisions for the rule fixes (F1–F7, Phase 0 of `docs/rule-fix-plan.md`, 9 Nov 2026)

Decided by Snehal Patel. They set the rules for Phases 1–4; they are not reviews of any rule.

- **F1. Schemes for organisations.** Each rule file gets `"applicant_type": "individual" | "institution" | "mixed"` (default `individual`). Intake and the shortlist skip `institution` schemes (C07, C21, C22, C30); an operator can still check one by id. `mixed` schemes (C10, C11) stay in citizen intake; making their rules fit individuals is Phase 4. C09 stays `individual`.
- **F2. `social_category` values.** `SC, ST, OBC, VJ-A, NT-B, NT-C, NT-D, SBC, Nav-Buddha, EWS, EBC, General`. A scheme text that says "VJNT" means VJ-A, NT-B, NT-C and NT-D. VJNT and SBC count as OBC in a central scheme only when that scheme's text says so.
- **F3. Income.** One income field, `annual_family_income`. Monthly limits are converted to yearly ones (×12), and `annual_income`, `monthly_income` and `applicant_monthly_income` are retired. C31's and C38's scheme-specific fields stay, because their limits are on the applicant and spouse, not the family. Known cost: where a scheme limits the applicant's own income (C05, M10, M11, possibly C16), using the family's income is stricter than the text. Every such rule must name this in its review.
- **F4. Bank account.** C01–C05 share one field, `has_bank_or_post_office_savings_account`. `has_aadhaar_linked_bank_account` (M19, M21) stays separate, because Aadhaar linking is a real extra condition.
- **F5. "A family member already got this scheme."** Each scheme gets its own field (for example `family_member_already_got_ramai_awas`), so an answer about one scheme never decides another. This replaces `family_member_already_beneficiary` in C10, M12 and M14.
- **F6. Age relaxation.** Always two rules: `age ≤ max + 5`, and `age ≤ max` OR the person is in a relaxed group. No engine change. Affects C24, C26, M14.
- **F7. Source conflicts.** None of the 12 open questions in the plan's last table is fixed from myScheme alone. The rule fix that depends on each one waits until a person has read the official guideline and recorded the answer here.

### F7 answers (checked against the official sources by Snehal Patel, 9 Nov 2026)

- **C02:** the upper age of 70 (age nearer birthday) is exclusive.
- **C16:** the ₹8 lakh limit is on total family income, so the rule uses `annual_family_income`. The applicant is a student with no income of their own, so elig-4's "total income of the applicant" means the family's income. The income-criteria amendment (https://socialjustice.gov.in/writereaddata/UploadFile/RICfor%20ISSC.pdf) can be added to the record as a second source.
- **C19:** local body schools are not covered. Bal Vatika is covered.
- **C15:** the scholarship is for a single-child family with a girl. Two daughters, twins included, cannot apply, so record elig-3 ("girls without brothers or twin daughters may also apply") is not followed. The limit is 30 or under at PG admission.
- **M14:** the special category for the age relaxation is SC, ST, women, ex-servicemen, differently abled, VJNT, OBC and minorities, as benefits-11 lists it. Minorities are the six central ones (Muslim, Christian, Sikh, Buddhist, Jain, Parsi), not the state list with Jews (decided 9 Nov 2026).

## Draft schemes fixed before review (Phase 2 of `docs/rule-fix-plan.md`, 9 Nov 2026)

These were already draft and stay draft. The reviewer checks them as for any AI-drafted scheme.

- **M08, M09:** income limits added. BPL households pass. Otherwise family income (F3) must be within ₹1,20,000, or ₹98,000 in a rural area (`area_type`, shared values). M08 says "up to" and M09 says "below". M08 also needs the 7/12 land extract, but only for agricultural project loans (elig-6).
- **M12:** SC or Nav-Buddha only (details-1). Family income limits by area: ₹1 lakh rural, ₹1.5 lakh municipal council, ₹2 lakh municipal corporation (`residence_area_type`). ₹2 lakh caps every area. Its own "already got this scheme" field (F5).
- **C24, C26:** age limits 35/40 and 45/50 with the F6 pattern for SC/ST/OBC, persons with disability and women. Under F2, OBC means OBC only. C24 asks "PhD/MD/MS" and "thesis submitted" as two questions. C26 needs residence in India.
- **C25:** category A (permanent government scientist, retired or retiring within a year) needs age 57–62 and 20 publications. Category B (temporary researcher) needs age 45–62 and 10 publications. The PhD question says "or equivalent".
- **C27:** Indian nationals from the six notified minorities, or EWS candidates (details-16 and details-20). It asks about religion, so the reviewer should check that the question says why it asks.
- **C31:** the income limit leaves out the artist pension. "Pension of at least ₹500 a month" and "recommended by a Zonal Cultural Centre" are two questions.
- **C09:** project duration of 24 months at most, and the three exclusions (only software, only patenting without a prototype, basic research without commercial use).
- **C16:** OBC or EBC students (details-5).
- **C15:** only a single-child family with a girl (`is_only_child`, see F7 answers). Deemed universities without government funds are excluded. The age is the age at PG admission, 30 or under, asked directly.
- **M14:** age 18–45, or up to 50 for the groups elig-1 names (SC/ST, women, ex-servicemen, differently abled). Class 7 is needed above a ₹10 lakh project and class 10 above ₹25 lakh. The fields are CMEGP-specific (F5), including the project cost. The relaxation also covers VJNT (VJ-A, NT-B/C/D), OBC and the six central minorities (benefits-11, see F7 answers).

## Smaller fixes (Phase 4 of `docs/rule-fix-plan.md`, 9 Nov 2026)

C01, C04, C05 and C10 are left untouched so they stay live. Their F3, F4 and F5 renames and C04's clause-text fixes wait until they are next reviewed. The other changed schemes were draft or already waiting for re-review.

- **C11:** a woman, or a man from SC/ST, as two questions. The rule for enterprises (51% stake) is not added, because no sentence in the record states it.
- **C18:** pregnant, more than 12 weeks and at most 40 weeks; residence in India.
- **C21:** indigent, or dementia / continuous nursing care, as two questions. The senior-citizen age of 60 waits for F7.
- **C22:** years the case has been pending (more than 10). Whether High Court cases count waits for F7.
- **C28:** the 17.5-year minimum is 210 months, worked out from the date of birth. The armed-forces standards are two questions: education, and physical and medical. The upper age waits for F7.
- **C32:** medal winner or international participant as two questions. The kind of institution is a choice, and each kind cites its own clause. National-level medals beyond the National Games wait for F7.
- **C33:** the orthopedic disability must be permanent.
- **C36:** course and year as a list of choices. CGPA of at least 7, or 65% or more. "Letter of acceptance". Whether 1st- and 2nd-year B.Tech students count waits for F7.
- **M05:** enrolled in a Maharashtra-recognised institution (elig-3). The post-matric question says "class 11, 12 or a technical or professional degree".
- **M06:** a child (under 18), with an intellectual disability, needing care and protection, as three questions.
- **M07:** roadside cobbler, and identified by the Gram Panchayat, as two questions.
- **M10:** family income (F3): below ₹18,000 a year for 100% assistance (elig-5), up to ₹24,000 for 50% (elig-6).
- **M11:** unemployed (details-1); family income below ₹1 lakh (F3).
- **M21:** `has_aadhaar` dropped, because an Aadhaar-linked bank account implies it.
- **C02, C03 (F4):** `has_bank_or_post_office_savings_account`; C03 also accepts a PM-KISAN account. Gold profiles for C02 use the new field.
- **Cleanup:**
  - `rule_logic` is explicit in C02, C06, C17, C19, C30, C38, M13 and M16. This is metadata only, so live schemes stay live.
  - C02's exit clauses quote the record word for word.
  - Heading-only clauses are removed from C07, M09 and M12.
- **Memory policy:** `annual_income` is removed, since no rule uses it now. The temporary-only list names `has_permanent_orthopedic_disability` and `has_intellectual_disability`.

## Engine and intake changes (Phase 3 of `docs/rule-fix-plan.md`, 9 Nov 2026)

- **`applicant_type`** (F1) is an optional key of a rule file, `individual` by default.
- **Shared values** (F2): `data/field_values.json` holds the one spelling of `social_category`, `area_type` and `residence_area_type`. A rule file that uses another value fails to load, and intake offers the whole list as choices.
- **Citations:** a rule that passes through one alternative cites only that alternative's clause. A failing or undecided rule still cites every clause it tried.
- **Income period:** only number fields are asked "per month" or "per year". Yes/no tax questions no longer are. Under F3 the name-based period still covers every income field.
- **Ages from the date of birth:** `age_nearer_birthday` and `age_in_months` (for a 17.5-year minimum) are worked out from `date_of_birth` (YYYY-MM-DD), as is `age` when it isn't stated. Intake asks for the date of birth instead of those fields, and asks the field itself only if the person can't give the date. C15's "age at admission" needs the admission date and is left to its Phase 2 fix.
