"""Emulated conversations: drive a customer's agent endpoint through a multi-turn scenario,
emit the exchange as a normal trace, and roll the resulting evaluations into a gate verdict.

Pure logic only (no I/O) — `services/simulation_service.py` owns the HTTP + ingest side.
"""

from tracely.domain.simulation.aggregate import (
    ScenarioOutcome,
    conversation_verdict,
    gate_verdict,
    user_text,
)
from tracely.domain.simulation.attacker import (
    ATTACKER_SYSTEM,
    TECHNIQUES,
    AttackerMove,
    attacker_prompt,
    weakness_lines,
)
from tracely.domain.simulation.emit import turn_payload
from tracely.domain.simulation.expectations import (
    ATTACK_SCORE,
    ATTACK_SYSTEM,
    EXPECT_SCORE,
    EXPECT_SYSTEM,
    TOOLS_SCORE,
    ExpectationResult,
    attack_prompt,
    attack_result,
    attack_skipped,
    check_tools,
    expect_prompt,
    expect_result,
    expect_skipped,
)
from tracely.domain.simulation.turns import Turn, normalize_turns, serialize_turns

__all__ = [
    "ATTACKER_SYSTEM",
    "ATTACK_SCORE",
    "ATTACK_SYSTEM",
    "EXPECT_SCORE",
    "EXPECT_SYSTEM",
    "ExpectationResult",
    "ScenarioOutcome",
    "TOOLS_SCORE",
    "Turn",
    "AttackerMove",
    "TECHNIQUES",
    "attack_prompt",
    "attack_result",
    "attack_skipped",
    "attacker_prompt",
    "check_tools",
    "conversation_verdict",
    "expect_prompt",
    "expect_result",
    "expect_skipped",
    "gate_verdict",
    "normalize_turns",
    "serialize_turns",
    "turn_payload",
    "user_text",
    "weakness_lines",
]
