"""Tests run as in CI: a developer's .env never reaches them."""
import os

from agents.supervisor import UnifiedRouter
from app import auth


def test_no_api_key_or_auth0_setting_reaches_a_test():
    assert os.getenv("OPENROUTER_API_KEY") is None and os.getenv("AUTH0_DOMAIN") is None
    assert not UnifiedRouter().api_available  # the router uses its keyword rules, not a live model


def test_load_dotenv_is_a_no_op_in_tests():
    auth.load_dotenv()
    assert os.getenv("AUTH0_DOMAIN") is None
