"""The price table: US dollars per million tokens for each model, used when the provider reports no cost.

The file holds no real prices by default. A model that is missing, or has a malformed entry, is
treated as unpriced, and its calls are counted separately instead of being costed at zero.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PRICES_FILE_ENV = "MODEL_PRICES_FILE"
DEFAULT_FILE = Path(__file__).with_name("model_prices.json")
PER_TOKENS = 1_000_000


@dataclass(frozen=True)
class Price:
    input: float  # US dollars per million input tokens
    output: float  # US dollars per million output tokens

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input + output_tokens * self.output) / PER_TOKENS


def number(value: Any) -> float | None:
    """A finite, non-negative number, or None. A bool, a string or a negative is not a price or a count."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


_dotenv_loaded = False


def prices_path() -> Path:
    global _dotenv_loaded
    if not _dotenv_loaded:  # reading .env on every priced call would cost milliseconds each time
        load_dotenv()
        _dotenv_loaded = True
    configured = os.environ.get(PRICES_FILE_ENV, "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_FILE


_cache: tuple[Path, float, dict[str, Price]] | None = None


def load_prices() -> dict[str, Price]:
    """The price table, re-read when the file changes. A missing or unreadable file is an empty table."""
    global _cache
    path = prices_path()
    try:
        modified = path.stat().st_mtime
    except OSError:
        _cache = None
        return {}
    if _cache is not None and _cache[0] == path and _cache[1] == modified:
        return _cache[2]
    table: dict[str, Price] = {}
    try:
        models = json.loads(path.read_text(encoding="utf-8")).get("models", {})
    except (OSError, ValueError, AttributeError):
        logger.warning("The model price file could not be read; model calls will be counted as unpriced.")
        models = {}
    for name, entry in (models.items() if isinstance(models, dict) else []):
        entry = entry if isinstance(entry, dict) else {}
        input_price, output_price = number(entry.get("input")), number(entry.get("output"))
        if input_price is None or output_price is None:
            logger.warning("A model price entry is malformed and was ignored.")
            continue
        table[str(name)] = Price(input_price, output_price)
    _cache = (path, modified, table)
    return table


def price_for(model: str) -> Price | None:
    return load_prices().get(model)
