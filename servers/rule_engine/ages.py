"""Ages worked out from one date of birth, so intake never asks a second age question (Phase 3.5)."""

from collections.abc import Mapping
from datetime import date

# Rule fields an age in whole years can't settle: "age nearer birthday" may be age or age + 1,
# and a 17.5-year minimum needs months. Intake asks for date_of_birth instead of these.
DOB_DERIVED = {"age_nearer_birthday", "age_in_months"}


def derive_age_fields(profile: Mapping[str, object], today: date | None = None) -> dict[str, object]:
    """The profile plus age fields worked out from ``date_of_birth`` (YYYY-MM-DD).

    Facts already in the profile win. A missing, malformed or future date adds nothing.
    """
    out = dict(profile)
    try:
        born = date.fromisoformat(profile["date_of_birth"])  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return out
    today = today or date.today()
    if born > today:
        return out
    months = (today.year - born.year) * 12 + today.month - born.month - (today.day < born.day)
    years = months // 12
    # Nearer birthday: the coming birthday counts once six months have passed since the last one.
    derived = {"age": years, "age_in_months": months, "age_nearer_birthday": years + (months % 12 >= 6)}
    for field, value in derived.items():
        if out.get(field) is None:
            out[field] = value
    return out
