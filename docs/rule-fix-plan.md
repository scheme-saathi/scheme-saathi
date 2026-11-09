# Rule fix plan: all 49 schemes

**Scope.** I compared every rule file in `data/rules/` with its scheme record in `data/schemes/` (matched by `scheme_id`) on `develop` as of 9 Nov 2026. Every eligibility and exclusion sentence was checked for coverage, field, operator, value, boundaries, units, `rule_logic`, `or_conditions` and citations, using the semantics in `servers/rule_engine/rules.py`.

**Result.** Every scheme except M21 has at least one issue, and M21 has only one minor issue. **20 issues give wrong verdicts** (critical): 17 found by the reviewers, plus M13, M19 and C29, which I raised to critical because they reject or accept the wrong people in schemes that are live today. All 20 were confirmed directly in the files.

- **Critical:** the verdict is wrong. An eligible person is rejected, or an ineligible person is accepted.
- **Major:** a condition is missing, a question can't be answered or packs two conditions into one, or the scheme is for organisations but is treated as one for individuals.
- **Minor:** a wrong citation, clause text that doesn't match the record, inconsistent field naming, or wording.

**The rule that governs this whole plan:** a person must check a rule file before it goes live (`REVIEW_STATUS.md`). An AI fix to a **draft** file leaves it `draft`. An AI fix to a **reviewed** file sets the changed rules back to `draft` until a person signs them off.

---

## Phase 0: decisions a person must make first

Each of these changes what the fixes in this plan look like. Record each answer as a decision in `REVIEW_STATUS.md`, numbered F1, F2 and so on.

| # | Question | Schemes |
|---|---|---|
| F1 | Should schemes for organisations be left out of citizen verdicts? Proposal: add `"applicant_type": "institution" \| "individual" \| "mixed"` to each rule file and skip `institution` ones in intake and the shortlist. | C07, C09?, C10, C11, C21, C22, C30 |
| F2 | What values can `social_category` take? Proposal: `SC, ST, OBC, VJNT, VJ-A, NT-B, NT-C, NT-D, SBC, Nav-Buddha, EWS, EBC, General`. Is VJNT/SBC counted as OBC for central schemes? | M12, M14, M18, C11, C16, C24, C26 |
| F3 | Which income fields exist, and what does each mean? Proposal: `applicant_annual_income`, `annual_family_income` and `applicant_monthly_income`. Keep the scheme-specific fields in C31 and C38. | C05, C16, M08, M09, M10, M11, M12 |
| F4 | One shared field for bank accounts? Proposal: `has_bank_or_post_office_savings_account`. | C01, C02, C03, C04, C05 |
| F5 | Should "a family member already got this scheme" be a separate field per scheme? Proposal: yes, because one generic field shared across schemes leaks an answer from one scheme into another. | C10, M12, M14 |
| F6 | Should age relaxation always use the same pattern? Proposal: `age ≤ max+5` AND (`age ≤ max` OR in a relaxed category). | C24, C26, M14 |
| F7 | Which source conflicts need checking against the official guidelines? | see the list at the end |

---

## Phase 1: live (reviewed) schemes that give wrong verdicts today

These have the highest priority because citizens already get these answers.

