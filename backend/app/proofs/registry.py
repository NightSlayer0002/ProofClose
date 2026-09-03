from collections.abc import Callable
from inspect import Signature, signature
from typing import Any


RuleEvaluator = Callable[..., Any]


def _accepts_positional_arguments(callable_signature: Signature, *arguments: object) -> bool:
    """Check a callable's declared shape without invoking its implementation."""
    try:
        callable_signature.bind(*arguments)
    except TypeError:
        return False
    return True


def invoke_evaluator(
    evaluator: RuleEvaluator,
    inputs: dict[str, Any],
    context: object | None = None,
) -> Any:
    """Invoke an evaluator using its explicit one- or two-argument contract.

    Signature binding happens before invocation, so a ``TypeError`` raised by the
    evaluator body is never mistaken for an arity mismatch and retried.
    Historical evaluators receive only their persisted inputs; current evaluators
    may retain a one-input callable or accept the v2 context as a second input.
    """
    try:
        callable_signature = signature(evaluator)
    except (TypeError, ValueError) as exc:
        raise TypeError("rule evaluator signature is unavailable") from exc

    if context is not None and _accepts_positional_arguments(callable_signature, inputs, context):
        return evaluator(inputs, context)
    if _accepts_positional_arguments(callable_signature, inputs):
        return evaluator(inputs)
    raise TypeError("rule evaluator must accept one input argument or inputs plus context")


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], RuleEvaluator] = {}
        self._current: dict[str, str] = {}

    def register(self, rule_name: str, version: str, evaluator: RuleEvaluator) -> None:
        self._rules[(rule_name, version)] = evaluator

    def resolve(self, rule_name: str, version: str) -> RuleEvaluator | None:
        return self._rules.get((rule_name, version))

    def remove(self, rule_name: str, version: str) -> None:
        self._rules.pop((rule_name, version), None)

    def set_current(self, rule_name: str, version: str) -> None:
        if (rule_name, version) not in self._rules:
            raise ValueError("cannot activate an unregistered rule implementation")
        self._current[rule_name] = version

    def current(self, rule_name: str) -> tuple[str, RuleEvaluator] | None:
        version = self._current.get(rule_name)
        if version is None:
            return None
        evaluator = self._rules.get((rule_name, version))
        if evaluator is None:
            return None
        return version, evaluator
