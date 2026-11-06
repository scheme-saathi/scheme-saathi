import json

import pytest

from graph import tools


def test_tool_budget_stops_calls_before_reaching_the_mcp_client(monkeypatch):
    calls = []

    async def expected_call(server, tool, arguments):
        calls.append((server, tool))
        return {"data": ["SYNTH-PENSION-001"]}

    monkeypatch.setattr(tools, "_call", expected_call)

    with tools.tool_call_budget(limit=1):
        assert tools.call_tool(tools.RULE_ENGINE, "list_rule_schemes") == ["SYNTH-PENSION-001"]
        with pytest.raises(tools.ToolCallError) as error:
            tools.call_tool(tools.RULE_ENGINE, "list_rule_schemes")

    assert error.value.code == "budget_exceeded"
    assert calls == [(tools.RULE_ENGINE, "list_rule_schemes")]


def test_compiled_graph_invocation_gets_a_fresh_tool_budget(monkeypatch):
    class FakeGraph:
        def invoke(self, *_args, **_kwargs):
            tools.call_tool(tools.RULE_ENGINE, "list_rule_schemes")
            return tools.call_tool(tools.RULE_ENGINE, "list_rule_schemes")

    calls = []

    async def expected_call(server, tool, arguments):
        calls.append((server, tool))
        return {"data": []}

    monkeypatch.setattr(tools, "_call", expected_call)
    monkeypatch.setattr(tools, "DEFAULT_TOOL_CALL_BUDGET", 1)

    graph = tools.budget_graph(FakeGraph())
    with pytest.raises(tools.ToolCallError, match="exceeded its limit"):
        graph.invoke({})
    with pytest.raises(tools.ToolCallError, match="exceeded its limit"):
        graph.invoke({})

    assert calls == [(tools.RULE_ENGINE, "list_rule_schemes")] * 2


def test_tool_audit_log_excludes_arguments_results_and_error_text(monkeypatch, caplog):
    private_marker = "1234 5678 9012"

    async def failing_call(server, tool, arguments):
        raise tools.ToolCallError(server, tool, "tool_error", private_marker)

    monkeypatch.setattr(tools, "_call", failing_call)

    with caplog.at_level("INFO", logger="graph.tools"):
        with pytest.raises(tools.ToolCallError):
            tools.call_tool(
                tools.RULE_ENGINE,
                "list_rule_schemes",
                household_note=private_marker,
            )

    assert private_marker not in caplog.text
    records = [record for record in caplog.records if record.message.startswith("mcp_tool_call ")]
    assert len(records) == 1
    audit = json.loads(records[0].message.removeprefix("mcp_tool_call "))
    duration_ms = audit.pop("duration_ms")
    assert isinstance(duration_ms, int) and duration_ms >= 0
    assert audit == {
        "actor": "unknown",
        "server": tools.RULE_ENGINE,
        "tool": "list_rule_schemes",
        "outcome": "error",
        "error_code": "tool_error",
    }


def test_call_tool_denies_unregistered_server_before_calling(monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail("unregistered server reached the MCP client")

    monkeypatch.setattr(tools, "_call", unexpected_call)

    with pytest.raises(tools.ToolCallError) as error:
        tools.call_tool("unknown-server", "anything")

    assert error.value.code == "unknown_server"


def test_call_tool_denies_unlisted_tool_before_calling(monkeypatch):
    def unexpected_call(*args, **kwargs):
        pytest.fail("unlisted tool reached the MCP client")

    monkeypatch.setattr(tools, "_call", unexpected_call)

    with pytest.raises(tools.ToolCallError) as error:
        tools.call_tool(tools.MOCK_PORTAL, "new_unclassified_write")

    assert error.value.code == "forbidden"
    assert "not an allow-listed tool" in str(error.value)


def test_allowlisted_read_tool_requires_no_actor(monkeypatch):
    async def expected_call(server, tool, arguments):
        assert (server, tool) == (tools.RULE_ENGINE, "list_rule_schemes")
        return {"data": ["SYNTH-PENSION-001"]}

    monkeypatch.setattr(tools, "_call", expected_call)

    assert tools.call_tool(tools.RULE_ENGINE, "list_rule_schemes") == ["SYNTH-PENSION-001"]
