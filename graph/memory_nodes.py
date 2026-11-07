"""Memory steps of the agent workflow: what is read before eligibility, what is written after.

The helpers hold no graph state. The memory scope comes from the run config, which the
backend sets from the signed-in identity; it never comes from the model or from graph state.
A memory failure is logged without values and never stops a run.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from agents.contracts import FactMap
from agents.family import family_members, family_relation
from agents.memory import (
    ApplicationReference,
    MemoryFact,
    MemoryScope,
    MemoryService,
    clean_relation,
    utc_now,
)
from agents.memory_service import HouseholdAllowlist

logger = logging.getLogger(__name__)

SCOPE_KEYS = ("memory_actor_id", "memory_household_id", "memory_role")


@dataclass(frozen=True)
class MemoryContext:
    service: MemoryService
    scope: MemoryScope

    @property
    def allowlist(self) -> HouseholdAllowlist:
        return self.service.allowlist


def memory_config(scope: MemoryScope) -> dict[str, str]:
    """Run-config entries that carry a scope into the graph; merge them into `configurable`."""
    return dict(zip(SCOPE_KEYS, (scope.actor_id, scope.household_id, scope.actor_role)))


def memory_context(memory: MemoryService | None, config: Mapping[str, Any] | None) -> MemoryContext | None:
    """The memory service with the run's scope, or None when memory is off or the scope is missing."""
    if memory is None:
        return None
    configurable = (config or {}).get("configurable") or {}
    actor_id, household_id, role = (configurable.get(key) for key in SCOPE_KEYS)
    if not actor_id or not household_id or role not in ("citizen", "operator"):
        return None
    try:
        return MemoryContext(memory, MemoryScope(actor_id=actor_id, household_id=household_id, actor_role=role))
    except ValueError:
        return None


def load_remembered(ctx: MemoryContext, specs: Mapping[str, Any], present: FactMap) -> FactMap:
    """Remembered facts for the fields the schemes need and the run does not already have."""
    fields = [f for f in specs if f not in present and ctx.allowlist.is_field_allowed(f)]
    if not fields:
        return {}
    usable: FactMap = {}
    for field, value in ctx.service.read_facts(ctx.scope, fields).items():
        try:
            ctx.allowlist.validate_fact(field, value)
        except ValueError:
            logger.warning("A remembered fact no longer fits the policy and was ignored: %s", field)
            continue
        usable[field] = value
    return usable


def save_confirmed(
    ctx: MemoryContext, confirmed: FactMap, remembered: FactMap, now: datetime | None = None
) -> tuple[list[str], FactMap]:
    """Remember the confirmed facts the policy allows; return the fields touched and what memory now holds.

    A fact the person confirmed unchanged only gets a later reconfirm date. A new or changed
    fact starts a fresh retention window.
    """
    allowed = {f: v for f, v in confirmed.items() if ctx.allowlist.is_field_allowed(f)}
    if not allowed:
        return [], remembered
    consent = ctx.service.active_consent(ctx.scope, "profile_facts")
    if consent is None:
        return [], remembered

    now = now or utc_now()
    unchanged = [f for f, v in allowed.items() if f in remembered and remembered[f] == v]
    saved = list(ctx.service.reconfirm_facts(ctx.scope, unchanged, now))
    held = dict(remembered)
    for field, value in allowed.items():
        if field in unchanged:
            continue
        try:
            reconfirm_by, expires_at = ctx.allowlist.retention_window(field, now)
            ctx.service.save_confirmed_fact(
                ctx.scope,
                MemoryFact(
                    field=field,
                    value=value,
                    source="citizen_confirmed",
                    confirmed_at=now,
                    reconfirm_by=reconfirm_by,
                    expires_at=expires_at,
                    consent_reference=consent.consent_reference,
                ),
            )
        except ValueError:
            logger.warning("A confirmed fact was not remembered: %s", field)
            continue
        saved.append(field)
        held[field] = value
    return sorted(saved), held


def save_application_reference(
    ctx: MemoryContext,
    scheme_id: str,
    application_id: str,
    subject: str,
    relation: str | None,
    now: datetime | None = None,
) -> bool:
    """Remember a submitted application for later status checks; False when there is no consent."""
    consent = ctx.service.active_consent(ctx.scope, "application_references")
    if consent is None:
        return False
    now = now or utc_now()
    for_other = ctx.scope.actor_role == "operator" or subject == "other"
    label = (family_relation(relation) or clean_relation(relation)) if for_other else None
    nickname = None
    if label and family_relation(label):  # a returning family member keeps their nickname
        nickname = next(
            (m.nickname for m in family_members(ctx.service.read_application_references(ctx.scope)) if m.relation == label),
            None,
        )
    ctx.service.save_application_reference(
        ctx.scope,
        ApplicationReference(
            scheme_id=scheme_id,
            application_id=application_id,
            submitted_at=now,
            expires_at=now + timedelta(days=ctx.allowlist.application_reference_expiry_days),
            consent_reference=consent.consent_reference,
            subject="other" if for_other else "self",
            relation=label,
            submitted_by=ctx.scope.actor_id,
            nickname=nickname,
        ),
    )
    return True
