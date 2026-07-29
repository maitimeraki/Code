"""Tool definitions, schemas, and registry for LLM tool-calling."""

from dataclasses import dataclass
from typing import Dict, Type, Literal, Optional, Any
from pydantic import BaseModel

from .models import ToolType


class ReadFileArgs(BaseModel):
    """Arguments for read_file tool."""
    path: str


class WriteFileArgs(BaseModel):
    """Arguments for write_file tool."""
    path: str
    content: str


class EditFileArgs(BaseModel):
    """Arguments for edit_file tool."""
    path: str
    old_text: str
    new_text: str


class BashExecArgs(BaseModel):
    """Arguments for bash_exec tool."""
    command: str
    timeout: int = 120


class GrepSearchArgs(BaseModel):
    """Arguments for grep_search tool."""
    pattern: str
    path: str = "."


class GlobSearchArgs(BaseModel):
    """Arguments for glob_search tool."""
    pattern: str
    path: str = "."


class SpawnAgentArgs(BaseModel):
    """Arguments for spawn_agent tool."""
    name: str
    task: str
    working_dir: Optional[str] = None
    success_criteria: Optional[str] = None
    non_goals: Optional[list[str]] = None
    run_in_background: Optional[bool] = False
    isolation: Optional[str] = None


class AttemptCompletionArgs(BaseModel):
    """Arguments for attempt_completion tool."""
    summary: str


# ── New tool argument models ──────────────────────────────────────────────

class AskUserQuestionArgs(BaseModel):
    """Arguments for ask_user_question tool.
    Each question should have: question (str), options (list of dicts with label + optional description),
    header (str), multiSelect (bool)."""
    questions: list = []
    multi_select: bool = False
    preview: Any = None


class SkillArgs(BaseModel):
    """Arguments for skill tool."""
    skill: str
    args: str = ""


class TaskCreateArgs(BaseModel):
    """Arguments for task_create tool."""
    subject: str
    description: str = ""
    active_form: str = ""
    metadata: Optional[dict[str, Any]] = None


class TaskGetArgs(BaseModel):
    """Arguments for task_get tool."""
    task_id: str


class TaskListArgs(BaseModel):
    """Arguments for task_list tool."""
    status: Optional[str] = None


class TaskOutputArgs(BaseModel):
    """Arguments for task_output tool."""
    task_id: str
    block: bool = True
    timeout: int = 60000


class TaskStopArgs(BaseModel):
    """Arguments for task_stop tool."""
    task_id: str


class TaskUpdateArgs(BaseModel):
    """Arguments for task_update tool."""
    task_id: str
    status: Optional[str] = None
    subject: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass
class ToolDefinition:
    """Definition of a tool for LLM tool-calling."""
    name: str
    tool_type: ToolType
    description: str
    args_model: Type[BaseModel]
    permission_kind: Literal["fs_read", "fs_write", "shell", "agent_spawn", "interaction", "skill", "task"]


