from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP(
    "mock-portal",
    instructions="Application drafting and submission flow. This server is write-enabled only for the Application Agent.",
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
) -> dict[str, Any]:
    """Write-enabled application creation or submission for the Application Agent.

    Args:
        scheme_id: The scheme the citizen is applying for.
        applicant: A JSON object containing applicant facts and personal data.
        documents: Optional uploaded document metadata keyed by type.
        submit: Whether to immediately move the application to the submitted stage.

    Returns:
        A JSON object with the application ID and resulting status.
    """
    if not scheme_id.strip():
        return _error("invalid_scheme_id", "scheme_id must be a non-empty string.")

    application_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    status = "submitted" if submit else "draft"
    payload = {
        "application_id": application_id,
        "scheme_id": scheme_id,
        "applicant": applicant,
        "documents": documents or {},
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    if submit:
        payload["submitted_at"] = now
    APPLICATIONS[application_id] = payload
    return {"ok": True, "access": "write", "data": payload}


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
def create_application_route(payload: ApplicationCreateRequest) -> dict[str, Any]:
    return create_application(
        scheme_id=payload.scheme_id,
        applicant=payload.applicant,
        documents=payload.documents,
        submit=payload.submit,
    )


@app.get("/applications/{application_id}")
def get_application_route(application_id: str) -> dict[str, Any]:
    return get_application_status(application_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
