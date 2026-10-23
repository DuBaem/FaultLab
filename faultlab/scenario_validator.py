"""Validate FaultLab scenario files without executing privileged commands.

This Report 1 prototype mirrors the constraints in
``scenarios/scenario.schema.json`` and adds cross-field safety checks. It does
not apply network or process faults.

AI-assistance disclosure: the initial scaffold was generated with OpenAI Codex
on October 4, 2026. Student review, modification, testing, and attribution are
required before this code is claimed as a course contribution.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "1.0"
ALLOWED_SERVICES = frozenset({"server"})
ALLOWED_FAULT_TYPES = frozenset(
    {"latency", "packet_loss", "disconnect", "process_failure"}
)
SCENARIO_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
ACTION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")

TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "scenario_id",
        "description",
        "targets",
        "actions",
        "expected_outcomes",
        "safety",
    }
)
TARGET_FIELDS = frozenset({"name", "service"})
ACTION_FIELDS = frozenset(
    {
        "id",
        "type",
        "target",
        "start_after_seconds",
        "duration_seconds",
        "parameters",
    }
)
SAFETY_FIELDS = frozenset(
    {"scope", "cleanup_required", "max_total_duration_seconds"}
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One actionable validation problem with its scenario path."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class ScenarioValidationError(ValueError):
    """Raised when a scenario contains one or more validation issues."""

    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        message = "Scenario validation failed:\n" + "\n".join(
            f"- {issue}" for issue in self.issues
        )
        super().__init__(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _unknown_fields(
    value: Mapping[str, Any], allowed: frozenset[str], path: str
) -> list[ValidationIssue]:
    return [
        ValidationIssue(f"{path}.{name}", "field is not allowed")
        for name in sorted(set(value) - allowed)
    ]


def _require_text(
    value: Mapping[str, Any], field: str, path: str, issues: list[ValidationIssue]
) -> str | None:
    result = value.get(field)
    if not isinstance(result, str) or not result.strip():
        issues.append(ValidationIssue(f"{path}.{field}", "must be a non-empty string"))
        return None
    return result


def _bounded_number(
    value: Mapping[str, Any],
    field: str,
    path: str,
    minimum: float,
    maximum: float,
    issues: list[ValidationIssue],
    *,
    required: bool = True,
) -> float | None:
    if field not in value and not required:
        return None
    result = value.get(field)
    if not _is_number(result):
        issues.append(
            ValidationIssue(
                f"{path}.{field}",
                f"must be a number between {minimum:g} and {maximum:g}",
            )
        )
        return None
    number = float(result)
    if not minimum <= number <= maximum:
        issues.append(
            ValidationIssue(
                f"{path}.{field}",
                f"must be between {minimum:g} and {maximum:g}",
            )
        )
        return None
    return number


def _validate_parameters(
    action_type: str,
    parameters: Any,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(parameters, Mapping):
        issues.append(ValidationIssue(path, "must be an object"))
        return

    if action_type == "latency":
        allowed = frozenset({"latency_ms", "jitter_ms"})
        issues.extend(_unknown_fields(parameters, allowed, path))
        _bounded_number(parameters, "latency_ms", path, 1, 5000, issues)
        _bounded_number(
            parameters, "jitter_ms", path, 0, 1000, issues, required=False
        )
    elif action_type == "packet_loss":
        allowed = frozenset({"loss_percent"})
        issues.extend(_unknown_fields(parameters, allowed, path))
        _bounded_number(parameters, "loss_percent", path, 0.1, 100, issues)
    elif action_type == "disconnect":
        allowed = frozenset({"direction"})
        issues.extend(_unknown_fields(parameters, allowed, path))
        direction = parameters.get("direction")
        if direction != "both":
            issues.append(
                ValidationIssue(
                    f"{path}.direction",
                    'must equal "both" in FaultLab scenario version 1.0',
                )
            )
    elif action_type == "process_failure":
        allowed = frozenset({"signal", "restart_after_seconds"})
        issues.extend(_unknown_fields(parameters, allowed, path))
        signal = parameters.get("signal")
        if signal not in {"SIGTERM", "SIGKILL"}:
            issues.append(
                ValidationIssue(
                    f"{path}.signal", "must be one of: SIGTERM, SIGKILL"
                )
            )
        _bounded_number(
            parameters,
            "restart_after_seconds",
            path,
            0,
            60,
            issues,
            required=False,
        )


def validate_scenario(document: Any) -> list[ValidationIssue]:
    """Return all validation issues found in a parsed scenario document."""

    issues: list[ValidationIssue] = []
    if not isinstance(document, Mapping):
        return [ValidationIssue("$", "scenario must be a JSON object")]

    issues.extend(_unknown_fields(document, TOP_LEVEL_FIELDS, "$"))
    required_fields = TOP_LEVEL_FIELDS
    for field in sorted(required_fields - set(document)):
        issues.append(ValidationIssue(f"$.{field}", "field is required"))

    if document.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                "$.schema_version", f'must equal supported version "{SCHEMA_VERSION}"'
            )
        )

    scenario_id = _require_text(document, "scenario_id", "$", issues)
    if scenario_id and not SCENARIO_ID_PATTERN.fullmatch(scenario_id):
        issues.append(
            ValidationIssue(
                "$.scenario_id",
                "must be 3-64 lowercase letters, numbers, underscores, or hyphens",
            )
        )

    description = _require_text(document, "description", "$", issues)
    if description and len(description) > 240:
        issues.append(ValidationIssue("$.description", "must be 240 characters or fewer"))

    declared_targets: set[str] = set()
    targets = document.get("targets")
    if not isinstance(targets, list) or not targets:
        issues.append(ValidationIssue("$.targets", "must be a non-empty array"))
    else:
        for index, target in enumerate(targets):
            path = f"$.targets[{index}]"
            if not isinstance(target, Mapping):
                issues.append(ValidationIssue(path, "must be an object"))
                continue
            issues.extend(_unknown_fields(target, TARGET_FIELDS, path))
            name = _require_text(target, "name", path, issues)
            service = _require_text(target, "service", path, issues)
            if name:
                if name in declared_targets:
                    issues.append(ValidationIssue(f"{path}.name", "must be unique"))
                declared_targets.add(name)
            if service and service not in ALLOWED_SERVICES:
                issues.append(
                    ValidationIssue(
                        f"{path}.service",
                        "must be the approved FaultLab 1.0 fault target: server",
                    )
                )

    safety = document.get("safety")
    max_total_duration = 300.0
    if not isinstance(safety, Mapping):
        issues.append(ValidationIssue("$.safety", "must be an object"))
    else:
        issues.extend(_unknown_fields(safety, SAFETY_FIELDS, "$.safety"))
        if safety.get("scope") != "local_docker_only":
            issues.append(
                ValidationIssue(
                    "$.safety.scope", 'must equal "local_docker_only"'
                )
            )
        if safety.get("cleanup_required") is not True:
            issues.append(
                ValidationIssue("$.safety.cleanup_required", "must be true")
            )
        checked_duration = _bounded_number(
            safety,
            "max_total_duration_seconds",
            "$.safety",
            1,
            300,
            issues,
        )
        if checked_duration is not None:
            max_total_duration = checked_duration

    actions = document.get("actions")
    seen_action_ids: set[str] = set()
    if not isinstance(actions, list) or not actions:
        issues.append(ValidationIssue("$.actions", "must be a non-empty array"))
    elif len(actions) > 20:
        issues.append(ValidationIssue("$.actions", "must contain no more than 20 actions"))
    else:
        for index, action in enumerate(actions):
            path = f"$.actions[{index}]"
            if not isinstance(action, Mapping):
                issues.append(ValidationIssue(path, "must be an object"))
                continue
            issues.extend(_unknown_fields(action, ACTION_FIELDS, path))
            action_id = _require_text(action, "id", path, issues)
            if action_id:
                if not ACTION_ID_PATTERN.fullmatch(action_id):
                    issues.append(
                        ValidationIssue(
                            f"{path}.id",
                            "must be 3-64 lowercase letters, numbers, underscores, or hyphens",
                        )
                    )
                if action_id in seen_action_ids:
                    issues.append(ValidationIssue(f"{path}.id", "must be unique"))
                seen_action_ids.add(action_id)

            action_type = _require_text(action, "type", path, issues)
            if action_type and action_type not in ALLOWED_FAULT_TYPES:
                issues.append(
                    ValidationIssue(
                        f"{path}.type",
                        "must be one of: latency, packet_loss, disconnect, process_failure",
                    )
                )

            target = _require_text(action, "target", path, issues)
            if target and target not in declared_targets:
                issues.append(
                    ValidationIssue(
                        f"{path}.target", "must reference a declared target"
                    )
                )

            start = _bounded_number(
                action, "start_after_seconds", path, 0, 300, issues
            )
            duration = _bounded_number(
                action, "duration_seconds", path, 0.1, 300, issues
            )
            if start is not None and duration is not None:
                if start + duration > max_total_duration:
                    issues.append(
                        ValidationIssue(
                            path,
                            "action end time exceeds safety.max_total_duration_seconds",
                        )
                    )

            if "parameters" not in action:
                issues.append(ValidationIssue(f"{path}.parameters", "field is required"))
            elif action_type in ALLOWED_FAULT_TYPES:
                _validate_parameters(
                    action_type, action["parameters"], f"{path}.parameters", issues
                )
                if (
                    action_type == "process_failure"
                    and duration is not None
                    and isinstance(action["parameters"], Mapping)
                    and _is_number(action["parameters"].get("restart_after_seconds"))
                    and float(action["parameters"]["restart_after_seconds"]) != duration
                ):
                    issues.append(
                        ValidationIssue(
                            f"{path}.parameters.restart_after_seconds",
                            "must match duration_seconds when supplied",
                        )
                    )

    outcomes = document.get("expected_outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        issues.append(
            ValidationIssue("$.expected_outcomes", "must be a non-empty array")
        )
    else:
        for index, outcome in enumerate(outcomes):
            if not isinstance(outcome, str) or not outcome.strip():
                issues.append(
                    ValidationIssue(
                        f"$.expected_outcomes[{index}]", "must be a non-empty string"
                    )
                )

    return issues


def load_and_validate(path: Path) -> dict[str, Any]:
    """Load one JSON scenario and raise a detailed error when it is invalid."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScenarioValidationError(
            [ValidationIssue("$", f"file not found: {path}")]
        ) from exc
    except json.JSONDecodeError as exc:
        raise ScenarioValidationError(
            [
                ValidationIssue(
                    "$", f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
                )
            ]
        ) from exc

    issues = validate_scenario(document)
    if issues:
        raise ScenarioValidationError(issues)
    return dict(document)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a FaultLab scenario without applying any faults."
    )
    parser.add_argument("scenario", type=Path, help="path to a JSON scenario file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        scenario = load_and_validate(args.scenario)
    except ScenarioValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f'Valid FaultLab scenario "{scenario["scenario_id"]}" '
        f'({len(scenario["actions"])} action(s)); no faults were executed.'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
