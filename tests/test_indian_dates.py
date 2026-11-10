"""Dates are stored as YYYY-MM-DD for the rule engine and shown and typed as DD/MM/YYYY."""
import pytest
from streamlit.testing.v1 import AppTest

from agents.intake import profile_model
from app import app_new
from graph.agent_workflow import _fits


@pytest.mark.parametrize("typed, stored", [
    ("05/03/1962", "1962-03-05"),   # day first: 5 March, not 3 May
    (" 31/12/2000 ", "2000-12-31"),
    ("31/02/2000", None),           # not a real date
    ("1962-03-05", None),           # only the Indian order is accepted in the form
    ("", None),
])
def test_a_typed_indian_date_is_stored_as_iso(typed, stored):
    assert app_new._iso_date(typed) == stored


def test_a_stored_date_is_shown_day_first():
    assert app_new._indian_date("1962-03-05") == "05/03/1962"
    assert app_new._indian_date("not a date") == "not a date"


def confirmation_with_a_date():
    import streamlit as st
    from app import app_new

    st.session_state.setdefault("chat_session_id", "thread-1")
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault(
        "chat_confirmation", {"facts": {"date_of_birth": "1962-03-05"}, "payload_hash": "h"}
    )
    app_new._render_fact_confirmation("http://api")


def test_the_confirmation_table_shows_the_date_day_first():
    app = AppTest.from_function(confirmation_with_a_date).run()
    assert "05/03/1962" in str(app.table[0].value)


def test_an_edited_date_must_be_iso():
    assert _fits("date", "1962-03-05")
    assert not _fits("date", "05/03/1962")
    assert not _fits("date", 1962)


def test_the_extractor_is_told_dates_are_day_first():
    model = profile_model({"date_of_birth": {"type": "date", "known_values": []}})
    description = model.model_json_schema()["properties"]["date_of_birth"]["description"]
    assert "DD/MM/YYYY" in description and "1962-03-05" in description
