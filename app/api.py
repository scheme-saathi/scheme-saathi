"""FastAPI endpoints for the Streamlit Scheme Saathi demo."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from graph.tools import ToolCallError

if __package__:
    from .business_logic import (
        DemoService,
        SessionNotFoundError,
        WorkflowConflictError,
    )
else:
    from business_logic import (
        DemoService,
        SessionNotFoundError,
        WorkflowConflictError,
    )


class AnalysisRequest(BaseModel):
    citizen: dict[str, Any]
    scheme_ids: list[str] | None = Field(default=None, min_length=1)


class DecisionRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    payload_hash: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


@lru_cache(maxsize=1)
def get_service() -> DemoService:
    """Share one in-memory demo workflow across requests."""
    return DemoService()


def _event_stream(
    events: Any,
) -> StreamingResponse:
    def encode_events():
        for name, payload in events:
            data = json.dumps(payload, ensure_ascii=False, default=str)
            yield f"event: {name}\ndata: {data}\n\n"

    return StreamingResponse(
        encode_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def create_api(service: DemoService | None = None) -> FastAPI:
    """Create the API app; a service can be injected by endpoint tests."""
    demo = service or get_service()
    application = FastAPI(title="Scheme Saathi Demo API", version="0.1.0")

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/schemes")
    def schemes() -> dict[str, list[dict[str, Any]]]:
        try:
            return {"schemes": demo.available_schemes()}
        except ToolCallError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.post("/api/analyze")
    def analyze(payload: AnalysisRequest) -> StreamingResponse:
        try:
            events = demo.analyze(payload.citizen, payload.scheme_ids)
        except ToolCallError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _event_stream(events)

    @application.post("/api/chat")
    def chat(payload: ChatRequest) -> StreamingResponse:
        return _event_stream(
            demo.chat_turn(payload.user_input, payload.session_id)
        )

    @application.post("/api/threads/{thread_id}/documents/upload")
    async def upload_document(
        thread_id: str,
        scheme_id: str = Form(...),
        document_type: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        filename = file.filename or ""
        if not filename:
            raise HTTPException(status_code=422, detail="Choose a document file.")
        content = await file.read(10 * 1024 * 1024 + 1)
        try:
            return demo.upload_document(
                thread_id,
                scheme_id,
                document_type,
                filename,
                file.content_type,
                content,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorkflowConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        finally:
            await file.close()

    @application.post("/api/threads/{thread_id}/decision")
    def decide(thread_id: str, payload: DecisionRequest) -> StreamingResponse:
        try:
            events = demo.decide(
                thread_id,
                payload.action,
                payload.payload_hash,
                payload.changes,
            )
        except SessionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorkflowConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _event_stream(events)

    return application


app = create_api()
