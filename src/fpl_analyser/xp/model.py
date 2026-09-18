from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fpl_analyser.models import PlayerXp


@dataclass
class ModelContext:
    """Inputs for xP. Phase 1 only uses bootstrap ep_next as a labelled placeholder."""

    bootstrap: dict[str, Any]
    understat_league: dict[str, Any] | None = None
    player_match: dict[int, str] = field(default_factory=dict)
    team_match: dict[int, str] = field(default_factory=dict)


def expected_points(player_id: int, event_ids: list[int], context: ModelContext) -> PlayerXp:
    """Placeholder xP: repeats FPL ep_next across the requested horizon.

    Replace this with the event-by-event model documented in docs/expected-points.md.
    """
    players = {int(p["id"]): p for p in context.bootstrap.get("elements") or []}
    player = players.get(int(player_id)) or {}
    try:
        ep_next = float(player.get("ep_next") or 0.0)
    except (TypeError, ValueError):
        ep_next = 0.0
    per_event = {int(eid): ep_next for eid in event_ids}
    return PlayerXp(
        player_id=int(player_id),
        event_ids=[int(eid) for eid in event_ids],
        per_event=per_event,
        horizon_sum=sum(per_event.values()),
        breakdown={
            "source": "fpl_ep_next_placeholder",
            "ep_next": ep_next,
        },
        placeholder=True,
    )
