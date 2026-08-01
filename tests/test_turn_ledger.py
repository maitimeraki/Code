from harness.orchestration.orchestrator import MAX_LEDGER_TURNS, TURN_SUMMARY_CHARS
from harness.orchestration.agent import AgentConfig, AgentResult, AgentStatus


def _result(output: str) -> AgentResult:
    return AgentResult(
        agent_type="main",
        status=AgentStatus.COMPLETED,
        output=output,
    )


def test_agent_config_defaults_to_empty_ledger():
    config = AgentConfig(agent_type="main", task_description="do a thing")
    assert config.prior_turns == []


def test_ledger_records_prompt_and_summary(orchestrator):
    orchestrator._record_turn("first prompt", _result("first answer"))
    assert len(orchestrator.turns) == 1
    assert orchestrator.turns[0]["prompt"] == "first prompt"
    assert "first answer" in orchestrator.turns[0]["summary"]


def test_ledger_is_bounded_and_keeps_newest(orchestrator):
    for i in range(MAX_LEDGER_TURNS + 4):
        orchestrator._record_turn(f"prompt {i}", _result(f"answer {i}"))
    assert len(orchestrator.turns) == MAX_LEDGER_TURNS
    assert orchestrator.turns[-1]["prompt"] == f"prompt {MAX_LEDGER_TURNS + 3}"


def test_long_summary_is_truncated(orchestrator):
    orchestrator._record_turn("p", _result("y" * 5000))
    assert len(orchestrator.turns[0]["summary"]) <= TURN_SUMMARY_CHARS


def test_failed_turn_records_the_error(orchestrator):
    failed = AgentResult(
        agent_type="main", status=AgentStatus.FAILED, error="it exploded"
    )
    orchestrator._record_turn("p", failed)
    assert "it exploded" in orchestrator.turns[0]["summary"]