# Static tool registry — one entry per tool that has an actual handler.
TOOL_REGISTRY: Dict[ToolType, ToolDefinition] = {
    ToolType.READ: ToolDefinition(
        name="Read",
        tool_type=ToolType.READ,
        description=
        """Purpose:
Retrieve the contents of a file from the local filesystem and return them for inspection. This tool can access any file directly.

Behavior Rules:
This tool can read all files. If the user supplies a path, treat it as valid. Attempting to read a nonexistent file simply returns an error — that is acceptable.
The file_path parameter must be an absolute path, never a relative one.
By default, the first 2000 lines of the file are returned from the beginning.
You may optionally supply a line offset and a line limit to read a specific range (useful for very large files), but reading the entire file is the recommended default.
Returned content includes line numbers beginning at 1.
Image files (PNG, JPEG, etc.) are supported — the image is presented visually through the multimodal capabilities of the LLM.
PDF files are supported. For large PDFs (more than 10 pages), you MUST specify a pages parameter. A maximum of 20 pages may be requested per call.
Jupyter notebook files (.ipynb) are supported — all cells and their outputs are returned.
This tool reads files only, not directories. To list directory contents, use ls through the shell tool.
When the user asks you to view a screenshot, ALWAYS use this tool with the screenshot's file path.
If a file exists but contains no data, a system reminder is returned warning that the file is empty.

Guardrails:
Never fabricate file contents — return exactly what the tool provides.
If a file cannot be read, report the error clearly and suggest alternative approaches.
Do not expose secrets, credentials, or personal data discovered in file contents.
For very large files, prefer targeted range reads over loading the entire file to avoid excessive output.

Prompt Template:
You have a file reading tool that retrieves contents from the local filesystem.

Task:
{{TASK_DESCRIPTION}}

Read target:
- Path: {{FILE_PATH}}
- Scope: {{FULL_FILE_OR_RANGE}}
- Reason: {{WHY_THIS_FILE}}

Operating rules:
1) You can access any file on the filesystem. When the user provides a file path, assume it is valid. Reading a file that does not exist will return an error, and that is fine.
2) The file_path must always be absolute — never use relative paths.
3) Without explicit offset or limit parameters, the tool returns up to 2000 lines starting from line 1.
4) You may specify a line offset and line limit to read a particular section (particularly helpful for large files), but reading the complete file without parameters is the preferred approach.
5) Lines in the output are numbered starting at 1.
6) Image files (PNG, JPEG, and similar formats) can be read — the image is rendered visually through the model's multimodal support.
7) PDF files can be read. For PDFs exceeding 10 pages, you MUST include a pages parameter. No more than 20 pages per individual request.
8) Jupyter notebooks (.ipynb) can be read — the tool returns every cell along with its outputs.
9) This tool handles files only, not directories. To browse a directory, run ls via the shell tool.
10) Whenever the user requests that you examine a screenshot, ALWAYS use this tool to open the file at the given path.
11) If a file exists but is completely empty, the tool returns a system-level warning indicating zero content.

Return:
- What was read
- Critical observations
- Unknowns or ambiguities
- Recommended next read
""",
        args_model=ReadFileArgs,
        permission_kind="fs_read",
    ),
    ToolType.WRITE: ToolDefinition(
        name="Write",
        tool_type=ToolType.WRITE,
        description="""
Purpose:
Write content to a file on the local filesystem. If a file already exists at the given path, it will be completely overwritten.

Behavior Rules:
If the target is an existing file, you MUST read it with Read first. The tool will reject the operation if you have not read the file beforehand.
Prefer the Update tool for changes to existing files — it transmits only the diff. Use Write only when creating an entirely new file or when a complete rewrite of the content is necessary.
NEVER produce documentation files (*.md) or README files unless the user has explicitly asked for them.
Do not insert emojis unless the user has specifically requested them.

Guardrails:
Never overwrite an existing file you have not read in the current session.
Do not write secrets, API keys, credentials, or personal data into files.
Confirm the target path and filename are correct before writing.
If the intended destination is unclear, ask the user before creating the file.

Prompt Template:
You have a file writing tool that creates or overwrites files on the local filesystem.

Task:
{{TASK_DESCRIPTION}}

Write target:
- File path: {{FILE_PATH}}
- File purpose: {{FILE_PURPOSE}}
- Required structure/format: {{FORMAT_REQUIREMENTS}}

Operating rules:
1) When the target file already exists, you MUST have read it with FileRead beforehand. The tool will fail if you attempt to overwrite an unread file.
2) For modifications to existing files, prefer the FileEdit tool — it sends only the changed portion. Reserve FileWrite for brand-new files or situations where the entire file content must be replaced.
3) NEVER generate documentation files (*.md) or README files unless the user has expressly requested them.
4) Do not include emojis unless the user has explicitly asked for them.

Return:
- File created or overwritten
- Brief content overview
- Any assumptions made
- Optional next validation step
""",
        args_model=WriteFileArgs,
        permission_kind="fs_write",
    ),
    ToolType.EDIT: ToolDefinition(
        name="Update",
        tool_type=ToolType.EDIT,
        description="""
Purpose:
Apply precise string-level replacements within existing files, swapping an exact old substring for a new one.

Behavior Rules:
You MUST read the target file with FileRead at least once before attempting any edit. The tool will reject the operation if the file has not been read first.
When working from FileRead output, maintain the exact indentation (tabs and spaces) as it appears in the actual file content AFTER the line-number prefix. Never incorporate any portion of the line-number prefix into old_string or new_string.
ALWAYS prefer modifying an existing file over creating a new one. Only create a new file when there is an explicit requirement to do so.
Do not insert emojis unless the user has specifically asked for them.
The operation will FAIL if old_string matches more than one location in the file. To fix this, include additional surrounding lines to make the match unique, or set replace_all to true.
Enable replace_all when you need to swap every occurrence of a string throughout the file (for example, renaming a variable or identifier globally).
Choose the shortest old_string that still identifies exactly one site — typically 2–4 adjacent lines are enough. Avoid providing 10 or more lines of context.

Guardrails:
Never edit a file you have not read in the current session.
Do not silently change behavior outside the scope the user requested.
Do not strip security checks, validation logic, or error handling without a clear reason.
If the file has changed since you last read it (stale context), re-read before patching.
Abort and report when the expected match target is absent from the current file content.

Prompt Template:
You have a file editing tool that performs exact string replacements within files.

Task:
{{TASK_DESCRIPTION}}

Edit target:
- File path: {{FILE_PATH}}
- Intended modification: {{CHANGE_INTENT}}
- Limitations: {{CONSTRAINTS}}

Operating rules:
1) You MUST have read the file with FileRead at least once before making any edit. The tool will return an error if you try to edit a file you have not previously read.
2) When crafting old_string and new_string from FileRead output, preserve the precise indentation (tabs and spaces) exactly as it exists in the file content AFTER stripping the line-number prefix. Never include any part of the line-number prefix in your strings.
3) ALWAYS favor editing an existing file over writing a brand-new one. Only produce a new file when explicitly required.
4) Do not add emojis unless the user has expressly requested them.
5) The edit will FAIL when old_string appears more than once in the file. Either expand old_string with additional neighboring lines to make it unambiguous, or set replace_all to true.
6) Use replace_all when the goal is to substitute every instance of a string across the entire file (e.g., globally renaming a variable).
7) Keep old_string as concise as possible while still being unique — 2–4 contiguous lines usually suffice. Do not include 10 or more lines of context.

Return:
- File updated
- What changed and why
- Any side effects to review
- Suggested validation command(s)
""",
        args_model=EditFileArgs,
        permission_kind="fs_write",
    ),
    ToolType.BASH: ToolDefinition(
        name="Bash",
        tool_type=ToolType.BASH,
        description="""Purpose:
Execute bash commands in a controlled environment, returning their output. The working directory carries over between invocations, but shell state (variables, aliases) does not — each session starts fresh from the user's profile.

Behavior Rules:
Do NOT use this tool for file operations that have dedicated alternatives:
Reading files (cat/head/tail) → use FileRead instead
Editing files (sed/awk) → use FileEdit instead
Creating files (echo heredoc) → use FileWrite instead
Searching for files (find/ls) → use Glob instead
Searching file contents (grep/rg) → use Grep instead
Reserve shell invocation strictly for genuine system commands that require a shell.
Before creating files or directories, confirm the parent directory exists by running ls on it first.
Always wrap file paths that contain spaces in double quotes.
Track the working directory using absolute paths; avoid changing directory with cd.
An optional timeout parameter controls how long the command may run (defaults to 30 seconds, ceiling of 10 minutes).
For long-running or indefinite processes, set run_in_background. No trailing '&' is needed. You will be notified upon completion.
When issuing multiple commands:
Independent commands → send them as parallel tool invocations in a single message.
Dependent commands → chain them with && so later ones only run if earlier ones succeed.
When failure of early commands is acceptable → join with ; instead.
NEVER separate commands with newlines.
Communicate with the user by outputting text directly in your response. Do NOT use echo or printf inside the shell to relay messages.
Avoid unnecessary sleep calls: do not sleep between commands that complete immediately, prefer run_in_background over polling loops, do not retry inside a sleep loop, and if you must sleep keep durations brief (1–5 seconds).

Guardrails:
SANDBOX: Commands execute inside a sandbox by default. Filesystem access is restricted (certain reads denied, writes limited to allowed paths). Network access is restricted. Use $TMPDIR rather than /tmp. Only disable the sandbox (dangerouslyDisableSandbox) when a command fails specifically because of sandbox restrictions.
GIT SAFETY:
Never alter git configuration.
Never force-push or perform irreversible git operations.
Never pass --no-verify or skip commit hooks.
Favor creating a new commit over amending an existing one.
Stage specific files rather than using -A (stage-all).
GIT COMMIT PROCESS:
Run git status and git diff in parallel to inspect all pending changes.
Review recent commit messages (git log) to match the repository's style.
Stage only the relevant files.
Write the commit message using a HEREDOC to preserve formatting:
git commit -m "$(cat <<'EOF'
Your message here.
EOF
)"
Run git status after committing to confirm success.
PULL REQUEST CREATION:
Run git status, git diff, remote tracking check, and git log in parallel to understand the branch state since it diverged from the base branch.
Push with -u if the remote branch doesn't exist yet.
Create the PR via gh pr create with a body structured as:
Summary — 1–3 bullet points
Test plan — checklist of verification steps
Use a HEREDOC for the PR body to ensure correct formatting.
Never push to remote unless the user explicitly asks.

Prompt Template:
You have a bash execution tool for running system commands.

Task:
{{TASK_DESCRIPTION}}

Environment:
- Working directory: {{WORKING_DIRECTORY}}
- Expected result: {{EXPECTED_OUTCOME}}
- Limitations: {{CONSTRAINTS}}

Operating rules:
1) The working directory persists across calls, but shell state (env vars, aliases, functions) does not — each invocation starts from the user's shell profile.
2) Do NOT invoke this tool for file I/O that has a specialized counterpart:
- Reading files (cat/head/tail) → FileRead
- Modifying files (sed/awk) → FileEdit
- Creating files (echo with heredoc) → FileWrite
- Locating files (find/ls) → Glob
- Searching content (grep/rg) → Grep
Use shell exclusively for genuine system-level commands.
3) Before creating any file or directory, verify the parent path exists by listing it with ls.
4) Enclose any file path containing spaces in double quotes.
5) Reference the working directory with absolute paths; do not use cd to navigate.
6) An optional timeout controls maximum execution time (default 30 seconds, cap 10 minutes).
7) For long-running or persistent processes, enable run_in_background — no trailing '&' required. You receive a notification when the process finishes.
8) When dispatching multiple commands:
- Independent ones → parallel tool calls in one message.
- Sequential dependencies → join with &&.
- Sequence where early failures are acceptable → join with ;.
- NEVER use newlines to delimit separate commands.
9) Relay information to the user by writing text in your response — never use echo or printf inside the shell for communication.
10) Minimize sleep usage: skip it between instant commands, use run_in_background instead of poll-loops, avoid retry-via-sleep patterns, and if sleep is unavoidable keep it to 1–5 seconds.

Sandbox policy:
- Commands execute within a sandbox by default with restricted filesystem reads, constrained write paths, and limited network access.
- Use $TMPDIR instead of /tmp for temporary files.
- Only disable the sandbox (dangerouslyDisableSandbox) when a failure is directly caused by sandbox restrictions and cannot be resolved otherwise.
- Do not suggest adding sensitive paths like ~/.bashrc, ~/.zshrc, ~/.ssh/* to the sandbox allowlist.
- Evidence of sandbox failures includes: operation not permitted errors, access denied to paths outside allowed directories, network connection failures to non-whitelisted hosts, unix socket connection errors.

Git safety protocol:
- Never modify git configuration.
- Never execute destructive or irreversible git operations (force push, hard reset, etc.) unless the user explicitly requests them.
- Never bypass hooks (--no-verify, --no-gpg-sign, etc.) unless explicitly told to.
- Prefer creating a fresh commit over amending a previous one.
- Stage individual files instead of using -A to stage everything.
- Do not commit changes unless the user explicitly requests it.
- Do not use the -uall flag with git status (can cause memory issues on large repos).
- Never use the -i flag with git commands (interactive input not supported).

Git commit procedure:
1) Inspect all pending changes: run git status and git diff simultaneously.
2) Check recent commit messages (git log) to follow the project's style.
3) Stage only the files relevant to the change.
4) Compose the commit message inside a HEREDOC block:
git commit -m "$(cat <<'EOF'
Commit message here.
EOF
)"
5) Confirm the commit succeeded by running git status afterward.
6) Do not commit files likely containing secrets (.env, credentials.json). Warn the user if they specifically request it.
7) Write a concise (1-2 sentence) message that focuses on the reason for the change rather than describing the change.

Pull request procedure:
1) Gather branch context in parallel: git status, git diff, remote tracking status, git log, and git diff <base>...HEAD.
2) Push with -u if no upstream branch is set.
3) Open the PR with gh pr create, structuring the body as:
## Summary — 1–3 bullet points
## Test plan — verification checklist
Use a HEREDOC for the body to preserve formatting.
4) Keep the PR title under 70 characters.
5) Return the PR URL when finished.
6) Never push to remote unless the user explicitly instructs it.

Return:
- Commands executed
- Key output highlights
- Result status (success / failed / partial)
- Recommended next action
""",
        args_model=BashExecArgs,
        permission_kind="shell",
    ),
    ToolType.GREP: ToolDefinition(
        name="Grep",
        tool_type=ToolType.GREP,
        description="""Purpose:
Locate exact text or regex-based pattern matches within file contents across a codebase using a high-performance ripgrep-powered engine.

Behavior Rules:
This is a high-performance content search engine built on top of ripgrep.
You MUST use this tool for all text content searches. NEVER call grep or rg directly via the shell — this tool is specifically tuned for proper permissions and file access.
Full regular expression syntax is available (for example, log.*Error or function\\s+\\w+).
Narrow results to specific files using the glob parameter (e.g., *.js, **/*.tsx) or the type parameter (e.g., js, py, rust).
Three output modes exist: content displays the matching lines themselves, files_with_matches returns only the paths of files that matched (this is the default), and count reports how many matches occurred per file.
When a search is exploratory and likely to need several iterative rounds, delegate to the Agent tool instead.
The pattern engine is ripgrep, not GNU grep — literal curly braces must be escaped (write interface\\{\\} to match interface{} in Go code).
By default, patterns only match within individual lines. To match patterns that span multiple lines, enable the multiline flag by setting multiline: true.

Guardrails:
Avoid overly broad regex that could produce excessive or runaway output.
Do not search directories outside the relevant scope when you know where to look.
Redact or omit sensitive strings discovered in search results.
Treat matches as candidates — confirm with a file read before making edits.
If results are truncated, narrow the scope and re-run rather than guessing at missing data.

Prompt Template:
You are executing a text content search using a ripgrep-based matching engine.

Task:
{{TASK_DESCRIPTION}}

Search configuration:
- Regex pattern: {{SEARCH_PATTERN}}
- Target path: {{SEARCH_PATH}}
- File filter (glob or type): {{FILE_GLOB_OR_TYPE}}
- Lines of surrounding context: {{CONTEXT_LINES}}

Operational rules:
1) This engine is built on ripgrep. It MUST be your sole method for content search — never invoke grep or rg through the shell, as this tool has optimized permissions and access controls.
2) Full regex is supported (e.g., "log.*Error", "function\\s+\\w+"). Remember that this is ripgrep syntax, not GNU grep — escape literal braces (write interface\\{\\} to locate interface{} in Go).
3) Restrict results using the glob parameter (e.g., "*.js", "**/*.tsx") or the type parameter (e.g., "js", "py", "rust").
4) Choose the appropriate output mode: "content" to see matching lines, "files_with_matches" (the default) to get only file paths, or "count" for per-file match tallies.
5) Patterns match within single lines by default. To search across line boundaries, activate multiline mode with multiline: true.
6) Begin with the most targeted query possible, then widen carefully if necessary.
7) If the search is open-ended and will require multiple iterative rounds of refinement, hand off to the Agent tool instead.
8) Summarize the strongest matches with file-path-level precision.
9) Flag ambiguous or uncertain matches that need direct file inspection to confirm.

Return:
- Search pattern(s) executed
- Top relevant matches with reasoning
- Notes on empty results or truncation
- Suggested files to read or edit next
""",
        args_model=GrepSearchArgs,
        permission_kind="fs_read",
    ),
    ToolType.GLOB: ToolDefinition(
        name="Glob",
        tool_type=ToolType.GLOB,
        description="""Purpose:
Discover files by their path and name patterns so that implementation, review, and investigation work can be scoped quickly.

Behavior Rules:
This is a high-speed file pattern matching engine that scales to codebases of any size.
It accepts standard glob syntax such as **/*.js or src/**/*.ts.
Results are returned as a list of matching file paths ordered by most-recently-modified first.
Reach for this tool whenever you need to locate files based on naming conventions or directory structure.
When the search is open-ended and will require multiple iterative rounds of glob and grep operations, delegate to the Agent tool instead.

Guardrails:
Avoid sweeping wildcard scans when you already know the target directories.
Skip hidden and excluded directories unless the task specifically calls for them.
Treat generated code and dependency directories as opt-in, not default.
If a pattern returns an overwhelming number of paths, tighten it rather than dumping all results.
Never assume a file's purpose from its path alone — verify with a content read.

Prompt Template:
You are locating files via glob-style path pattern matching.

Task:
{{TASK_DESCRIPTION}}

Glob configuration:
- Pattern: {{GLOB_PATTERN}}
- Root directory: {{TARGET_DIRECTORY}}
- Exclusions: {{EXCLUDE_PATTERNS}}

Operational rules:
1) This is a high-speed file finder that performs well regardless of codebase size. Use it whenever you need to locate files by name or path patterns.
2) Standard glob syntax is supported — for example, "**/*.js" or "src/**/*.ts".
3) Matched file paths are returned sorted by modification time, most recent first.
4) Start with a tightly scoped pattern and broaden only if essential files are missing.
5) If the task demands several iterative rounds of globbing and content searching, hand off to the Agent tool rather than running many sequential calls yourself.
6) Organize results by relevance to the current task.
7) Recommend which discovered file(s) should be inspected next.

Return:
- Glob pattern(s) executed
- Matching file paths
- Confidence and relevance notes
- Recommended next action
""",
        args_model=GlobSearchArgs,
        permission_kind="fs_read",
    ),
    ToolType.SPAWN_AGENT: ToolDefinition(
        name="Agent",
        tool_type=ToolType.SPAWN_AGENT,
        description=(
            """Purpose:
Spawn autonomous sub-agents to carry out complex, multi-step work independently — each with its own tools, context window, and specialization.Available agent types are listed in <system-reminder> messages in the conversation.

Behavior Rules:
Every invocation creates a fresh subprocess. Specify an agent name so the system selects the right toolset.
Attach a brief label (3–5 words) that captures the agent's mission at a glance.
When several agents have no dependency on each other, fire them all in one message via parallel tool calls — never sequentially.
The spawned agent's output is invisible to the end user. After the agent returns, relay a concise summary in your own words.
Agents can run in the foreground (default — blocks until done) or in the background (run_in_background). Choose foreground when you need results before continuing; choose background when you have other independent work to do while the agent runs.
You are notified automatically when a background agent finishes — do not poll or sleep.
To continue a conversation with an existing agent, send a follow-up message using SendMessage with the agent's ID. The agent resumes with full history intact. A brand-new Agent call always starts from scratch — provide a complete briefing every time.
Use isolation: "worktree" when the agent needs its own git worktree copy to avoid conflicts.
Trust the agent's results by default.
When an agent's description says it should be invoked proactively, do so without waiting for an explicit user request.

When NOT to Invoke:
Reading a known file path — call FileRead or Glob yourself.
Searching for a specific symbol like class Foo — use Glob directly.
Looking inside 2–3 particular files — use FileRead directly.
Any task you can resolve in a single straightforward tool call.

Crafting the Agent Briefing:
Write as though briefing a capable colleague who just sat down — they have zero visibility into the conversation so far.
State what you are trying to achieve and why it matters.
Summarize what you have already discovered or eliminated.
Supply enough background that the agent can exercise judgment without asking follow-up questions.
For simple lookups, hand over the exact command or query. For open-ended investigations, hand over the question itself.
Be explicit about whether the agent should produce code changes or just gather information.
Terse, command-style instructions lead to shallow, generic output. Invest in a substantive prompt.
Never offload comprehension: do not write "based on what you find, fix it." Instead, include file paths, line numbers, and precise descriptions of the change required — proving that you already understand the problem.

Guardrails:
Do not delegate work the parent agent can finish faster with a direct tool call.
Do not spawn agents for trivial one-step actions.
Do not leave the user uninformed — always surface a summary of the agent's findings.
Do not use vague prompts that force the sub-agent to guess your intent.
When running agents in parallel, ensure none depend on another's output.

Prompt Template:
You are launching a specialized sub-agent to perform autonomous work.
Mission:
{{BRIEF_LABEL}} — {{DETAILED_OBJECTIVE}}

Agent configuration:
- Type: {{AGENT_TYPE}}
- Isolation: {{WORKTREE_OR_NONE}}
- Execution: {{FOREGROUND_OR_BACKGROUND}}

Briefing for the agent:
Context: {{WHAT_YOU_KNOW_AND_HAVE_TRIED}}
Goal: {{DESIRED_OUTCOME}}
Scope: {{RESEARCH_ONLY_OR_IMPLEMENT}}
Key details: {{FILE_PATHS_LINE_NUMBERS_SPECIFICS}}

After the agent returns:
- Summarize its findings or changes for the user.
- Decide whether follow-up work or another agent launch is needed.
"""
        ),
        args_model=SpawnAgentArgs,
        permission_kind="agent_spawn",
    ),
    ToolType.ATTEMPT_COMPLETION: ToolDefinition(
        name="Completion",
        tool_type=ToolType.ATTEMPT_COMPLETION,
        description=(
            """Signal that you believe the task is complete. Pass a short summary of "
            "what you accomplished. If a verification step is configured for this task, "
            "your completion is only accepted when that check passes; if it fails, you "
            "will be told why and must continue until it passes."""
        ),
        args_model=AttemptCompletionArgs,
        permission_kind="fs_read",
    ),
    # ── Interaction tools ────────────────────────────────────────────────────
    ToolType.ASK_USER_QUESTION: ToolDefinition(
        name="AskUserQuestion",
        tool_type=ToolType.ASK_USER_QUESTION,
        description=(
            """Purpose:
Present structured multiple-choice questions to the user when you need to resolve ambiguity, learn preferences, collect missing information, or get a decision on competing implementation paths.

Behavior Rules:
Offer clear, labeled options. Users can always pick "Other" and type a free-form answer.
Set multiSelect: true when more than one choice is valid simultaneously.
When you have a preferred recommendation, place it first in the list and append "(Recommended)" to its label.
In plan mode, use this tool to nail down requirements before finalizing the plan. Do not use it to ask "Does this plan look good?" — that is the job of ExitPlanMode.
Never reference "the plan" in your question text, because the user cannot see the plan in the UI until ExitPlanMode has been called.

Preview feature:
Use the optional `preview` field on options when presenting concrete artifacts to users for better understanding.

When to Invoke:
Ambiguous instructions where two or more reasonable interpretations exist.
Implementation forks that depend on user taste or project conventions.
Missing data that cannot be safely assumed.
Offering directional choices (e.g., "optimize for speed vs. readability").

Guardrails:
Do not ask when the answer is inferable from context or low-risk to assume.
Do not repeat questions already answered in the conversation.
Do not present misleading options that obscure real tradeoffs.
Do not ask the user to reveal secrets or credentials in chat.
Keep each question tightly scoped — one decision per invocation.

Prompt Template:
You need structured input from the user before continuing.
Situation:
{{WHY_INPUT_IS_NEEDED}}
Question:
{{SINGLE_FOCUSED_QUESTION}}
Options:
1. {{RECOMMENDED_OPTION}} (Recommended)
2. {{ALTERNATIVE_A}}
3. {{ALTERNATIVE_B}}
4. Other — provide your own answer
Selection mode: {{SINGLE_SELECT_OR_MULTI_SELECT}}
Fallback if no response:
{{DEFAULT_ACTION_AND_RATIONALE}}
"""
        ),
        args_model=AskUserQuestionArgs,
        permission_kind="interaction",
    ),
    ToolType.SKILL: ToolDefinition(
        name="Skill",
        tool_type=ToolType.SKILL,
        description="Execute a skill within the main conversation.",
        args_model=SkillArgs,
        permission_kind="skill",
    ),
    # ── Task management tools ────────────────────────────────────────────────
    ToolType.TASK_CREATE: ToolDefinition(
        name="TaskCreate",
        tool_type=ToolType.TASK_CREATE,
        description="""
Use this tool to create a structured task list for your current coding session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user. It also helps the user understand the progress of the task and overall progress of their requests.

When to Use This Tool:
Use this tool proactively in these scenarios:

Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
Non-trivial and complex tasks - Tasks that require careful planning or multiple operations${CONDTIONAL_TEAMMATES_NOTE}
Plan mode - When using plan mode, create a task list to track the work
User explicitly requests todo list - When the user directly asks you to use the todo list
User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
After receiving new instructions - Immediately capture user requirements as tasks
When you start working on a task - Mark it as in_progress BEFORE beginning work
After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation


When NOT to Use This Tool:
Skip using this tool when:

There is only a single, straightforward task
The task is trivial and tracking it provides no organizational benefit
The task can be completed in less than 3 trivial steps
The task is purely conversational or informational
NOTE that you should not use this tool if there is only one trivial task to do. In this case you are better off just doing the task directly.

Task Fields:
subject: A brief, actionable title in imperative form (e.g., "Fix authentication bug in login flow")
description: What needs to be done
activeForm (optional): Present continuous form shown in the spinner when the task is in_progress (e.g., "Fixing authentication bug"). If omitted, the spinner shows the subject instead.
All tasks are created with status pending.

Tips:
Create tasks with clear, specific subjects that describe the outcome
After creating tasks, use TaskUpdate to set up dependencies (blocks/blockedBy) if needed ${CONDITIONAL_TASK_NOTES}- Check TaskList first to avoid creating duplicate tasks
""",
        args_model=TaskCreateArgs,
        permission_kind="task",
    ),
    ToolType.TASK_GET: ToolDefinition(
        name="TaskGet",
        tool_type=ToolType.TASK_GET,
        description="""
Use this tool to retrieve a task by its ID from the task list.

When to Use This Tool:
When you need the full description and context before starting work on a task
To understand task dependencies (what it blocks, what blocks it)
After being assigned a task, to get complete requirements

Output:
Returns full task details:
subject: Task title
description: Detailed requirements and context
status: 'pending', 'in_progress', or 'completed'
blocks: Tasks waiting on this one to complete
blockedBy: Tasks that must complete before this one can start

Tips:
After fetching a task, verify its blockedBy list is empty before beginning work.
Use TaskList to see all tasks in summary form.
""",
        args_model=TaskGetArgs,
        permission_kind="task",
    ),
    ToolType.TASK_LIST: ToolDefinition(
        name="TaskList",
        tool_type=ToolType.TASK_LIST,
        description="""
Use this tool to list all tasks in the task list.

When to Use This Tool:
To see what tasks are available to work on (status: 'pending', no owner, not blocked)
To check overall progress on the project
To find tasks that are blocked and need dependencies resolved ${TEAMMATE_TASKLIST_WHEN_TO_USE_NOTE}- After completing a task, to check for newly unblocked work or claim the next available task
Prefer working on tasks in ID order (lowest ID first) when multiple tasks are available, as earlier tasks often set up context for later ones

Output:
Returns a summary of each task: ${TASKLIST_ID_OUTPUT_LINE}
subject: Brief description of the task
status: 'pending', 'in_progress', or 'completed'
owner: Agent ID if assigned, empty if available
blockedBy: List of open task IDs that must be resolved first (tasks with blockedBy cannot be claimed until dependencies resolve)
Use TaskGet with a specific task ID to view full details including description and comments. ${TEAMMATE_WORKFLOW_BLOCK}
""",
        args_model=TaskListArgs,
        permission_kind="task",
    ),
    ToolType.TASK_OUTPUT: ToolDefinition(
        name="TaskOutput",
        tool_type=ToolType.TASK_OUTPUT,
        description=(
            "Retrieve output from a background task. Deprecated in favor of Read "
            "on the task's output file path. When no task matches the ID, the error "
            "lists the running background agents by ID and description."
        ),
        args_model=TaskOutputArgs,
        permission_kind="task",
    ),
    ToolType.TASK_STOP: ToolDefinition(
        name="TaskStop",
        tool_type=ToolType.TASK_STOP,
        description=(
            """Stops a running background task by ID. It also accepts an agent-team teammate or a named background agent by agent ID or name. Before v2.1.198, it accepted only a background task ID. When no task matches the ID, the error lists the running background agents by ID and description, including agents that another agent spawned."""
        ),
        args_model=TaskStopArgs,
        permission_kind="task",
    ),
    ToolType.TASK_UPDATE: ToolDefinition(
        name="TaskUpdate",
        tool_type=ToolType.TASK_UPDATE,
        description="""
Use this tool to update a task in the task list.

When to Use This Tool:
Mark tasks as resolved:
    When you have completed the work described in a task
    When a task is no longer needed or has been superseded
    IMPORTANT: Always mark your assigned tasks as resolved when you finish them
    After resolving, call TaskList to find your next task
    ONLY mark a task as completed when you have FULLY accomplished it
    If you encounter errors, blockers, or cannot finish, keep the task as in_progress
    When blocked, create a new task describing what needs to be resolved
    Never mark a task as completed if:
        Tests are failing
        Implementation is partial
        You encountered unresolved errors
        You couldn't find necessary files or dependencies
Delete tasks:
    When a task is no longer relevant or was created in error
    Setting status to deleted permanently removes the task
Update task details:
    When requirements change or become clearer
    When establishing dependencies between tasks
    
Fields You Can Update:
    status: The task status (see Status Workflow below)
    subject: Change the task title (imperative form, e.g., "Run tests")
    description: Change the task description
    activeForm: Present continuous form shown in spinner when in_progress (e.g., "Running tests")
    owner: Change the task owner (agent name)
    metadata: Merge metadata keys into the task (set a key to null to delete it)
    addBlocks: Mark tasks that cannot start until this one completes
    addBlockedBy: Mark tasks that must complete before this one can start
    
Status Workflow:
    Status progresses: pending → in_progress → completed
    Use deleted to permanently remove a task.

Staleness:
Make sure to read a task's latest state using TaskGet before updating it.

Examples:
Mark task as in progress when starting work:

{"taskId": "1", "status": "in_progress"}
Mark task as completed after finishing work:

{"taskId": "1", "status": "completed"}
Delete a task:

{"taskId": "1", "status": "deleted"}
Claim a task by setting owner:

{"taskId": "1", "owner": "my-name"}
Set up task dependencies:

{"taskId": "2", "addBlockedBy": ["1"]}
""",
        args_model=TaskUpdateArgs,
        permission_kind="task",
    ),
}


def to_llm_tool_schema(definition: ToolDefinition) -> dict:
    """Convert a ToolDefinition to OpenAI/litellm tool schema format."""
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.args_model.model_json_schema(),
        },
    }

from harness.registry.definitions import AgentRegistry
def get_tools_payload(router) -> list[dict]:
    """Build tools payload for LLM, filtering to only registered handlers.

    For spawn_agent, dynamically appends available agent names+descriptions to the tool description.
    """
    tools = []
    for tool_type in router.handlers.keys():
        if tool_type not in TOOL_REGISTRY:
            continue
        definition = TOOL_REGISTRY[tool_type]
        schema = to_llm_tool_schema(definition)
        tools.append(schema)
    return tools


def validate_args(tool_type: ToolType, raw_args: dict) -> BaseModel:
    """Validate and parse tool arguments against the tool's args schema.

    Raises pydantic.ValidationError if arguments don't match the schema.
    """
    if tool_type not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool type: {tool_type.value}")

    definition = TOOL_REGISTRY[tool_type]
    return definition.args_model.model_validate(raw_args)
