"""Pure sentiment aggregation over scored transcript turns (ADR-011.3)."""

from __future__ import annotations

from collections.abc import Iterable

from acme_agent.domain.models import Sentiment, Speaker, TranscriptTurn

TREND_THRESHOLD = 0.15  # last-third mean minus first-third mean needed to leave "stable"
MIN_SCORES_FOR_TREND = 3


def aggregate(turns: Iterable[TranscriptTurn], frustration_events: int = 0) -> Sentiment | None:
    """Average, minimum and trend of the per-turn scores; None when no turn was scored.

    Trend compares the mean of the first third of scores with the last third (at least one
    score each): a rise of `TREND_THRESHOLD` or more is `improving`, a fall of that much is
    `worsening`, anything else (and fewer than three scores) is `stable`.
    """
    scores = [
        t.sentiment for t in turns if t.speaker is Speaker.CANDIDATE and t.sentiment is not None
    ]
    if not scores:
        return None
    trend = "stable"
    if len(scores) >= MIN_SCORES_FOR_TREND:
        third = len(scores) // 3
        delta = sum(scores[-third:]) / third - sum(scores[:third]) / third
        if delta >= TREND_THRESHOLD:
            trend = "improving"
        elif delta <= -TREND_THRESHOLD:
            trend = "worsening"
    return Sentiment(
        avg=round(sum(scores) / len(scores), 3),
        min=min(scores),
        frustration_events=frustration_events,
        trend=trend,
    )