| Scheme | Severity | Fix |
|---|---|---|
| **M01** Sanjay Gandhi Niradhar | critical | "Unmarried woman above 35" is never checked against age. Add `{niradhar_category ne "unmarried woman above 35", or: age gt 35, clause elig-14}`. |
| M01 | critical | The disease category is a closed list ("tb, cancer, aids or leprosy") but the source says "diseases **like**…". Change the value to "unable to sustain due to a serious disease (e.g. tb, cancer, aids, leprosy)" and update `tests/test_step4_reviewed_rules.py`. |
| M01 | major | "Orphan child" has no age check. Add `{niradhar_category ne "orphan child", or: age lt 18, clause elig-6}`. |
| M01 | major | Someone in two categories (for example a widow over 65) fails if they pick the "below 65" one. The ask prompt should list the most specific categories first and "destitute below 65" last. |
| M01 | minor | All 12 categories cite elig-4. Cite elig-5 to elig-16, and only after the engine change in Phase 3.3. |
| **M13** Namo Shetkari | critical | The exclusion fields read as "you" (`is_non_resident_indian`, `paid_income_tax_in_last_assessment_year`, …), but the source excludes the **whole family**. Rename them to `family_has_…` and update C03, which reuses them (decision E5). |
| M13 | major | The carve-out "(excluding MTS / Class IV / Group D)" is packed into one yes/no. Split it: `family_has_govt_or_local_body_employee eq false` OR `that_employee_is_mts_class_iv_or_group_d`. Do the same for the pension ≥ ₹10,000 rule. Apply both to C03. |
| M13 | major | Nothing checks that the farmer is in Maharashtra or a PM-KISAN beneficiary. Add `holds_farmland_in_maharashtra` and `is_pm_kisan_beneficiary`, citing details clauses. |
| **M19** Ladki Bahin | critical | `family_has_government_employee_or_government_pensioner` drops "regular/permanent", so families of contract workers are wrongly rejected. Rename to `family_has_regular_government_employee_or_pensioner`. |
| **C29** Disability Pension | critical | `has_disability eq true` rejects a person with dwarfism who answers "no". Add `or: is_person_with_dwarfism eq true` to that rule too. |
| **C30** HEPSN | major | This scheme is for colleges, not individuals. Apply F1 (`applicant_type: institution`). |
| **C02** PMSBY | major | `age_nearer_birthday lte 70` conflicts with "cover terminates on attaining age 70". Change it to `lt 70`, or record a decision to keep 70 inclusive. Ask for `age` once and work out the nearer-birthday age in code, instead of asking two age questions. |
| **C06** Widow Pension | major | `age lte 79` rejects widows aged 80+, but the benefits section pays them ₹500. Decide whether they move to IGNOAPS, and say so in the not-eligible answer, or drop the upper limit. |
| **C19** PM POSHAN | major | Bal Vatika (pre-school) children are rejected (`school_class gte 1`) although the benefits cover them. Add an or_condition, or record that the eligibility text wins. Add "local body" to `school_type`. |
| **C23** Nari Adalat | major | It runs as a pilot in a few Gram Panchayats only, but every woman gets "eligible". Add `state_of_residence in [Assam, J&K, Bihar, Karnataka, A&N]` from a details clause, and update gold cases F17a/F17b. |
| **C14** PMFBY | major | No rule says the farmer must cultivate the insured land (elig-4). Add `farmer_applicant_category in [cultivator values]`, reusing C13's field. Split "notified crop **and** notified area" into two questions. |
| **C03** PM Kisan Maandhan | major | The same packed government-employee carve-out as M13 (fix both together). Add `covered_by_other_statutory_social_security_scheme` for the "etc." in excl-1. |
| **C13** KCC | minor | `rule_logic: any` across three category rules means any condition added later becomes an alternative instead of a requirement. Merge them into one `in` rule and set `rule_logic: all`. |
| **M18** Motor Driving | major | `meets_motor_vehicle_act_age_education_and_fitness_conditions` can't be answered. Replace it with `age gte 18` plus `is_medically_fit_to_drive`. Add the VJ-A and NT-B/C/D values to `social_category` (F2). |
| **M20** MJPJAY | minor | `ration_card_type` has no PHH value, so PHH card holders without a domicile certificate are rejected. Add "phh" or map it to orange. Rename `…_mbocww_board` to match M16 (or the other way round). |
| **M16** | minor | Rename `registered_with_mbo_cww_board` to `registered_with_mbocww_board` (spelling). |
| C01, C04, C05, C17, C38, M02 | minor | Wording and naming only. See Phase 4. |

---

## Phase 2: draft schemes with critical faults

Fix these before anyone reviews them; otherwise a person would sign off a wrong rule.

