# Gold set review after the rule fixes

**For:** the person who labelled `tests/evaluation/eligibility_gold_v1`
**Branch:** `fix/rule-phase` (rule-fix plan Phases 0–4, 9 Nov 2026)
**Asked by:** Snehal Patel

The rule fixes added conditions that some gold cases don't answer, and one source fact was checked against the official rules. As a result, 15 gold verdicts in 15 cases no longer agree with the corrected rules. **No verdict has been changed.** Please decide each one.

How to decide:

- Label from the scheme's source sentence and the case, as before. Don't copy the engine's answer: a disagreement is either a labelling question or a rule bug.
- For each case, either:
  - **add the missing fact** to `hidden_profile`, if the persona clearly implies it (then the label may stay), or
  - **change the verdict** (`eligible`, `not_eligible` or `cant_tell`).
- Record your decision in the last column, then edit `tests/evaluation/eligibility_gold_v1/<split>/cases.jsonl`.

The held-out split is for final evaluation only. Changing it here is allowed because the rules changed, not to match a run.

---

## 1. Verdicts to review (15)

### M13 Namo Shetkari Mahasanman Nidhi: 3 cases

New rules:
- The farmer must be a **PM-KISAN beneficiary** (`is_pm_kisan_beneficiary`). Source, details-3: *"Farmers which are eligible for PM Kisan Yojana will be eligible for the benefit of Namo Shetkari Mahasanman Nidhi Yojana"*.
- The farmer must **hold farmland in Maharashtra** (`holds_farmland_in_maharashtra`). This was decided by the team; it cites the Government Resolution sentence (details-2).

| Case | Split | Message | Label now | Draft rules say | Missing fact | Your decision |
|---|---|---|---|---|---|---|
| F13a | development | "I farm 2 acres of my own land in Nashik, owned since 2010. Can I get a Kisan Credit Card or farmer support?" | eligible | can't tell | PM-KISAN beneficiary | |
| F13d | development | Marathi version of F13a | eligible | can't tell | PM-KISAN beneficiary | |
| F14c | held_out | "We have owned our farm since 2005. My father retired as a Group D peon and gets a pension of 12,000 a month. Can we get Namo Shetkari?" | eligible | can't tell | PM-KISAN beneficiary; farmland in Maharashtra | |

### C23 Nari Adalat: 11 cases

New rule: it runs as a pilot only in **Assam, Jammu and Kashmir, Bihar, Karnataka and Andaman and Nicobar Islands** (`state_of_residence`). Source, details-1: *"The scheme is being run in 50 Gram Panchayat each in the state of Assam and UT of Jammu and Kashmir. Further it is being expanded in the 10 Gram Panchayats of Bihar and Karnataka and 5 Gram Panchayats of Andaman and Nicobar Islands."*

C23 is a second scheme in most of these cases; the person asked about something else.

| Case | Split | Message | Label now | Draft rules say | Missing fact | Your decision |
|---|---|---|---|---|---|---|
| F01a | held_out | "My mother is 62, a widow, lives in Pune district and has a BPL card. What can she get? Help me apply." | eligible | **not eligible** (Pune is outside the pilot) | none | |
| F01b | held_out | Hindi version of F01a | eligible | **not eligible** | none | |
| F01c | held_out | Marathi version of F01a | eligible | **not eligible** | none | |
| F17a | held_out | "My daughter is in class 8 at the government school. Does she get the free school meal?" | eligible | can't tell | state | |
| F17b | held_out | "My daughter moved to class 9 at the government school. Does she still get the free school meal?" | eligible | can't tell | state | |
| F17e | held_out | Marathi: daughter in class 8 at a government school | eligible | can't tell | state | |
| F18a | development | "I use an LPG cylinder at home. Last year my husband's and my taxable income together was exactly 10 lakh rupees…" | eligible | can't tell | state | |
| F18b | development | "We use LPG at home. Our combined taxable income last year was 10,00,001 rupees…" | eligible | can't tell | state | |
| F18c | development | "We cook on a wood stove and don't have an LPG connection…" | eligible | can't tell | state | |
| F18d | development | Marathi version of F18a | eligible | can't tell | state | |
| F20a | held_out | "I am a woman having a dispute with my in-laws. Can I go to the Nari Adalat?" | eligible | can't tell | state | |

