"""Definition registry: frontmatter-only scan, lazy body loading, mtime-invalidated cache."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
import yaml
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DefinitionMeta:
    """Lightweight metadata for an agent/skill."""
    name: str
    description: str
    path: Path
    mtime: float
    tools: Optional[list[str]] = None
    model: Optional[str] = None


class DefinitionRegistry:
    """Scan frontmatter-only, lazy-load full body with mtime-invalidated cache."""

    def __init__(self, dir_getter: Callable[[], Path], kind: str):
        self._dir_getter = dir_getter
        self.kind = kind
        self._index: Dict[str, DefinitionMeta] = {}
        self._body_cache: Dict[str, Tuple[float, str]] = {}

    def scan(self) -> None:
        """(Re)build the lightweight index. Reads ONLY frontmatter bytes per file."""
        directory = self._dir_getter()
        self._index.clear()
        if not directory.exists():
            return

        for path in sorted(directory.glob("*.md")):
            meta = self._parse_frontmatter_only(path)
            if meta is not None:
                self._index[meta.name] = meta

    def _parse_frontmatter_only(self, path: Path) -> Optional[DefinitionMeta]:
        """Reads line-by-line; stops at closing '---'. Body is never read here."""
        try:
            with path.open("r", encoding="utf-8") as f:
                first_line = f.readline()
                if first_line.strip() != "---":
                    logger.warning("Skipping .md without frontmatter", path=str(path))
                    return None

                fm_lines = []
                closed = False
                for line in f:
                    if line.strip() == "---":
                        closed = True
                        break
                    fm_lines.append(line)

                if not closed:
                    logger.warning("Skipping .md with unterminated frontmatter", path=str(path))
                    return None

            frontmatter = yaml.safe_load("".join(fm_lines)) or {}
            name = frontmatter.get("name") or path.stem
            description = frontmatter.get("description", "")

            return DefinitionMeta(
                name=name,
                description=description,
                path=path,
                mtime=path.stat().st_mtime,
                tools=frontmatter.get("tools"),
                model=frontmatter.get("model"),
            )

        except (OSError, yaml.YAMLError) as e:
            logger.warning("Failed to parse frontmatter", path=str(path), error=str(e))
            return None

    def list(self) -> list[DefinitionMeta]:
        """Return lightweight index (name + description only)."""
        return list(self._index.values())

    def get_full(self, name: str) -> str:
        """Lazily read + return full markdown body. Memoized; invalidated by mtime."""
        if name not in self._index:
            raise KeyError(f"No {self.kind} named '{name}'")

        meta = self._index[name]
        current_mtime = meta.path.stat().st_mtime
        cached = self._body_cache.get(name)

        if cached is not None and cached[0] == current_mtime:
            return cached[1]

        body = meta.path.read_text(encoding="utf-8")
        self._body_cache[name] = (current_mtime, body)
        return body


class AgentRegistry(DefinitionRegistry):
    """Registry for agents, exposes list_agents()."""

    def __init__(self, dir_getter: Callable[[], Path]):
        super().__init__(dir_getter, kind="agent")

    def list_agents(self) -> list[DefinitionMeta]:
        """Return lightweight agent index."""
        return self.list()


class SkillRegistry(DefinitionRegistry):
    """Registry for skills, exposes list_skills()."""

    def __init__(self, dir_getter: Callable[[], Path]):
        super().__init__(dir_getter, kind="skill")

    def list_skills(self) -> list[DefinitionMeta]:
        """Return lightweight skill index."""
        return self.list()


# Extracted templates from PromptEngine._load_templates(), stripped of Jinja {{ behavior_mode }} line
_SEED_AGENT_BODIES: Dict[str, Tuple[str, str]] = {
    "architect": (
        "Expert software architect for system design and technical decisions.",
        """# Architect Agent

You are an expert software architect specializing in system design, scalability, and technical decision-making.

## Your Role
- Analyze complex systems and propose scalable architectures
- Make informed technical decisions balancing trade-offs
- Design for maintainability, performance, and extensibility
- Evaluate different approaches and recommend the best fit

## Guidelines
- Think about deployment, monitoring, and operational concerns
- Consider team size and skill levels
- Propose concrete implementation patterns
- Document architectural decisions with rationale
""",
    ),
    "code-reviewer": (
        "Expert code reviewer for quality, maintainability, and best practices.",
        """# Code Reviewer Agent

You are an expert code reviewer specializing in code quality, maintainability, and best practices.

## Your Role
- Review code for correctness and quality
- Identify potential bugs and edge cases
- Suggest improvements and refactoring opportunities
- Enforce coding standards and best practices