| Scheme | Fault | Fix |
|---|---|---|
| **M08** Mahila Kisan | Income limit missing (elig-7/8) | Rule A: `annual_income lte 120000, or: household_below_bpl`. Rule B: `area_type ne "rural", or: [annual_income lte 98000, household_below_bpl]`. Add the `area_type` field (rural/urban). Add the 7/12 land-record rule (elig-6). |
| **M09** Mahila Samridhi | Income limit missing (elig-6/7) | Same as M08, but with `lt` ("below"). |
| **M12** Ramai Awas | No SC/Nav-Buddha check; one ₹2 lakh limit for every area | Add `social_category in [SC, Nav-Buddha]` (details clause). Add `residence_area_type` with limits of 1 lakh (rural), 1.5 lakh (municipal council) and 2 lakh (corporation), using or_conditions. Rename `family_member_already_beneficiary` (F5). |
| **M14** CMEGP | 5-year age relaxation ignored; class 7 required for every project | Age: F6 pattern with SC/ST, woman, ex-serviceman and disability. Education: `has_passed_class_7, or: project_cost lte 1000000` and `has_passed_class_10, or: project_cost lte 2500000`. Rename the generic fields (F5). |
| **C24** NPDF | No relaxation (SC/ST/OBC/PwD/women) | F6 pattern, limits 35/40. Split "PhD **or** thesis submitted" into two fields. |
| **C26** TARE | No relaxation, and residence missing | F6 pattern, limits 45/50. Add `resides_in_india`. |
| **C25** WIDUSHI | Categories A and B merged into the loosest combination | Add `widushi_employment_category`. Use `age gte 57, or: category B` and `publications gte 20, or: category B`. Rename the PhD field to "or equivalent". Fix the citations. |
| **C27** PM VIKAS | No minority-community check | Add `religion in [6 notified], or: is_ews` (details clause; the question must explain why it asks). Add `is_indian_citizen`. |
| **C15** PG Single Girl | Twin daughters rejected; deemed-university exclusion missing; age measured at the wrong time | Split into `has_brother eq false` + `is_only_girl_child, or: is_twin_daughter`. Add the excl-2 rule. Rename to `age_at_pg_admission`. |
| **C16** Ambedkar overseas loan | No OBC/EBC check | `social_category in [OBC], or: is_economically_backward_class` (details clause, F2). Check whether the income limit is the applicant's or the family's (F3). |
| **C31** Veteran Artists | Income should exclude the artist pension | Rename to `…_annual_income_excluding_artist_pension`. Split "pension ≥ ₹500 **or** ZCC recommendation" into a number field plus an OR. |
| **C07** Krishi Vigyan Puraskar | Age rule wrong for two of the award categories | Most likely F1 (an award for scientists, not a citizen scheme), so leave it out. Otherwise add `award_category` with or_conditions for each category. |
| **C09** PRISM | Patenting-only proposals accepted; three exclusions missing | Add `proposal_is_only_patenting_without_prototype`, `…only_software`, `…basic_research_without_commercial_use` (all eq false) and `project_duration_months lte 24`. |

## Phase 3: engine and intake changes that several schemes need

Each item is small, needs its own test, and must land before the scheme fixes that depend on it.

1. **`applicant_type`** (F1): an optional key in the rule file. `search_schemes` / `_candidate_schemes` skip `institution` schemes for citizen intake. Affects C07, C10 (mixed), C11 (mixed), C21, C22, C30.
2. **Shared field values for text fields**: put the `social_category`, `area_type` and `residence_area_type` value lists in one place, so every scheme uses the same spelling. The ask prompt already lists `known_values` as choices.
3. **Cite only the clause that matched in an OR rule.** Today the engine cites every evaluated or_condition, so M01 would cite all 12 categories. Change: for a passing OR rule, keep only the conditions that came out `true`.
4. **Income period conversion**: `income_period` recognises income fields by their names. Update it for the renamed fields from F3.
5. **Age at a date** (C02 age nearer birthday, C15 age at admission, C28 17.5 years): ask for age (or date of birth) once and work out these fields in code, instead of asking extra age questions.

## Phase 4: draft schemes with major or minor issues only

