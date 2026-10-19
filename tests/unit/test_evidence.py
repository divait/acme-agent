"""Advisory said-in-transcript check: pure function."""

from __future__ import annotations

from acme_agent.interview.evidence import said_in_transcript


def test_shared_token_ignoring_accents_case_and_stop_words() -> None:
    assert said_in_transcript("Chamberí", ["me gusta CHAMBERI"])
    assert not said_in_transcript("el de la", ["el de la"])  # stop-words never count
    assert not said_in_transcript("Acme Burgers Sol", ["mañana puedo empezar"])


def test_digit_runs_compared_as_digits() -> None:
    assert said_in_transcript("600 123 456", ["mi número es 600123456"])
    assert said_in_transcript("600123456", ["seis 600 123 456"])
    assert not said_in_transcript("600 123 456", ["mi número es 611 222 333"])


def test_only_last_three_turns_and_empty_said() -> None:
    turns = ["Marta", "uno", "dos", "tres"]
    assert not said_in_transcript("Marta", turns)
    assert said_in_transcript("", [])
    assert not said_in_transcript("Marta", [])
