import pytest

from graph import tools


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
