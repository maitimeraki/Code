"""Prompt engine with template support."""

from typing import Optional
import structlog
from jinja2 import Environment, BaseLoader, Template

from .models import (
    AgentRole,
    BehaviorMode,
    PromptConstraint,
    PromptContext,
    GeneratedPrompt,
)

logger = structlog.get_logger(__name__)


class PromptEngine:
    """Generate role-optimized prompts with context injection."""

    def __init__(self):
        self.env = Environment(loader=BaseLoader())
        self.templates = self._load_templates()

    def _load_templates(self) -> dict:
        """Load and pre-compile prompt templates."""
        templates = {}

        # Architect template
        templates[AgentRole.ARCHITECT] = self.env.from_string("""You are an expert software architect specializing in system design, scalability, and technical decision-making.

Your goal: Design robust, scalable solutions that balance simplicity, performance, and maintainability.

Constraints:
- Keep designs pragmatic (avoid over-engineering)
- Document key trade-offs
- Consider operational concerns (monitoring, debugging, deployment)

Available tools: Read, Write, Grep, Glob, Bash, HTTP

Behavioral mode: {{ behavior_mode }}
""")

        # Code Reviewer template
        templates[AgentRole.CODE_REVIEWER] = self.env.from_string("""You are an expert code reviewer specializing in code quality, maintainability, and best practices.

Your goal: Review code for clarity, correctness, and adherence to project standards.

Check for:
- Readability and clear naming
- Proper error handling
- No security vulnerabilities
- Appropriate abstractions
- Test coverage

Available tools: Read, Edit, Grep, Bash

Behavioral mode: {{ behavior_mode }}
""")

        # TDD Guide template
        templates[AgentRole.TDD_GUIDE] = self.env.from_string("""You are a Test-Driven Development specialist enforcing write-tests-first methodology.

Your goal: Ensure 80%+ test coverage with meaningful, behavioral tests.

Workflow:
1. Write test first (RED phase - should fail)
2. Implement minimal code to pass (GREEN phase)
3. Refactor for clarity (IMPROVE phase)
4. Verify coverage >= 80%

Available tools: Read, Write, Edit, Bash

Behavioral mode: {{ behavior_mode }}
""")

        # Security Reviewer template
        templates[AgentRole.SECURITY_REVIEWER] = self.env.from_string("""You are a security expert specializing in vulnerability detection and secure coding practices.

Your goal: Identify and remediate security issues in code and systems.

Check for OWASP Top 10:
- Injection (SQL, command, path)
- Broken auth/session
- XSS vulnerabilities
- Insecure deserialization
- Weak cryptography

Available tools: Read, Grep, Bash

Behavioral mode: {{ behavior_mode }}
""")

        # Python Reviewer template
        templates[AgentRole.PYTHON_REVIEWER] = self.env.from_string("""You are an expert Python code reviewer specializing in PEP 8, Pythonic idioms, and performance.

Your goal: Ensure Python code is clean, efficient, and maintainable.

Standards:
- PEP 8 compliance
- Type hints for all functions
- Pythonic patterns (list comprehensions, context managers)
- Proper error handling
- Performance considerations

Available tools: Read, Edit, Grep, Bash

Behavioral mode: {{ behavior_mode }}
""")

        # Planner template
        templates[AgentRole.PLANNER] = self.env.from_string("""You are an expert planning specialist for complex features and refactoring.

Your goal: Create comprehensive implementation plans with clear phases and dependencies.

Plan should include:
- Phase breakdown with deliverables
- Dependency analysis
- Risk identification
- Testing strategy
- Rollback plan

Available tools: Read, Grep, Glob

Behavioral mode: {{ behavior_mode }}
""")

        return templates

    async def generate(
        self,
        role: AgentRole,
        task: str,
        context: Optional[PromptContext] = None,
        behavior_mode: BehaviorMode = BehaviorMode.STANDARD,
        constraints: Optional[PromptConstraint] = None,
    ) -> GeneratedPrompt:
        """Generate a role-optimized prompt with context injection."""

        if constraints is None:
            constraints = PromptConstraint()

        if context is None:
            context = PromptContext(task_description=task)

        # Get template for role
        if role not in self.templates:
            logger.warning(f"No template for role {role.value}, using standard")
            template_str = self.templates[AgentRole.PLANNER]
        else:
            template_str = self.templates[role]

        # Render system prompt with behavior mode
        system_prompt = template_str.render(
            behavior_mode=behavior_mode.value,
        )

        # Build user prompt with context
        user_prompt = self._build_user_prompt(task, context, constraints)

        # Estimate tokens (rough: ~4 chars per token)
        token_estimate = len(system_prompt + user_prompt) // 4

        generated = GeneratedPrompt(
            role=role,
            behavior_mode=behavior_mode,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            constraints=constraints,
            context_entries_used=len(context.prior_solutions),
            token_estimate=token_estimate,
        )

        logger.info(
            "Generated prompt",
            role=role.value,
            tokens=token_estimate,
            context_entries=len(context.prior_solutions),
        )

        return generated

    def _build_user_prompt(
        self,
        task: str,
        context: PromptContext,
        constraints: PromptConstraint,
    ) -> str:
        """Build user-facing prompt with context injection."""
        lines = [
            "## Task",
            f"{task}",
            "",
        ]

        # Add constraints
        if constraints.must_include or constraints.must_avoid or constraints.guardrails:
            lines.append("## Requirements")
            if constraints.must_include:
                for item in constraints.must_include:
                    lines.append(f"- Must: {item}")
            if constraints.must_avoid:
                for item in constraints.must_avoid:
                    lines.append(f"- Avoid: {item}")
            if constraints.guardrails:
                for item in constraints.guardrails:
                    lines.append(f"- Guardrail: {item}")
            lines.append("")

        # Add prior solutions
        if context.prior_solutions:
            lines.append("## Prior Solutions (for reference)")
            for entry in context.prior_solutions[:3]:  # Top 3
                lines.append(f"- {entry.title} (score: {entry.relevance_score:.2f})")
                lines.append(f"  {entry.content[:200]}...")
            lines.append("")

        # Add code examples
        if context.code_examples:
            lines.append("## Code Examples")
            for entry in context.code_examples[:2]:  # Top 2
                lines.append(f"```\n{entry.content}\n```")
            lines.append("")

        # Add tool examples
        if context.tool_examples:
            lines.append("## Tool Usage Examples")
            for entry in context.tool_examples:
                lines.append(f"- {entry.title}: {entry.content}")
            lines.append("")

        return "\n".join(lines)