### C02 Pradhan Mantri Suraksha Bima Yojana: 1 case

Checked against the official rules: the upper age of **70 (age nearer birthday) is not included**, so the rule is age nearer birthday below 70. The record also says *"The accident cover of the member shall terminate … On attaining age 70 years (age nearer birth day)"* (exit-1, exit-2).

| Case | Split | Message | Label now | Draft rules say | Missing fact | Your decision |
|---|---|---|---|---|---|---|
| F09c | held_out | "My father is 70 years and 2 months old and has a savings account. Can he get accident insurance?" | eligible | **not eligible** (age nearer birthday is 70) | none | |

---

## 2. Profile values filled in during the rule fixes: please check

When rule fields were renamed, split or added, these values were filled into `hidden_profile`. They're mechanical or read from the message, but they're your labels' inputs, so please confirm them.

| Cases | Change | Value used | Why | OK? |
|---|---|---|---|---|
| All M13 cases | The exclusions are now about anyone in the family (`family_has_…`). | same yes/no as before | renamed only | |
| All M13 cases | "Government employee / pensioner (excluding MTS / Class IV / Group D)" split into "has one" and "all are Group D". | old "excluded: yes" → has one: yes, all Group D: no; old "no" → has one: no | split | |
| F14c | Same split, from the message | employee: yes, Group D: yes; pensioner with ₹10,000+: yes, Group D: yes | "retired as a Group D peon … pension of 12,000" | |
| F13a, F13d | New: farmland in Maharashtra | yes | message says Nashik | |
| F14a–e, F13b, F13c | New: farmland in Maharashtra | not given (null) | not stated | |
| All M13 cases | New: PM-KISAN beneficiary | not given (null) | not stated | |
| F19a, F19b, F19d | "Meets Motor Vehicle Act conditions" replaced by age and medical fitness | age 21; medically fit: yes | "I am 21 … I meet the licence rules" | |
| F19c | Same | age and fitness not given | "not sure whether I meet the age, education and fitness rules" | |
| F19c | `social_category` "VJNT" | "VJ-A" | VJNT is now split into VJ-A and NT-B/C/D; every subgroup gives the same verdict | |
| F17a–e | New: in Bal Vatika (pre-school) | no | the class (1–9) is known | |
| F01a–c | New: `state_of_residence` | Maharashtra | "lives in Pune district" | |
| Other C23 cases | New: `state_of_residence` | not given (null) | not stated | |
| C02 cases | Bank field renamed to `has_bank_or_post_office_savings_account` (decision F4) | same yes/no as before | renamed only | |

---

## 3. When you're done

1. Edit the `cases.jsonl` files. Keep `labelled_by` and update `labelled_on` for cases you change.
2. Check the structure and agreement:
   ```
   python tests/evaluation/check_eligibility_gold.py --split development
   python tests/evaluation/check_eligibility_gold.py --split held_out
   ```
   These run the **live** rules, so schemes still waiting for sign-off (below) show as "can't tell" until they're reviewed.
3. Once the labels agree and the schemes are signed off, remove the `xfail` mark from:
   - `test_c0_fixed_workflow_matches_gold_on_development` in `tests/test_eval_runner.py`
   - `test_rule_engine_matches_gold_on_development_split` in `tests/test_eligibility_gold.py`

   They are strict, so they start failing as soon as everything agrees. That's the reminder.

---

## 4. Related: schemes waiting for rule sign-off (optional)

13 schemes have rules that an AI changed. Those rules are `draft`, so citizens get "can't tell" for these schemes until a person checks each draft rule against its cited sentence:

C02, C03, C13, C14, C19, C23, C29, M01, M13, M16, M18, M19, M20.

What changed in each, and what to look at, is in `data/rules/REVIEW_STATUS.md` under "Waiting for re-review". To sign one off:

1. Set its rules' `status` to `reviewed`.
2. Move it from `PENDING_REREVIEW_IDS` to the reviewed set in `tests/test_scheme_gold_set.py`.
3. Record it in `REVIEW_STATUS.md`.
