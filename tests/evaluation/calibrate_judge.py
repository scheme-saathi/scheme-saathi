#!/usr/bin/env python3
"""Calibrate the offline claim judge against human-labelled synthetic messages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.callbacks import get_usage_metadata_callback  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from observability.pricing import price_for  # noqa: E402
from tests.evaluation.claim_judge import (  # noqa: E402
    PROMPT, ClaimJudge, ReviewSet, calibrate, judge_messages, read_calibration, validate_models,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--labels", type=Path, help="human-labelled synthetic JSON file")
    source.add_argument("--classify", type=Path, help="reviewed synthetic messages, no labels required")
    parser.add_argument("--confirm-synthetic", action="store_true",
                        help="confirm all messages were reviewed and contain no sensitive data")
    parser.add_argument("--agent-model", action="append", required=True,
                        help="provider/model used by an evaluated agent; repeat for each model")
    parser.add_argument("--output", type=Path, required=True, help="new report file; must not already exist")
    args = parser.parse_args(argv)
    if args.classify and not args.confirm_synthetic:
        parser.error("--classify requires --confirm-synthetic after reviewing the messages")
    load_dotenv()
    judge_model = os.getenv("JUDGE_MODEL", "").strip()
    validate_models(judge_model, args.agent_model)
    if args.labels:
        data, digest = read_calibration(args.labels)
    else:
        content = args.classify.read_bytes()
        data, digest = ReviewSet.model_validate_json(content), hashlib.sha256(content).hexdigest()
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY for the judge.")
    if args.output.exists():
        raise FileExistsError(f"Report already exists: {args.output}")
    model = ChatOpenAI(
        model=judge_model,
        api_key=key,
        base_url=os.getenv("OPENROUTER_BASE_URL", "").strip() or "https://openrouter.ai/api/v1",
        temperature=0,
        timeout=30,
        max_retries=2,
    )
    with get_usage_metadata_callback() as usage:
        judge = ClaimJudge(model)
        if args.labels:
            result = calibrate(data.items, judge.judge)
        else:
            result = judge_messages(data.items, judge.judge)
    tokens = {name: dict(value) for name, value in usage.usage_metadata.items()}
    total = 0.0
    for model_name, counts in tokens.items():
        price = price_for(model_name)
        input_count, output_count = counts.get("input_tokens"), counts.get("output_tokens")
        if (price is None or not isinstance(input_count, int) or isinstance(input_count, bool)
                or not isinstance(output_count, int) or isinstance(output_count, bool)
                or input_count < 0 or output_count < 0):
            total = None
            break
        total += price.cost(input_count, output_count)
    result.update({
        "judge_model": judge_model,
        "agent_models": args.agent_model,
        "labels_sha256": digest,
        "mode": "calibration" if args.labels else "classification",
        "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
        "tokens_by_model": tokens,
        "estimated_cost_usd": round(total, 8) if tokens and total is not None else None,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)
        file.write("\n")
    print(f"Judge report written to {args.output}; {result['errors']} failed item(s).")
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
