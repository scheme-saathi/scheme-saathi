"""Family members: which relations count as family, and grouping, renaming and deleting them.

A family member is not a record of its own. It is the set of saved applications that carry the
same family relation, so it expires with its last application and holds only the relation and
an optional nickname. No facts about the person are kept.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from agents.memory import (
    RELATION_LABEL,
    ApplicationReference,
    MemoryScope,
    MemoryService,
    as_utc,
    remove_application,
)

_ALIASES: dict[str, tuple[str, ...]] = {
    "mother": ("mother", "mom", "mum", "mommy", "mummy", "maa", "mata", "माँ", "मां", "माता", "आई", "मम्मी"),
    "father": ("father", "dad", "daddy", "papa", "pita", "पिता", "पिताजी", "पापा", "बाबा", "वडील"),
    "grandmother": ("grandmother", "grandma", "dadi", "nani", "दादी", "नानी", "आजी"),
    "grandfather": ("grandfather", "grandpa", "dada", "nana", "दादा", "नाना", "आजोबा"),
    "son": ("son", "beta", "बेटा", "मुलगा"),
    "daughter": ("daughter", "beti", "बेटी", "मुलगी"),
    "wife": ("wife", "biwi", "patni", "पत्नी", "बीवी", "बायको"),
    "husband": ("husband", "pati", "पति", "नवरा"),
}
FAMILY_RELATIONS: tuple[str, ...] = tuple(_ALIASES)
_CANONICAL = {alias: relation for relation, aliases in _ALIASES.items() for alias in aliases}
_SPLIT = re.compile(r"[\s.,;:!?()\"“”।]+")
_POSSESSIVE = ("'s", "’s")


def family_relation(value: object) -> str | None:
    """The family relation a word names, in English, or None for anyone who is not family."""
    if not isinstance(value, str):
        return None
    word = value.strip().lower()
    for suffix in _POSSESSIVE:
        word = word.removesuffix(suffix)
    return _CANONICAL.get(word)


def relation_in_text(text: str) -> str | None:
    """The first family relation a message names, such as "mother" in "my mother's application"."""
    for word in _SPLIT.split(text.lower()):
        relation = family_relation(word)
        if relation:
            return relation
    return None


def clean_nickname(value: object) -> str | None:
    """A nickname: letters only, so a number or ID cannot be kept in it. Blank means none."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("A nickname must be text.")
    nickname = value.strip()
    if not nickname:
        return None
    if not RELATION_LABEL.fullmatch(nickname):
        raise ValueError("A nickname is a short word made of letters, never a number or ID.")
    return nickname


class FamilyMember(BaseModel):
    relation: str
    nickname: str | None
    applications: list[ApplicationReference]


def family_members(references: list[ApplicationReference]) -> list[FamilyMember]:
    """Group saved applications by family relation, the member with the newest application first."""
    grouped: dict[str, list[ApplicationReference]] = {}
    for reference in references:
        relation = family_relation(reference.relation) if reference.subject == "other" else None
        if relation:
            grouped.setdefault(relation, []).append(reference)
    members = []
    for relation, items in grouped.items():
        items.sort(key=lambda item: as_utc(item.submitted_at), reverse=True)
        members.append(
            FamilyMember(
                relation=relation,
                nickname=next((item.nickname for item in items if item.nickname), None),
                applications=items,
            )
        )
    return sorted(members, key=lambda member: as_utc(member.applications[0].submitted_at), reverse=True)


def _of_member(service: MemoryService, scope: MemoryScope, relation: str) -> list[ApplicationReference]:
    return [
        reference
        for reference in service.read_application_references(scope)
        if reference.subject == "other" and family_relation(reference.relation) == relation
    ]


def rename_family_member(
    service: MemoryService, scope: MemoryScope, relation: str, nickname: str | None
) -> int:
    """Give every saved application of this family member the nickname; returns how many changed."""
    nickname = clean_nickname(nickname)
    references = _of_member(service, scope, relation)
    for reference in references:
        service.save_application_reference(
            scope, ApplicationReference(**{**reference.model_dump(), "nickname": nickname})
        )
    return len(references)


def delete_family_member(service: MemoryService, scope: MemoryScope, relation: str) -> int:
    """Remove the family member's saved applications, and so the member; returns how many went.

    Applications already submitted to the portal are not touched.
    """
    references = _of_member(service, scope, relation)
    for reference in references:
        remove_application(service, scope, reference.application_id)
    return len(references)