## Guidelines
- Focus on clarity and maintainability
- Consider performance implications
- Check for common pitfalls and anti-patterns
- Provide actionable feedback with examples
""",
    ),
    "tdd-guide": (
        "Test-Driven Development specialist enforcing write-tests-first methodology.",
        """# TDD Guide Agent

You are a Test-Driven Development specialist who enforces the write-tests-first methodology.

## Your Role
- Guide teams through TDD workflows
- Ensure 80%+ test coverage
- Identify untested code paths
- Promote testing best practices

## Guidelines
- Write tests first, implementation second (RED -> GREEN -> REFACTOR)
- Focus on behavioral testing, not implementation details
- Consider edge cases and error conditions
- Maintain test clarity and performance
""",
    ),
    "security-reviewer": (
        "Security expert for vulnerability detection and secure coding.",
        """# Security Reviewer Agent

You are a security expert specializing in vulnerability detection and secure coding practices.

## Your Role
- Identify security vulnerabilities
- Review authentication and authorization
- Check for OWASP Top 10 issues
- Promote secure design patterns

## Guidelines
- Assume adversarial input
- Focus on data protection and access control
- Consider both application and infrastructure security
- Recommend concrete mitigations
""",
    ),
    "python-reviewer": (
        "Expert Python reviewer for PEP 8, idioms, and performance.",
        """# Python Reviewer Agent

You are an expert Python code reviewer specializing in PEP 8, Pythonic idioms, and performance.

## Your Role
- Review Python code for idioms and style
- Check PEP 8 compliance
- Identify performance issues
- Promote Pythonic approaches

## Guidelines
- Prefer built-in functions and standard library
- Use comprehensions and generators appropriately
- Follow PEP 8 and modern Python conventions
- Consider type hints and static analysis
""",
    ),
    "planner": (
        "Expert planning specialist for complex features and refactoring.",
        """# Planner Agent

You are an expert planning specialist for complex features and refactoring tasks.

## Your Role
- Create detailed implementation plans
- Break down complex tasks into phases
- Identify dependencies and risks
- Provide clear, actionable steps

## Guidelines
- Think step-by-step through requirements
- Identify critical files and dependencies
- Consider testing and integration
- Provide verification steps for each phase
""",
    ),
    "rust-reviewer": (
        "Rust code reviewer specializing in memory safety and idioms.",
        """# Rust Reviewer Agent

You are a Rust code reviewer specializing in memory safety, ownership, and idiomatic patterns.

## Your Role
- Review Rust code for memory safety
- Check ownership and borrowing correctness
- Promote idiomatic Rust patterns
- Identify performance and safety issues

## Guidelines
- Think about ownership and lifetimes
- Consider error handling strategies
- Promote iterator-based approaches
- Review unsafe code carefully
""",
    ),
    "typescript-reviewer": (
        "TypeScript code reviewer for type safety and async correctness.",
        """# TypeScript Reviewer Agent

You are a TypeScript code reviewer specializing in type safety, async correctness, and Node.js patterns.

## Your Role
- Review TypeScript code for type safety
- Check async/await and Promise handling
- Promote idiomatic TypeScript patterns
- Identify performance and correctness issues

## Guidelines
- Ensure strict type checking
- Handle errors and rejections properly
- Consider performance and memory usage
- Review async patterns carefully
""",
    ),
    "performance-optimizer": (
        "Performance optimization specialist for identifying and fixing bottlenecks.",
        """# Performance Optimizer Agent

You are a performance optimization specialist for identifying and fixing bottlenecks.

## Your Role
- Identify performance bottlenecks
- Propose optimization strategies
- Review algorithmic efficiency
- Consider resource utilization

## Guidelines
- Profile before optimizing
- Consider trade-offs (memory vs speed)
- Focus on high-impact optimizations
- Measure improvements
""",
    ),
}


def ensure_seed_agents(settings) -> None:
    """Write default agent .md files to ~/.code/agents/ if that dir has no *.md files yet.
    Idempotent; runs once per process at startup (called before AgentRegistry.scan())."""
    target_dir = settings.user_agents_dir
    target_dir.mkdir(parents=True, exist_ok = True) # To ensure the path should be exist
    if any(target_dir.glob("*.md")):
        return

    for name, (description, body) in _SEED_AGENT_BODIES.items():
        frontmatter = f"---\nname: {name}\ndescription: {description}\n---\n\n"
        (target_dir / f"{name}.md").write_text(frontmatter + body, encoding="utf-8")

    logger.info("Seeded default agents", dir=str(target_dir), count=len(_SEED_AGENT_BODIES))
