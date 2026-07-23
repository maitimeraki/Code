"""Completion criteria checking."""

from typing import Any, Callable
import structlog

from harness.core.models import TaskState


logger = structlog.get_logger(__name__)


class CompletionChecker:
    """Verify task meets success criteria."""

    def __init__(self, criteria: dict[str, Callable[[Any], bool]]):
        """
        Initialize with criteria validators.

        Args:
            criteria: Dict of {criterion_name: validator_function}
        """
        self.criteria = criteria

    def check(self, state: TaskState) -> bool:
        """Check if all criteria are met. Updates state.criteria_met."""
        all_met = True

        for criterion_name, validator in self.criteria.items():
            try:
                result = state.results.get(criterion_name)
                met = validator(result)
                state.criteria_met[criterion_name] = met

                if not met:
                    all_met = False
                    logger.debug(f"Criterion not met: {criterion_name}")
            except Exception as e:
                logger.error(f"Error checking criterion: {criterion_name}", error=str(e))
                state.criteria_met[criterion_name] = False
                all_met = False

        return all_met

    @staticmethod
    def create_simple(criteria_dict: dict[str, Any]) -> "CompletionChecker":
        """Create checker from simple criteria dict.

        Supports numeric comparisons, boolean exact match, and equality.
        """
        validators = {}

        for key, expected in criteria_dict.items():
            # bool must be checked before int/float: in Python bool is a subclass
            # of int, so isinstance(True, (int, float)) is True and would otherwise
            # route boolean criteria into the numeric >= comparison.
            if isinstance(expected, bool):
                validators[key] = lambda result, exp=expected: result is exp
            elif isinstance(expected, (int, float)):
                validators[key] = lambda result, exp=expected: (
                    isinstance(result, (int, float)) and result >= exp
                )
            else:
                validators[key] = lambda result, exp=expected: result == exp

        return CompletionChecker(validators)
