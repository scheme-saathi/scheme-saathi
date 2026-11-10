"""Answers that follow from another answer, so intake never asks a question already settled."""

from collections.abc import Mapping

# (known field, its value) -> (implied field, implied value). Never paid income tax means not paying
# it now; paying it now means having paid it. The converse of each is not implied.
IMPLIES = {
    ("is_or_was_income_tax_payer", False): ("is_income_tax_payer", False),
    ("is_income_tax_payer", True): ("is_or_was_income_tax_payer", True),
}


def derive_implied_facts(profile: Mapping[str, object]) -> dict[str, object]:
    """The profile plus facts implied by it. Facts already in the profile win."""
    out = dict(profile)
    for (field, value), (implied, implied_value) in IMPLIES.items():
        if profile.get(field) is value and out.get(implied) is None:
            out[implied] = implied_value
    return out
