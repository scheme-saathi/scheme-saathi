"""Memory API: consent, what is remembered, forgetting, saved applications and their status."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agents.memory import ApplicationReference, MemoryConsent, MemoryFact, MemoryScope
from agents.memory_service import HouseholdAllowlist, InMemoryMemoryService
from app import api, memory_runtime
from app.auth import AuthenticatedHousehold, authenticated_household
from app.memory_api import optional_memory
from graph import tools
from graph.memory_nodes import MemoryContext, save_application_reference


@pytest.fixture
def memory():
    return InMemoryMemoryService(HouseholdAllowlist.from_policy_file())


@pytest.fixture
def who():
    return {"household": "hh1", "sub": "user-1", "role": "citizen"}


class Surfaces:
    """Stands in for the application-workflow service and the conversation service."""

    def __init__(self):
        self.calls = []
        self.failing = set()

    def _run(self, name, household_id):
        self.calls.append((name, household_id))
        if name in self.failing:
            raise RuntimeError("the store is down")
        return 2

    def forget_household_documents(self, household_id):
        return self._run("documents", household_id)

    def forget_household_workflows(self, household_id):
        return self._run("application_workflows", household_id)

    def forget_household(self, household_id):
        return self._run("conversations", household_id)


@pytest.fixture
def surfaces(monkeypatch):
    surfaces = Surfaces()
    monkeypatch.setattr(api, "get_workflow_service", lambda: surfaces)
    return surfaces


@pytest.fixture
def client(memory, who, surfaces):
    application = api.create_api(service=surfaces)
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold(
        who["household"], who["sub"], who["role"]
    )
    application.dependency_overrides[optional_memory] = lambda: memory
    return TestClient(application)


def scope(household="hh1", sub="user-1"):
    return MemoryScope(actor_id=sub, household_id=household, actor_role="citizen")


def grant(memory, purpose, household="hh1", sub="user-1", reference=None):
    now = datetime.utcnow()
    memory.record_consent(
        scope(household, sub),
        MemoryConsent(
            purpose=purpose,
            granted=True,
            notice_version="1",
            decided_at=now,
            expires_at=now + timedelta(days=60),
            consent_reference=reference or f"{purpose}-{household}",
        ),
    )


def remember_fact(memory, field="age", value=34, household="hh1", confirmed_days_ago=0, reconfirm_days=30, expiry_days=90):
    confirmed_at = datetime.utcnow() - timedelta(days=confirmed_days_ago)
    memory.save_confirmed_fact(
        scope(household),
        MemoryFact(
            field=field,
            value=value,
            source="citizen_confirmed",
            confirmed_at=confirmed_at,
            reconfirm_by=confirmed_at + timedelta(days=reconfirm_days),
            expires_at=confirmed_at + timedelta(days=expiry_days),
            consent_reference=f"profile_facts-{household}",
        ),
    )


def remember_application(memory, application_id, household="hh1", subject="self", relation=None, scheme_id="C01"):
    now = datetime.utcnow()
    memory.save_application_reference(
        scope(household),
        ApplicationReference(
            scheme_id=scheme_id,
            application_id=application_id,
            submitted_at=now,
            expires_at=now + timedelta(days=90),
            consent_reference=f"application_references-{household}",
            subject=subject,
            relation=relation,
            submitted_by="user-1",
        ),
    )


# Consent


def test_nothing_is_remembered_until_the_person_agrees(client):
    body = client.get("/api/memory/consent").json()
    assert body["purposes"]["profile_facts"]["granted"] is False
    assert body["purposes"]["application_references"]["granted"] is False
    assert body["notice_version"]
    assert body["consent_expiry_days"] == 180


def test_the_consent_response_lists_the_fields_and_periods_that_apply(client):
    policy = client.get("/api/memory/consent").json()["policy"]
    age = next(item for item in policy["fields"] if item["field"] == "age")
    assert (age["reconfirm_days"], age["expiry_days"]) == (30, 90)
    assert "has_disability" in policy["temporary_only"]
    assert policy["application_reference_expiry_days"] == 90


def test_agreeing_records_the_choice_for_one_purpose_only(client):
    response = client.put("/api/memory/consent", json={"purpose": "profile_facts", "granted": True})
    assert response.status_code == 200
    purposes = response.json()["purposes"]
    assert purposes["profile_facts"]["granted"] is True
    assert purposes["application_references"]["granted"] is False
    assert purposes["profile_facts"]["expires_at"] is not None


def test_agreeing_again_does_not_extend_the_agreement(client, memory):
    client.put("/api/memory/consent", json={"purpose": "profile_facts", "granted": True})
    first = memory.active_consent(scope(), "profile_facts")
    client.put("/api/memory/consent", json={"purpose": "profile_facts", "granted": True})
    assert memory.active_consent(scope(), "profile_facts").consent_reference == first.consent_reference


def test_stopping_deletes_what_was_saved_under_that_purpose_only(client, memory):
    grant(memory, "profile_facts")
    grant(memory, "application_references")
    remember_fact(memory)
    remember_application(memory, "APP-1")

    response = client.put("/api/memory/consent", json={"purpose": "profile_facts", "granted": False})

    assert response.json()["purposes"]["profile_facts"]["granted"] is False
    assert client.get("/api/memory").json()["facts"] == []
    assert len(client.get("/api/applications").json()["for_me"]) == 1


def test_an_unknown_purpose_is_rejected(client):
    assert client.put("/api/memory/consent", json={"purpose": "everything", "granted": True}).status_code == 422


# What is remembered


def test_remembered_facts_show_their_dates_and_when_they_are_due_again(client, memory):
    grant(memory, "profile_facts")
    remember_fact(memory, "age", 34, confirmed_days_ago=0)
    remember_fact(memory, "is_indian_citizen", True, confirmed_days_ago=0)
    facts = {item["field"]: item for item in client.get("/api/memory").json()["facts"]}
    assert facts["age"]["value"] == 34 and facts["is_indian_citizen"]["value"] is True
    assert facts["age"]["reconfirm_due"] is False
    assert facts["age"]["expires_at"] and facts["age"]["confirmed_at"]


def test_a_fact_past_its_reconfirm_date_is_listed_as_due(client, memory, monkeypatch):
    grant(memory, "profile_facts")
    remember_fact(memory, "age", 34)
    later = datetime.utcnow() + timedelta(days=40)
    monkeypatch.setattr("agents.memory_service.utc_now", lambda: later)
    monkeypatch.setattr("app.memory_api.utc_now", lambda: later)
    [fact] = client.get("/api/memory").json()["facts"]
    assert fact["reconfirm_due"] is True


def test_one_remembered_fact_can_be_forgotten(client, memory):
    grant(memory, "profile_facts")
    remember_fact(memory, "age", 34)
    remember_fact(memory, "is_indian_citizen", True)

    assert client.delete("/api/memory/facts/age").status_code == 200

    assert [f["field"] for f in client.get("/api/memory").json()["facts"]] == ["is_indian_citizen"]
    assert client.delete("/api/memory/facts/age").status_code == 404


def test_forgetting_everything_clears_every_store_of_the_household(client, memory, surfaces):
    grant(memory, "profile_facts")
    grant(memory, "application_references")
    remember_fact(memory)
    remember_application(memory, "APP-1")

    body = client.delete("/api/memory").json()

    assert body["status"] == "success"
    assert "already submitted" in body["note"]
    assert body["surfaces"] == {
        "documents": {"status": "deleted", "count": 2},
        "application_workflows": {"status": "deleted", "count": 2},
        "conversations": {"status": "deleted", "count": 2},
        "memory": {"status": "deleted"},
    }
    assert surfaces.calls == [
        ("documents", "hh1"),
        ("application_workflows", "hh1"),
        ("conversations", "hh1"),
    ]
    assert client.get("/api/memory").json()["facts"] == []
    assert client.get("/api/applications").json() == {"for_me": [], "family": [], "for_others": []}
    consent = client.get("/api/memory/consent").json()["purposes"]
    assert not consent["profile_facts"]["granted"] and not consent["application_references"]["granted"]


def test_the_household_to_forget_comes_from_the_token_only(client, who, surfaces):
    who["household"], who["sub"] = "hh2", "user-2"
    client.delete("/api/memory", params={"household_id": "hh1"}, headers={"X-Household-Id": "hh1"})
    assert {household for _, household in surfaces.calls} == {"hh2"}


def test_a_failed_deletion_is_not_reported_as_success_and_the_rest_still_run(client, memory, surfaces, monkeypatch):
    def fail(scope):
        raise RuntimeError("storage is down")

    monkeypatch.setattr(memory, "forget_household", fail)
    response = client.delete("/api/memory")

    assert response.status_code == 500
    assert "success" not in response.text
    assert "memory" in response.json()["detail"]
    assert [name for name, _ in surfaces.calls] == ["documents", "application_workflows", "conversations"]


def test_a_failed_conversation_deletion_is_reported_while_the_memory_is_cleared(client, memory, surfaces):
    grant(memory, "profile_facts")
    remember_fact(memory)
    surfaces.failing = {"conversations"}

    response = client.delete("/api/memory")

    assert response.status_code == 500
    assert "conversations" in response.json()["detail"]
    assert client.get("/api/memory").json()["facts"] == []


def test_workflows_are_left_for_a_retry_when_their_documents_could_not_be_deleted(client, surfaces):
    surfaces.failing = {"documents"}

    response = client.delete("/api/memory")

    assert response.status_code == 500
    assert "documents" in response.json()["detail"] and "application_workflows" in response.json()["detail"]
    assert ("application_workflows", "hh1") not in surfaces.calls  # they still identify the documents

    surfaces.failing = set()
    retry = client.delete("/api/memory")
    assert retry.status_code == 200
    assert retry.json()["surfaces"]["application_workflows"]["status"] == "deleted"


def test_forgetting_still_clears_the_other_stores_when_remembering_is_unavailable(memory, who, surfaces):
    application = api.create_api(service=surfaces)
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold("hh1", "user-1")
    application.dependency_overrides[optional_memory] = lambda: None

    response = TestClient(application).delete("/api/memory")

    assert response.status_code == 200
    assert response.json()["surfaces"]["memory"] == {"status": "not_applicable"}
    assert [name for name, _ in surfaces.calls] == ["documents", "application_workflows", "conversations"]


def test_another_household_sees_and_deletes_nothing_of_mine(client, memory, who):
    grant(memory, "profile_facts")
    remember_fact(memory)
    who["household"], who["sub"] = "hh2", "user-2"

    assert client.get("/api/memory").json()["facts"] == []
    assert client.delete("/api/memory/facts/age").status_code == 404
    client.delete("/api/memory")

    who["household"], who["sub"] = "hh1", "user-1"
    assert [f["field"] for f in client.get("/api/memory").json()["facts"]] == ["age"]


def test_a_household_id_in_the_request_changes_nothing(client, memory, who):
    grant(memory, "profile_facts")
    remember_fact(memory)
    who["household"], who["sub"] = "hh2", "user-2"
    assert client.get("/api/memory", params={"household_id": "hh1"}).json()["facts"] == []
    assert client.get("/api/memory", headers={"X-Household-Id": "hh1"}).json()["facts"] == []


def test_every_memory_endpoint_needs_a_signed_in_person(memory):
    application = api.create_api(service=object())
    application.dependency_overrides[optional_memory] = lambda: memory
    client = TestClient(application)
    for method, path in [
        ("get", "/api/memory"),
        ("get", "/api/memory/consent"),
        ("delete", "/api/memory"),
        ("get", "/api/applications"),
        ("get", "/api/applications/APP-1/status"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_memory_endpoints_report_when_remembering_is_unavailable(who):
    application = api.create_api(service=object())
    application.dependency_overrides[authenticated_household] = lambda: AuthenticatedHousehold("hh1", "user-1")
    application.dependency_overrides[optional_memory] = lambda: None
    client = TestClient(application)
    for method, path in [("get", "/api/memory"), ("get", "/api/memory/consent"), ("get", "/api/applications")]:
        assert getattr(client, method)(path).status_code == 503, path


# Saved applications


def test_applications_are_grouped_for_me_family_and_other_people(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "APP-1", scheme_id="C01")
    remember_application(memory, "APP-2", subject="other", relation="mother", scheme_id="C02")
    remember_application(memory, "APP-3", subject="other", relation="neighbour", scheme_id="C03")

    body = client.get("/api/applications").json()

    assert [a["application_id"] for a in body["for_me"]] == ["APP-1"]
    [member] = body["family"]
    assert (member["relation"], member["nickname"]) == ("mother", None)
    [family_app] = member["applications"]
    assert (family_app["application_id"], family_app["scheme_id"]) == ("APP-2", "C02")
    [other] = body["for_others"]
    assert (other["application_id"], other["relation"], other["scheme_id"]) == ("APP-3", "neighbour", "C03")
    assert "submitted_by" not in other and "submitted_by" not in family_app


def test_status_is_read_live_from_the_portal_for_my_own_application(client, memory, monkeypatch):
    grant(memory, "application_references")
    remember_application(memory, "APP-1")
    asked = []
    monkeypatch.setattr(
        tools,
        "application_status",
        lambda application_id, household_id: asked.append((application_id, household_id))
        or {"application_id": application_id, "status": "submitted"},
    )

    body = client.get("/api/applications/APP-1/status").json()

    assert (body["status"], body["found_at_portal"], body["scheme_id"]) == ("submitted", True, "C01")
    assert asked == [("APP-1", "hh1")]  # asked on behalf of the token's household


def test_an_application_that_is_not_in_my_list_is_never_looked_up(client, memory, monkeypatch):
    grant(memory, "application_references", household="hh2", sub="user-2")
    remember_application(memory, "SOMEONE-ELSES", household="hh2")
    monkeypatch.setattr(
        tools, "application_status", lambda application_id, household_id: pytest.fail("must not reach the portal")
    )

    assert client.get("/api/applications/SOMEONE-ELSES/status").status_code == 404
    assert client.get("/api/applications/NOT-REAL/status").status_code == 404


def test_an_application_the_portal_no_longer_has_is_reported_not_hidden(client, memory, monkeypatch):
    grant(memory, "application_references")
    remember_application(memory, "APP-1")

    def gone(application_id, household_id):
        raise tools.ToolCallError("mock-portal", "get_application_status", "application_not_found", "missing")

    monkeypatch.setattr(tools, "application_status", gone)
    body = client.get("/api/applications/APP-1/status").json()
    assert body["found_at_portal"] is False and body["status"] is None


def test_a_portal_failure_is_a_503_not_a_made_up_status(client, memory, monkeypatch):
    grant(memory, "application_references")
    remember_application(memory, "APP-1")

    def down(application_id, household_id):
        raise tools.ToolCallError("mock-portal", "get_application_status", "transport_error", "down")

    monkeypatch.setattr(tools, "application_status", down)
    assert client.get("/api/applications/APP-1/status").status_code == 503


def test_an_application_can_be_removed_from_the_list(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "APP-1")
    assert client.delete("/api/applications/APP-1").status_code == 200
    assert client.get("/api/applications").json() == {"for_me": [], "family": [], "for_others": []}
    assert client.delete("/api/applications/APP-1").status_code == 404


def test_removing_another_households_application_finds_nothing(client, memory, who):
    grant(memory, "application_references")
    remember_application(memory, "APP-1")
    who["household"], who["sub"] = "hh2", "user-2"
    assert client.delete("/api/applications/APP-1").status_code == 404
    who["household"], who["sub"] = "hh1", "user-1"
    assert len(client.get("/api/applications").json()["for_me"]) == 1


# The workflow service and the legacy submission path


def test_the_run_config_carries_the_scope_only_when_memory_is_on(memory):
    with_memory = api.AgentWorkflowService(memory=memory)._config("t", scope())["configurable"]
    assert with_memory["thread_id"] == "t"
    assert (with_memory["memory_actor_id"], with_memory["memory_household_id"], with_memory["memory_role"]) == (
        "user-1",
        "hh1",
        "citizen",
    )
    without_memory = api.AgentWorkflowService()._config("t", scope())["configurable"]
    assert without_memory == {"thread_id": "t"}
    assert api.AgentWorkflowService(memory=memory)._config("t")["configurable"] == {"thread_id": "t"}


class FakeDemo:
    def __init__(self, subject="self", relation=None):
        self.subject = (subject, relation)

    def thread_subject(self, thread_id):
        return self.subject


SUBMITTED = {
    "application": {"scheme_id": "C01"},
    "submission": {"application_id": "APP-9", "status": "submitted (mock)"},
}


def run_events(memory, demo, monkeypatch, events=None):
    monkeypatch.setattr(memory_runtime, "get_memory_service", lambda: memory)
    events = events or [("progress", {"label": "x"}), ("result", dict(SUBMITTED))]
    return list(api._remembering_submission(demo, "t1", AuthenticatedHousehold("hh1", "user-1"), iter(events)))


def test_a_submission_through_the_application_flow_is_remembered(memory, monkeypatch):
    grant(memory, "application_references")
    events = run_events(memory, FakeDemo("other", "mother"), monkeypatch)

    assert events[0] == ("progress", {"label": "x"})
    assert events[1][1]["reference_saved"] is True
    [reference] = memory.read_application_references(scope())
    assert (reference.application_id, reference.subject, reference.relation) == ("APP-9", "other", "mother")


def test_without_consent_the_submission_still_goes_through_but_is_not_remembered(memory, monkeypatch):
    events = run_events(memory, FakeDemo(), monkeypatch)
    assert events[1][1]["reference_saved"] is False
    assert events[1][1]["submission"]["application_id"] == "APP-9"
    assert memory.read_application_references(scope()) == []


def test_events_without_a_submission_pass_through_untouched_and_open_no_store(monkeypatch):
    monkeypatch.setattr(memory_runtime, "get_memory_service", lambda: pytest.fail("the store must not be opened"))
    events = [("progress", {"label": "x"}), ("result", {"application": {}, "submission": None})]
    out = list(api._remembering_submission(FakeDemo(), "t1", AuthenticatedHousehold("hh1", "user-1"), iter(events)))
    assert out == events


def test_with_memory_unavailable_the_result_is_unchanged(monkeypatch):
    monkeypatch.setattr(memory_runtime, "get_memory_service", lambda: None)
    events = [("result", dict(SUBMITTED))]
    out = list(api._remembering_submission(FakeDemo(), "t1", AuthenticatedHousehold("hh1", "user-1"), iter(events)))
    assert out == events


def test_a_failure_remembering_the_submission_never_changes_the_result(memory, monkeypatch):
    grant(memory, "application_references")

    def broken(scope, reference):
        raise RuntimeError("down")

    monkeypatch.setattr(memory, "save_application_reference", broken)
    events = run_events(memory, FakeDemo(), monkeypatch)
    assert events[1][1]["reference_saved"] is False
    assert events[1][1]["submission"]["application_id"] == "APP-9"


def test_the_analysis_request_says_whose_application_it_is():
    default = api.AnalysisRequest(citizen={"age": 30})
    assert (default.subject, default.relation) == ("self", None)
    other = api.AnalysisRequest(citizen={"age": 30}, subject="other", relation="mother")
    assert (other.subject, other.relation) == ("other", "mother")
    with pytest.raises(ValueError):
        api.AnalysisRequest(citizen={}, subject="nobody")
    with pytest.raises(ValueError):
        api.AnalysisRequest(citizen={}, relation="x" * 41)


def test_the_demo_service_remembers_whose_application_a_thread_is_for():
    from app.business_logic import DemoService

    service = DemoService()
    assert service.thread_subject("unknown") == ("self", None)
    service._thread_subjects["t-1"] = ("other", "mother")
    assert service.thread_subject("t-1") == ("other", "mother")


# Operators


OPERATOR = {"household": "operator:op-1", "sub": "op-1", "role": "operator"}


@pytest.fixture
def operator(who):
    who.update(OPERATOR)
    return who


def operator_scope(sub="op-1"):
    return MemoryScope(actor_id=sub, household_id=f"operator:{sub}", actor_role="operator")


def operator_remembers(client, memory, application_id, sub="op-1", relation="neighbour"):
    """Save an application the way an approved submission does, with the person helped agreeing."""
    saved = save_application_reference(
        MemoryContext(memory, operator_scope(sub)), "C01", application_id, "other", relation, citizen_agreed=True
    )
    assert saved is True


def test_a_citizen_is_told_their_role_and_sees_both_choices(client):
    body = client.get("/api/memory/consent").json()
    assert body["role"] == "citizen"
    assert set(body["purposes"]) == {"profile_facts", "application_references"}


def test_an_operator_has_no_standing_consent_to_set(client, operator):
    body = client.get("/api/memory/consent").json()
    assert body["role"] == "operator"
    assert body["purposes"] == {}


@pytest.mark.parametrize("purpose", ["profile_facts", "application_references"])
def test_an_operator_cannot_set_a_standing_consent(client, operator, memory, purpose):
    response = client.put("/api/memory/consent", json={"purpose": purpose, "granted": True})

    assert response.status_code == 403
    assert "each application" in response.json()["detail"]
    assert memory.active_consent(operator_scope(), purpose) is None


def test_an_operators_agreement_is_recorded_per_application_in_person_and_by_whom(client, operator, memory):
    operator_remembers(client, memory, "OP-APP")

    [reference] = memory.read_application_references(operator_scope())
    consent = memory.consents[reference.consent_reference]
    assert reference.consent_reference.startswith("in-person-")
    assert (consent.obtained_via, consent.recorded_by) == ("in_person", "op-1")


def test_removing_an_operators_entry_withdraws_the_agreement_recorded_for_it(client, operator, memory):
    operator_remembers(client, memory, "OP-1")
    operator_remembers(client, memory, "OP-2")
    keep = next(r for r in memory.read_application_references(operator_scope()) if r.application_id == "OP-2")

    assert client.delete("/api/applications/OP-1").status_code == 200

    assert [r.application_id for r in memory.read_application_references(operator_scope())] == ["OP-2"]
    assert set(memory.consents) == {keep.consent_reference}


def test_a_citizens_agreement_is_self_service(client, memory):
    client.put("/api/memory/consent", json={"purpose": "profile_facts", "granted": True})
    consent = memory.active_consent(scope(), "profile_facts")
    assert (consent.obtained_via, consent.recorded_by) == ("self_service", None)


def test_an_operator_cannot_delete_a_households_details(client, operator, memory):
    grant(memory, "profile_facts", household="hh1")
    remember_fact(memory, household="hh1")

    assert client.delete("/api/memory/facts/age").status_code == 403
    assert len(memory.list_facts(scope("hh1"))) == 1


def test_an_operator_has_no_household_details_to_see(client, operator, memory):
    grant(memory, "profile_facts", household="hh1")
    remember_fact(memory, household="hh1")
    assert client.get("/api/memory").json()["facts"] == []


def test_an_operator_sees_only_the_applications_they_submitted(client, operator, memory):
    grant(memory, "application_references", household="hh1")
    remember_application(memory, "CITIZEN-APP", household="hh1")
    operator_remembers(client, memory, "OP-APP")

    body = client.get("/api/applications").json()

    assert [a["application_id"] for a in body["for_others"]] == ["OP-APP"]
    assert body["for_me"] == []


def test_one_operators_list_is_invisible_to_another_operator(client, operator, memory, who):
    operator_remembers(client, memory, "OP-APP")
    who.update({"household": "operator:op-2", "sub": "op-2"})
    assert client.get("/api/applications").json() == {"for_me": [], "family": [], "for_others": []}
    assert client.get("/api/applications/OP-APP/status").status_code == 404


def test_an_operators_status_lookup_is_made_under_their_own_account(client, operator, memory, monkeypatch):
    operator_remembers(client, memory, "OP-APP")
    asked = []
    monkeypatch.setattr(
        tools,
        "application_status",
        lambda application_id, household_id: asked.append((application_id, household_id))
        or {"application_id": application_id, "status": "submitted"},
    )

    assert client.get("/api/applications/OP-APP/status").json()["status"] == "submitted"
    assert asked == [("OP-APP", "operator:op-1")]


def test_an_operator_forgetting_clears_only_their_own_list(client, operator, memory, surfaces):
    grant(memory, "profile_facts", household="hh1")
    grant(memory, "application_references", household="hh1")
    remember_fact(memory, household="hh1")
    remember_application(memory, "CITIZEN-APP", household="hh1")
    operator_remembers(client, memory, "OP-APP")
    operator_remembers(client, memory, "OP-APP-2")

    assert client.delete("/api/memory").json()["status"] == "success"

    assert memory.read_application_references(operator_scope()) == []
    assert memory.active_consent(operator_scope(), "application_references") is None
    assert not any(ref.startswith("in-person-") for ref in memory.consents)
    assert len(memory.list_facts(scope("hh1"))) == 1
    assert [r.application_id for r in memory.read_application_references(scope("hh1"))] == ["CITIZEN-APP"]
    assert ("conversations", "operator:op-1") in surfaces.calls


def test_forgetting_also_clears_an_operators_earlier_standing_consent(client, operator, memory):
    now = datetime.utcnow()
    memory.record_consent(
        operator_scope(),
        MemoryConsent(
            purpose="application_references",
            granted=True,
            notice_version="1",
            decided_at=now,
            expires_at=now + timedelta(days=60),
            consent_reference="old-blanket",
            obtained_via="in_person",
            recorded_by="op-1",
        ),
    )
    operator_remembers(client, memory, "OP-APP")

    assert client.delete("/api/memory").json()["status"] == "success"
    assert memory.consents == {} and memory.read_application_references(operator_scope()) == []


def test_a_citizen_forgetting_leaves_an_operators_list_alone(client, memory, who, surfaces):
    who.update(OPERATOR)
    operator_remembers(client, memory, "OP-APP")
    who.update({"household": "hh1", "sub": "user-1", "role": "citizen"})
    grant(memory, "profile_facts")
    remember_fact(memory)

    assert client.delete("/api/memory").json()["status"] == "success"

    assert client.get("/api/memory").json()["facts"] == []
    assert [r.application_id for r in memory.read_application_references(operator_scope())] == ["OP-APP"]


# Family members


def family_apps(client):
    return {m["relation"]: m for m in client.get("/api/applications").json()["family"]}


def test_a_family_member_is_created_by_the_first_application_and_listed_with_it(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "A1", subject="other", relation="mother")
    remember_application(memory, "A2", subject="other", relation="mother", scheme_id="C02")

    members = family_apps(client)

    assert set(members) == {"mother"}
    assert {a["application_id"] for a in members["mother"]["applications"]} == {"A1", "A2"}
    assert members["mother"]["nickname"] is None


def test_a_family_member_can_be_given_a_nickname_and_it_is_listed(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "A1", subject="other", relation="mother")

    response = client.patch("/api/family/mother", json={"nickname": "Amma"})

    assert response.status_code == 200 and response.json()["relation"] == "mother"
    assert family_apps(client)["mother"]["nickname"] == "Amma"
    client.patch("/api/family/mother", json={"nickname": ""})
    assert family_apps(client)["mother"]["nickname"] is None


def test_a_relation_alias_reaches_the_same_member(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "A1", subject="other", relation="mother")
    assert client.patch("/api/family/mom", json={"nickname": "Amma"}).json()["relation"] == "mother"


def test_a_nickname_with_digits_is_refused_and_nothing_changes(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "A1", subject="other", relation="mother")
    assert client.patch("/api/family/mother", json={"nickname": "Amma 9876543210"}).status_code == 422
    assert family_apps(client)["mother"]["nickname"] is None


def test_someone_who_is_not_family_or_not_saved_is_not_found(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "A1", subject="other", relation="neighbour")
    for relation in ("neighbour", "father", "nobody"):
        assert client.patch(f"/api/family/{relation}", json={"nickname": "X"}).status_code == 404
        assert client.delete(f"/api/family/{relation}").status_code == 404
    assert len(client.get("/api/applications").json()["for_others"]) == 1


def test_removing_a_family_member_removes_their_saved_applications_only(client, memory):
    grant(memory, "application_references")
    remember_application(memory, "A1", subject="other", relation="mother")
    remember_application(memory, "A2", subject="other", relation="mother", scheme_id="C02")
    remember_application(memory, "A3", subject="other", relation="son")
    remember_application(memory, "A4")

    body = client.delete("/api/family/mother").json()

    assert body["applications_removed"] == 2
    listed = client.get("/api/applications").json()
    assert [m["relation"] for m in listed["family"]] == ["son"]
    assert [a["application_id"] for a in listed["for_me"]] == ["A4"]
    assert client.delete("/api/family/mother").status_code == 404


def test_another_household_cannot_rename_or_remove_my_family_member(client, memory, who):
    grant(memory, "application_references")
    remember_application(memory, "A1", subject="other", relation="mother")
    who.update({"household": "hh2", "sub": "user-2"})

    assert client.patch("/api/family/mother", json={"nickname": "Amma"}).status_code == 404
    assert client.delete("/api/family/mother").status_code == 404
    assert client.get("/api/applications").json()["family"] == []

    who.update({"household": "hh1", "sub": "user-1"})
    assert len(family_apps(client)["mother"]["applications"]) == 1


def test_family_endpoints_need_a_signed_in_person(memory):
    application = api.create_api(service=object())
    application.dependency_overrides[optional_memory] = lambda: memory
    anonymous = TestClient(application)
    assert anonymous.patch("/api/family/mother", json={"nickname": "X"}).status_code == 401
    assert anonymous.delete("/api/family/mother").status_code == 401


def test_an_operator_has_family_members_under_their_own_account(client, operator, memory):
    operator_remembers(client, memory, "OP-APP")  # a neighbour, who is not family
    operator_remembers(client, memory, "OP-MOTHER", relation="mother")

    assert set(family_apps(client)) == {"mother"}
    assert client.patch("/api/family/mother", json={"nickname": "Client"}).status_code == 200
    assert client.delete("/api/family/mother").json()["applications_removed"] == 1
    assert [a["application_id"] for a in client.get("/api/applications").json()["for_others"]] == ["OP-APP"]
    assert len(memory.consents) == 1  # the removed member's agreement went with them


# An operator's per-application agreement through the application flow


OPERATOR_PRINCIPAL = AuthenticatedHousehold("operator:op-1", "op-1", "operator")


def run_operator_events(memory, monkeypatch, citizen_agreed, principal=OPERATOR_PRINCIPAL):
    monkeypatch.setattr(memory_runtime, "get_memory_service", lambda: memory)
    events = [("result", dict(SUBMITTED))]
    return list(
        api._remembering_submission(
            FakeDemo("other", "mother"), "t1", principal, iter(events), citizen_agreed=citizen_agreed
        )
    )


def test_an_operators_submission_is_remembered_only_with_the_persons_agreement(memory, monkeypatch):
    events = run_operator_events(memory, monkeypatch, citizen_agreed=True)

    assert events[0][1]["reference_saved"] is True
    [reference] = memory.read_application_references(operator_scope())
    assert (reference.application_id, reference.relation) == ("APP-9", "mother")
    assert memory.consents[reference.consent_reference].obtained_via == "in_person"


def test_without_the_agreement_an_operators_submission_goes_through_but_nothing_is_kept(memory, monkeypatch):
    events = run_operator_events(memory, monkeypatch, citizen_agreed=False)

    assert events[0][1]["reference_saved"] is False
    assert events[0][1]["submission"]["application_id"] == "APP-9"
    assert memory.read_application_references(operator_scope()) == [] and memory.consents == {}


def test_the_decision_requests_carry_the_choice_and_default_to_no():
    assert api.DecisionRequest(action="approve", payload_hash="h").citizen_agreed is False
    assert api.ApprovalDecisionRequest(action="approve", payload_hash="h").citizen_agreed is False
    assert api.DecisionRequest(action="approve", payload_hash="h", citizen_agreed=True).citizen_agreed is True


def test_the_agent_service_passes_the_choice_into_the_resumed_decision(memory):
    seen = {}

    class Graph:
        checkpointer = None

        def get_state(self, config):
            from types import SimpleNamespace

            return SimpleNamespace(tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value={"kind": "approval"})])])

        def invoke(self, command, config):
            seen["decision"] = command.resume
            return {"status": "submitted", "response": "done"}

    service = api.AgentWorkflowService(memory=memory)
    service._agent_graph = Graph()
    service.create_thread("operator:op-1", "t1")

    service.submit_decision("t1", "operator:op-1", "approve", "h", {}, citizen_agreed=True)

    assert seen["decision"] == {"action": "approve", "payload_hash": "h", "changes": {}, "citizen_agreed": True}

