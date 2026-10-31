import json

from fastapi.testclient import TestClient

from app.api import create_api
from app.business_logic import DemoService


def parse_events(body):
    events = []
    for block in body.decode("utf-8").split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data = []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


def test_streamed_demo_workflow_requires_documents_before_approval():
    client = TestClient(create_api(DemoService()))
    scheme_id = "SYNTH-PENSION-001"
    response = client.post(
        "/api/analyze",
        json={
            "citizen": {"age": 62, "income": 250000, "is_widow": True},
            "scheme_ids": [scheme_id],
        },
    )

    assert response.status_code == 200
    events = parse_events(response.content)
    assert any(name == "progress" for name, _ in events)
    result = next(payload for name, payload in events if name == "result")
    assert result["verdicts"][scheme_id]["verdict"] == "eligible"
    assert result["approval"]["payload_hash"]

    thread_id = result["thread_id"]
    approval = result["approval"]
    blocked = client.post(
        f"/api/threads/{thread_id}/decision",
        json={"action": "approve", "payload_hash": approval["payload_hash"]},
    )
    assert blocked.status_code == 409
    assert "required documents" in blocked.json()["detail"]

    for document_type in result["documents"][scheme_id]:
        uploaded = client.post(
            f"/api/threads/{thread_id}/documents/upload",
            data={"scheme_id": scheme_id, "document_type": document_type},
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        )
        assert uploaded.status_code == 200

    submitted = client.post(
        f"/api/threads/{thread_id}/decision",
        json={"action": "approve", "payload_hash": approval["payload_hash"]},
    )
    assert submitted.status_code == 200
    final_events = parse_events(submitted.content)
    final_result = next(payload for name, payload in final_events if name == "result")
    assert final_result["submission"]["status"].startswith("submitted")


def test_unknown_scheme_is_rejected_before_streaming():
    client = TestClient(create_api(DemoService()))

    response = client.post(
        "/api/analyze",
        json={
            "citizen": {"age": 62, "income": 250000, "is_widow": True},
            "scheme_ids": ["unknown-scheme"],
        },
    )

    assert response.status_code == 422
    assert "unknown-scheme" in response.json()["detail"]
