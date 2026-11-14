"""Answers that follow from another answer, so intake never asks a question already settled."""

from collections.abc import Mapping

# (known field, its value, implied field, implied value). Each line holds by definition; the converse
# is not implied unless it has its own line. "family" includes the applicant.
IMPLIES = [
    # Never paid income tax means not paying it now; paying it now means having paid it.
    ("is_or_was_income_tax_payer", False, "is_income_tax_payer", False),
    ("is_income_tax_payer", True, "is_or_was_income_tax_payer", True),
    ("is_or_was_income_tax_payer", False, "paid_income_tax_in_last_assessment_year", False),
    ("paid_income_tax_in_last_assessment_year", True, "is_or_was_income_tax_payer", True),
    ("is_income_tax_payer", True, "family_has_income_tax_payer", True),
    ("family_has_income_tax_payer", False, "is_income_tax_payer", False),
    ("paid_income_tax_in_last_assessment_year", True, "family_has_member_who_paid_income_tax_in_last_assessment_year", True),
    ("family_has_member_who_paid_income_tax_in_last_assessment_year", False, "paid_income_tax_in_last_assessment_year", False),
    # Schooling: 12th/ITI/diploma needs class 10, class 10 needs class 7.
    ("has_passed_12th_iti_diploma_or_higher", True, "has_passed_class_10", True),
    ("has_passed_class_10", True, "has_passed_class_7", True),
    ("has_passed_class_7", False, "has_passed_class_10", False),
    ("has_passed_class_10", False, "has_passed_12th_iti_diploma_or_higher", False),
    # What the applicant holds, their family holds.
    ("is_former_or_present_constitutional_post_holder", True, "family_has_former_or_present_constitutional_post_holder", True),
    ("family_has_former_or_present_constitutional_post_holder", False, "is_former_or_present_constitutional_post_holder", False),
    ("is_former_or_present_listed_political_office_holder", True, "family_has_former_or_present_listed_political_office_holder", True),
    ("family_has_former_or_present_listed_political_office_holder", False, "is_former_or_present_listed_political_office_holder", False),
    ("family_has_present_or_former_mp_or_mla", True, "family_has_former_or_present_listed_political_office_holder", True),
    ("family_has_former_or_present_listed_political_office_holder", False, "family_has_present_or_former_mp_or_mla", False),
    ("is_practicing_registered_professional_in_listed_field", True, "family_has_practicing_registered_professional_in_listed_field", True),
    ("family_has_practicing_registered_professional_in_listed_field", False, "is_practicing_registered_professional_in_listed_field", False),
    ("is_excluded_government_or_local_body_employee", True, "family_has_government_or_local_body_employee", True),
    ("family_has_government_or_local_body_employee", False, "is_excluded_government_or_local_body_employee", False),
    # Bank accounts and Aadhaar.
    ("has_aadhaar_linked_bank_account", True, "has_bank_account", True),
    ("has_aadhaar_linked_bank_account", True, "has_aadhaar", True),
    ("has_savings_account", True, "has_bank_account", True),
    ("has_savings_account", True, "has_savings_or_pm_kisan_account", True),
    ("has_savings_or_jandhan_account_with_ifsc", True, "has_bank_account", True),
    ("has_bank_account", False, "has_aadhaar_linked_bank_account", False),
    ("has_bank_account", False, "has_savings_account", False),
    ("has_bank_account", False, "has_savings_or_jandhan_account_with_ifsc", False),
    ("has_aadhaar", False, "has_aadhaar_linked_bank_account", False),
    # Work.
    ("is_unemployed", True, "is_unemployed_or_starting_new_venture", True),
    ("is_unemployed_or_starting_new_venture", False, "is_unemployed", False),
    ("is_unorganized_worker", True, "is_organized_sector_worker", False),
    ("is_organized_sector_worker", True, "is_unorganized_worker", False),
    ("is_epfo_member", True, "is_organized_sector_worker", True),
    ("is_esic_member", True, "is_organized_sector_worker", True),
    ("is_organized_sector_worker", False, "is_epfo_member", False),
    ("is_organized_sector_worker", False, "is_esic_member", False),
    ("registered_with_mbo_cww_board", True, "is_building_or_construction_worker", True),
    ("is_building_or_construction_worker", False, "registered_with_mbo_cww_board", False),
    # Gender, disability, residence.
    ("is_widow", True, "is_woman_or_girl", True),
    ("is_pregnant_in_2nd_or_3rd_trimester", True, "is_woman_or_girl", True),
    ("is_woman_or_girl", False, "is_widow", False),
    ("is_woman_or_girl", False, "is_pregnant_in_2nd_or_3rd_trimester", False),
    ("is_woman_or_girl", False, "is_woman_in_government_womens_ashram", False),
    ("has_permanent_orthopedic_disability", True, "has_disability", True),
    ("is_person_with_dwarfism", True, "has_disability", True),
    ("has_disability", False, "has_permanent_orthopedic_disability", False),
    ("has_disability", False, "is_person_with_dwarfism", False),
    ("has_disability", False, "is_child_with_intellectual_disability_needing_care", False),
    ("is_maharashtra_resident", True, "resides_in_india", True),
    ("resides_in_india", False, "is_maharashtra_resident", False),
    # Research degrees: basic/applied science PhD is a science PhD, which counts as a PhD/MD/MS.
    ("has_phd_in_basic_or_applied_sciences", True, "has_phd_in_science_engineering_or_ms_md", True),
    ("has_phd_in_science_engineering_or_ms_md", True, "has_phd_md_ms_or_thesis_submitted", True),
    ("has_phd_md_ms_or_thesis_submitted", False, "has_phd_in_science_engineering_or_ms_md", False),
    ("has_phd_in_science_engineering_or_ms_md", False, "has_phd_in_basic_or_applied_sciences", False),
]


def derive_implied_facts(profile: Mapping[str, object]) -> dict[str, object]:
    """The profile plus facts implied by it, followed through chains. Facts already known win."""
    out = dict(profile)
    changed = True
    while changed:  # ends: each pass only fills unknown fields
        changed = False
        for field, value, implied, implied_value in IMPLIES:
            if out.get(field) is value and out.get(implied) is None:
                out[implied] = implied_value
                changed = True
    return out
