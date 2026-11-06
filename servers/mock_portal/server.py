from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from servers.mock_portal.authorization import (
    CapabilityError,
    application_payload_hash,
    consume_write_capability,
)
from app.auth import AuthenticatedHousehold, authenticated_household

mcp = FastMCP(
    "mock-portal",
    instructions="Application drafting and submission flow. Write calls require a valid one-use server capability.",
)

app = FastAPI(title="Scheme Saathi Mock Portal")
APPLICATIONS: dict[str, dict[str, Any]] = {}


class ApplicationCreateRequest(BaseModel):
    scheme_id: str = Field(..., min_length=1)
    applicant: dict[str, Any] = Field(default_factory=dict)
    documents: dict[str, Any] | None = None
    submit: bool = False


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "access": "write", "error": {"code": code, "message": message}}


@mcp.tool()
def create_application(
    scheme_id: str,
    applicant: dict[str, Any],
    documents: dict[str, Any] | None = None,
    submit: bool = False,
    write_capability: str = "",
    household_id: str | None = None,
) -> dict[str, Any]:
    """Write-enabled application creation or submission for the Application Agent.

    Args:
        scheme_id: The scheme the citizen is applying for.
        applicant: A JSON object containing applicant facts and personal data.
        documents: Optional uploaded document metadata keyed by type.
        submit: Whether to immediately move the application to the submitted stage.
        write_capability: Short-lived one-use capability from the trusted workflow.

    Returns:
        A JSON object with the application ID and resulting status.
    """
    if not scheme_id.strip():
        return _error("invalid_scheme_id", "scheme_id must be a non-empty string.")

    form_hash = application_payload_hash(scheme_id, applicant, documents)
    action = "submit_application" if submit else "create_draft"
    try:
        consume_write_capability(
            write_capability,
            action,
            scheme_id,
            form_hash,
            household_id,
        )
    except CapabilityError as exc:
        return _error("forbidden", str(exc))

    application_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    status = "submitted" if submit else "draft"
    payload = {
        "application_id": application_id,
        "scheme_id": scheme_id,
        "applicant": applicant,
        "documents": documents or {},
        "form_hash": form_hash,
        "household_id": household_id,
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    if submit:
        payload["submitted_at"] = now
    APPLICATIONS[application_id] = payload
    return {
        "ok": True,
        "access": "write",
        "data": {key: value for key, value in payload.items() if key != "household_id"},
    }


@mcp.tool()
def submit_draft(application_id: str, write_capability: str = "") -> dict[str, Any]:
    """Write-enabled: move an existing draft application to the submitted stage.

    Args:
        application_id: The draft created earlier by create_application.
        write_capability: One-use capability tied to this draft and its approved form.

    Returns:
        A JSON object with the updated application, or an error if it is missing or not a draft.
    """
    application = APPLICATIONS.get(application_id)
    if application is None:
        return _error("application_not_found", f"Application '{application_id}' was not found.")
    if application["status"] != "draft":
        return _error("not_a_draft", f"Application '{application_id}' is already {application['status']}.")
    current_hash = application_payload_hash(
        application["scheme_id"],
        application["applicant"],
        application["documents"],
    )
    if current_hash != application["form_hash"]:
        return _error("application_changed", "The draft no longer matches its approved form.")
    try:
        consume_write_capability(
            write_capability,
            "submit_draft",
            application_id,
            current_hash,
            application.get("household_id"),
        )
    except CapabilityError as exc:
        return _error("forbidden", str(exc))

    now = datetime.now(timezone.utc).isoformat()
    application.update(status="submitted", submitted_at=now, updated_at=now)
    return {"ok": True, "access": "write", "data": application}


@mcp.tool()
def get_application_status(application_id: str) -> dict[str, Any]:
    """Read-only lookup of a submitted or draft application status.

    Args:
        application_id: The unique application identifier.

    Returns:
        A JSON object with the current application status.
    """
    application = APPLICATIONS.get(application_id)
    if application is None:
        return {
            "ok": False,
            "access": "read",
            "error": {"code": "application_not_found", "message": f"Application '{application_id}' was not found."},
        }
    return {"ok": True, "access": "read", "data": {"application_id": application_id, "status": application["status"]}}


@app.post("/applications")
def create_application_route(
    payload: ApplicationCreateRequest,
    write_capability: str | None = Header(None, alias="X-Write-Capability"),
    principal: AuthenticatedHousehold = Depends(authenticated_household),
) -> dict[str, Any]:
    if not write_capability:
        raise HTTPException(status_code=401, detail="A write capability is required.")
    result = create_application(
        scheme_id=payload.scheme_id,
        applicant=payload.applicant,
        documents=payload.documents,
        submit=payload.submit,
        write_capability=write_capability,
        household_id=principal.household_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=403, detail="The write capability was not accepted.")
    return result


@app.get("/applications/{application_id}")
def get_application_route(
    application_id: str,
    principal: AuthenticatedHousehold = Depends(authenticated_household),
) -> dict[str, Any]:
    application = APPLICATIONS.get(application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    if application.get("household_id") != principal.household_id:
        raise HTTPException(status_code=403, detail="Application belongs to another household.")
    return get_application_status(application_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
