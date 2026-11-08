"""Long-term memory endpoints: consent, what is remembered, forgetting, and saved applications.

Every endpoint takes the household and the person from the verified token. Nothing here
accepts a household or user ID from the request.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.family import delete_family_member, family_members, family_relation, rename_family_member
from agents.memory import (
    ApplicationReference,
    MemoryConsent,
    MemoryService,
    Purpose,
    as_utc,
    utc_now,
)
from agents.memory import remove_application as remove_saved_application
from app import memory_runtime
from app.auth import AuthenticatedHousehold, authenticated_household
from app.memory_runtime import memory_scope
from graph import tools
from graph.memory_nodes import NOTICE_VERSION, MemoryContext, save_application_reference

logger = logging.getLogger(__name__)

CONSENT_EXPIRY_DAYS = 180
PURPOSES: tuple[Purpose, ...] = ("profile_facts", "application_references")
# An operator keeps no household details and has no standing consent. The person being helped
# agrees for each application when it is approved, and that agreement is recorded for it alone.
PURPOSES_BY_ROLE: dict[str, tuple[Purpose, ...]] = {
    "citizen": PURPOSES,
    "operator": (),
}
MAX_WITHDRAWALS = 10  # one person should never hold more than one active consent per purpose
FORGET_NOTE = "Applications already submitted to a government portal are not deleted."

router = APIRouter(prefix="/api", tags=["Memory"])


def optional_memory() -> MemoryService | None:
    return memory_runtime.get_memory_service()


def require_memory(service: MemoryService | None = Depends(optional_memory)) -> MemoryService:
    if service is None:
        raise HTTPException(status_code=503, detail="Remembering details is not available.")
    return service


class ConsentChange(BaseModel):
    purpose: Literal["profile_facts", "application_references"]
    granted: bool


def _consent_state(service: MemoryService, principal: AuthenticatedHousehold) -> dict[str, Any]:
    scope = memory_scope(principal)
    state: dict[str, Any] = {}
    for purpose in PURPOSES_BY_ROLE[principal.role]:
        consent = service.active_consent(scope, purpose)
        state[purpose] = {
            "granted": consent is not None,
            "decided_at": consent.decided_at if consent else None,
            "expires_at": consent.expires_at if consent else None,
        }
    return state


def _policy(service: MemoryService) -> dict[str, Any]:
    allowlist = service.allowlist
    fields = []
    for field, policy in allowlist.allowed_fields.items():
        retention = policy.get("retention", {})
        if retention.get("store", True):
            fields.append(
                {
                    "field": field,
                    "purpose": policy.get("purpose", ""),
                    "reconfirm_days": retention.get("reconfirm_days"),
                    "expiry_days": retention.get("expiry_days"),
                }
            )
    return {
        "fields": fields,
        "temporary_only": list(allowlist.temporary_only),
        "application_reference_expiry_days": allowlist.application_reference_expiry_days,
    }


@router.get("/memory/consent")
def get_consent(
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """What the person has agreed to remember, and the policy that applies to it."""
    return {
        "role": principal.role,
        "notice_version": NOTICE_VERSION,
        "consent_expiry_days": CONSENT_EXPIRY_DAYS,
        "purposes": _consent_state(service, principal),
        "policy": _policy(service),
    }


@router.put("/memory/consent")
def change_consent(
    change: ConsentChange,
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """Agree to remember, or stop remembering and delete what was saved under that agreement.

    Agreeing when an agreement is already active changes nothing, so retention is never
    extended silently. An operator has no standing agreement to set: the person being helped
    agrees for each application when it is approved.
    """
    if change.purpose not in PURPOSES_BY_ROLE[principal.role]:
        raise HTTPException(
            status_code=403,
            detail="Operators record the agreement of the person they help for each application, when it is approved.",
        )
    scope = memory_scope(principal)
    try:
        if change.granted:
            if service.active_consent(scope, change.purpose) is None:
                now = utc_now()
                service.record_consent(
                    scope,
                    MemoryConsent(
                        purpose=change.purpose,
                        granted=True,
                        notice_version=NOTICE_VERSION,
                        decided_at=now,
                        expires_at=now + timedelta(days=CONSENT_EXPIRY_DAYS),
                        consent_reference=f"consent-{uuid4().hex}",
                    ),
                )
        else:
            for _ in range(MAX_WITHDRAWALS):
                consent = service.active_consent(scope, change.purpose)
                if consent is None:
                    break
                service.withdraw_consent(scope, consent.consent_reference)
    except Exception:
        logger.exception("Could not change the memory consent.")
        raise HTTPException(status_code=500, detail="The choice could not be saved.")
    return {"purposes": _consent_state(service, principal)}


@router.get("/memory")
def get_memory(
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """The details remembered for this household, with their dates."""
    now = utc_now()
    facts = [
        {
            "field": fact.field,
            "value": fact.value,
            "confirmed_at": fact.confirmed_at,
            "reconfirm_by": fact.reconfirm_by,
            "expires_at": fact.expires_at,
            "reconfirm_due": as_utc(fact.reconfirm_by) <= now,
        }
        for fact in service.list_facts(memory_scope(principal))
    ]
    return {"facts": facts}


@router.delete("/memory/facts/{field}")
def forget_fact(
    field: str,
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    if principal.role == "operator":
        raise HTTPException(status_code=403, detail="Operators cannot delete a household's details.")
    if not service.delete_fact(memory_scope(principal), field):
        raise HTTPException(status_code=404, detail="That detail is not remembered.")
    return {"status": "success", "field": field}


def _application_item(reference: ApplicationReference) -> dict[str, Any]:
    return {
        "application_id": reference.application_id,
        "scheme_id": reference.scheme_id,
        "submitted_at": reference.submitted_at,
        "expires_at": reference.expires_at,
        "relation": reference.relation,
    }


@router.get("/applications")
def list_applications(
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """Applications saved for this person: their own, each family member's, and other people's."""
    references = service.read_application_references(memory_scope(principal))
    members = family_members(references)
    in_family = {item.application_id for member in members for item in member.applications}
    return {
        "for_me": [_application_item(r) for r in references if r.subject != "other"],
        "family": [
            {
                "relation": member.relation,
                "nickname": member.nickname,
                "applications": [_application_item(r) for r in member.applications],
            }
            for member in members
        ],
        "for_others": [
            _application_item(r) for r in references if r.subject == "other" and r.application_id not in in_family
        ],
    }


class FamilyRename(BaseModel):
    nickname: str | None = None


def _family_relation_or_404(relation: str) -> str:
    canonical = family_relation(relation)
    if canonical is None:
        raise HTTPException(status_code=404, detail="That is not a family member in your list.")
    return canonical


@router.patch("/family/{relation}")
def rename_member(
    relation: str,
    change: FamilyRename,
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """Give a family member a nickname, or clear it. Letters only, so no number or ID is kept."""
    canonical = _family_relation_or_404(relation)
    try:
        changed = rename_family_member(service, memory_scope(principal), canonical, change.nickname)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not changed:
        raise HTTPException(status_code=404, detail="That is not a family member in your list.")
    return {"status": "success", "relation": canonical}


@router.delete("/family/{relation}")
def remove_member(
    relation: str,
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """Remove a family member and their saved applications. Nothing at the portal is touched."""
    canonical = _family_relation_or_404(relation)
    removed = delete_family_member(service, memory_scope(principal), canonical)
    if not removed:
        raise HTTPException(status_code=404, detail="That is not a family member in your list.")
    return {"status": "success", "relation": canonical, "applications_removed": removed}


@router.get("/applications/{application_id}/status")
def application_status(
    application_id: str,
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """The portal's current status, for an application in this person's own list only."""
    reference = next(
        (r for r in service.read_application_references(memory_scope(principal)) if r.application_id == application_id),
        None,
    )
    if reference is None:
        raise HTTPException(status_code=404, detail="This application is not in your list.")
    result: dict[str, Any] = {
        "application_id": application_id,
        "scheme_id": reference.scheme_id,
        "checked_at": utc_now(),
    }
    try:
        result["status"] = tools.application_status(application_id, principal.household_id)["status"]
        result["found_at_portal"] = True
    except tools.ToolCallError as error:
        if error.code != "application_not_found":
            logger.warning("The portal status could not be read.")
            raise HTTPException(status_code=503, detail="The portal status could not be read right now.") from error
        result["status"] = None
        result["found_at_portal"] = False
    return result


@router.delete("/applications/{application_id}")
def remove_application(
    application_id: str,
    principal: AuthenticatedHousehold = Depends(authenticated_household),
    service: MemoryService = Depends(require_memory),
) -> dict[str, Any]:
    """Remove an application from the saved list. The application at the portal is not touched."""
    if not remove_saved_application(service, memory_scope(principal), application_id):
        raise HTTPException(status_code=404, detail="This application is not in your list.")
    return {"status": "success", "application_id": application_id}


def remember_submission(
    memory: MemoryService,
    principal: AuthenticatedHousehold,
    result: dict[str, Any],
    subject: str,
    relation: str | None,
    citizen_agreed: bool = False,
) -> dict[str, Any]:
    """Save a submitted application from a workflow result, if the person agreed. Never raises."""
    submission = result.get("submission")
    scheme_id = (result.get("application") or {}).get("scheme_id")
    if not isinstance(submission, dict) or not submission.get("application_id") or not scheme_id:
        return {}
    try:
        saved = save_application_reference(
            MemoryContext(memory, memory_scope(principal)),
            scheme_id,
            submission["application_id"],
            subject,
            relation,
            citizen_agreed=citizen_agreed,
        )
    except Exception:
        logger.warning("The submitted application could not be remembered.")
        saved = False
    return {"reference_saved": saved}
