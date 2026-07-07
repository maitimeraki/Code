"""Constraint encoding for prompts."""

from typing import Dict, Any, List
import structlog

from .models import PromptConstraint

logger = structlog.get_logger(__name__)


class ConstraintEncoder:
    """Encode task constraints into prompt directives."""

    @staticmethod
    def encode_safety_guardrails() -> List[str]:
        """Safety guardrails for all agents."""
        return [
            "Never modify user data without confirmation",
            "Never execute destructive commands without verification",
            "Always validate inputs before processing",
            "Never hardcode secrets or credentials",
            "Provide clear error messages on failures",
        ]

    @staticmethod
    def encode_code_quality() -> List[str]:
        """Code quality constraints."""
        return [
            "Functions should be < 50 lines",
            "Files should be < 800 lines",
            "No deep nesting (> 4 levels)",
            "Meaningful variable names required",
            "Comments only for non-obvious logic",
        ]

    @staticmethod
    def encode_performance() -> List[str]:
        """Performance constraints."""
        return [
            "O(n^2) algorithms discouraged",
            "Lazy-load large datasets",
            "Cache repeated operations",
            "Avoid blocking I/O in async context",
            "Monitor memory usage on large inputs",
        ]

    @staticmethod
    def encode_security() -> List[str]:
        """Security constraints."""
        return [
            "Validate all external inputs",
            "Use parameterized queries for databases",
            "Sanitize HTML/user content",
            "Implement rate limiting on endpoints",
            "Encrypt sensitive data at rest",
        ]

    @staticmethod
    def encode_test_coverage() -> List[str]:
        """Testing constraints."""
        return [
            "Minimum 80% code coverage required",
            "Write tests before implementation (TDD)",
            "Test both happy path and error cases",
            "Use descriptive test names",
            "Mock external dependencies",
        ]

    @staticmethod
    def create_constraint_set(
        safety: bool = True,
        code_quality: bool = True,
        performance: bool = False,
        security: bool = False,
        testing: bool = False,
    ) -> PromptConstraint:
        """Create a constraint set from configuration."""
        guardrails = []

        if safety:
            guardrails.extend(ConstraintEncoder.encode_safety_guardrails())
        if code_quality:
            guardrails.extend(ConstraintEncoder.encode_code_quality())
        if performance:
            guardrails.extend(ConstraintEncoder.encode_performance())
        if security:
            guardrails.extend(ConstraintEncoder.encode_security())
        if testing:
            guardrails.extend(ConstraintEncoder.encode_test_coverage())

        return PromptConstraint(
            max_tokens=4096,
            temperature=0.7,
            guardrails=guardrails,
        )

    @staticmethod
    def validate_constraints(constraints: PromptConstraint) -> bool:
        """Validate constraints are reasonable."""
        if constraints.max_tokens < 500 or constraints.max_tokens > 100000:
            logger.warning(f"Unusual max_tokens: {constraints.max_tokens}")
            return False

        if constraints.temperature < 0 or constraints.temperature > 2.0:
            logger.warning(f"Unusual temperature: {constraints.temperature}")
            return False

        if constraints.top_p < 0 or constraints.top_p > 1.0:
            logger.warning(f"Unusual top_p: {constraints.top_p}")
            return False

        return True

    @staticmethod
    def merge_constraints(
        base: PromptConstraint,
        override: PromptConstraint,
    ) -> PromptConstraint:
        """Merge two constraint sets (override takes precedence)."""
        merged = PromptConstraint(
            max_tokens=override.max_tokens or base.max_tokens,
            temperature=override.temperature or base.temperature,
            top_p=override.top_p or base.top_p,
            guardrails=list(set(base.guardrails + override.guardrails)),
            must_include=list(set(base.must_include + override.must_include)),
            must_avoid=list(set(base.must_avoid + override.must_avoid)),
        )

        return merged
