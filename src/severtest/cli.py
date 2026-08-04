from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import load_fruit_catalog, load_milestone_config
from .logging import configure_logging
from .planner import plan_exact_score, target_before_node


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SunnyIsland server test condition builder")
    parser.add_argument("--verbose", action="store_true", help="enable debug logs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="generate a milestone preparation plan")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--fruits", type=Path, required=True)
    plan.add_argument("--round", type=int, default=1)
    plan.add_argument("--initial-score", type=int, default=0)
    target = plan.add_mutually_exclusive_group(required=True)
    target.add_argument("--target-score", type=int)
    target.add_argument("--before-node", type=int)
    plan.add_argument("--remaining", type=int, default=1, help="score remaining before selected node")
    plan.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    logger = logging.getLogger("severtest.cli")

    try:
        config, digest = load_milestone_config(args.config)
        catalog = load_fruit_catalog(args.fruits)
        target_score = args.target_score
        if target_score is None:
            target_score = target_before_node(config, args.round, args.before_node, args.remaining)
        plan = plan_exact_score(
            config,
            catalog,
            round_number=args.round,
            initial_score=args.initial_score,
            target_score=target_score,
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.error("plan generation failed", extra={"fields": {"error": str(exc)}})
        return 2

    payload = plan.as_dict()
    payload["config_sha256"] = digest
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        logger.info("plan written", extra={"fields": {"path": str(args.output), "score": plan.planned_score}})
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