| Scheme | Main fixes |
|---|---|
| C10 Khadi | `applicant_type: mixed`; make the individual rules pass for institutions; clarify `is_khadi_registered` for artisans working under a registered institution; reuse `has_aadhaar` OR other ID. |
| C11 Stand-Up India | Replace `is_woman_or_from_sc_st` with `is_woman_or_girl, or: social_category in [SC, ST]`; add the rule for enterprises (51% stake). |
| C18 PMSMA | Add `resides_in_india`; split the trimester field into `is_pregnant` + `weeks_of_pregnancy gt 12 / lte 40`. |
| C21 AVYAY | Mostly an agency scheme (F1). Split `senior_care_need` into `is_indigent, or: has_dementia_or_needs_continuous_nursing_care`, citing elig-4/5. Confirm the senior-citizen age of 60. |
| C22 Nyaya Mitra | The rules cover litigants only. Use `years_case_pending gt 10` instead of the packed bool. Decide whether High Court cases count. |
| C28 Agnipath | Handle the 17.5-year minimum (Phase 3.5). Drop or split the armed-forces standards field. Confirm the upper age limit. |
| C32 Sports medal | Split the medal-or-participation OR. Replace the institution-type field with `institution_type in [...]` or leave it to the university to check. Fix the elig-2 citation. |
| C33 GST exemption | Rename to `has_permanent_orthopedic_disability`. |
| C36 AICTE-INAE | Use `engineering_course_and_year` (a list of choices) instead of a long OR. Use `previous_year_cgpa gte 7, or: previous_year_percentage gte 65`. Rename to "acceptance letter". |
| M05 | Add `is_enrolled_in_maharashtra_recognised_institution` (elig-3). Give "post-matric" plain wording in the question. |
| M06 | Split into `age lt 18`, `has_intellectual_disability` and `needs_care_and_protection`. Ask about "the child". |
| M07 | Split cobbler and Gram Panchayat identification into two fields. |
| M10 | Add an or_condition `monthly_income lt 1500` (elig-5) for correct citations. |
| M11 | Add `is_unemployed` (details); `applicant_annual_income` (F3). |
| M21 | Optionally drop `has_aadhaar`, which `has_aadhaar_linked_bank_account` already implies. |

**Cleanup across all files (minor):**
- Add `"rule_logic": "all"` explicitly where it is missing (C01, C02, C04, C05, C06, C10, C17, C19, C23, C30, C38).
- Fix the three clause texts that don't match the record word for word: C02 `exit-1`, C04 `elig-4`, C04 `doc-1`.
- Remove heading-only clauses (C07, M09, M12).
- Make income-tax questions word-for-word unambiguous (C04, C05, M19).

## Process for each scheme

1. **Edit** the rule file. Draft files stay `draft`; on reviewed files, the changed rules go back to `draft`.
2. **Test.** Add boundary cases to `tests/test_step4_reviewed_rules.py` (or a new `test_rule_fixes.py`): the person who should pass, the person who should fail, and a missing fact giving `cant_tell`. Run only these tests plus `tests/test_scheme_gold_set.py`.
3. **Sign-off.** A person checks each rule against its cited sentence. Then set it to `reviewed`, add it to `AI_DRAFTED_REVIEWED_IDS`, and record the decision in `REVIEW_STATUS.md`.
4. **Pull requests.** One PR per phase. Phase 1 should go first, and on its own, because it changes live answers.

## Facts to check against the official guidelines (myScheme alone is not enough)

| Scheme | Question |
|---|---|
| C16 | Is the ₹8 lakh limit on the applicant's income or the family's? |
| C38 | Is the ₹10 lakh limit on combined income or on each person's own income? Actual PAHAL policy is believed to be per person. |
| C28 | Is the upper age 21, 21½ or 22? |
| C36 | Does "any 4-year engineering degree" include 1st- and 2nd-year B.Tech students? |
| C21 | Is a senior citizen 60+? |
| C22 | Do High Court cases count? |
| C14 | Can oral sharecroppers join? |
| M14 | Does "special category" include VJNT, OBC and minorities? |
| C15 | Can a girl with sisters but no brothers apply? |
| C32 | Do national-level medals beyond the National Games count? |
| C06 | Do widows aged 80+ move to IGNOAPS? |
| C02 | Is age 70 inclusive or exclusive? |

The rules can only be as correct as the scheme records they're checked against, so these answers need the official scheme PDFs, not myScheme.
