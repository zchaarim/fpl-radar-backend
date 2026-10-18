from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fpl_radar.features import minutes_points
from fpl_radar.fpl_rules import POSITION_LABELS, ShrinkageConfig, scoring_table
from fpl_radar.ingest.sync import load_model_context, sync_fpl, sync_understat
from fpl_radar.xp.model import GOAL_KEYS, ModelContext, expected_points, horizon_event_ids


def _ep_float(player: dict[str, Any], key: str) -> float | None:
    raw = player.get(key)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def snapshot_rows(
    ctx: ModelContext,
    event_id: int,
    *,
    late: bool = False,
    deadline_time: str | None = None,
    first_kickoff: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    table = scoring_table(ctx.bootstrap.get("game_settings"))
    shrinkage = ShrinkageConfig()
    if ctx.features is not None:
        shrinkage = ctx.features.shrinkage
    taken_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for player in ctx.bootstrap.get("elements") or []:
        pid = int(player["id"])
        etype = int(player.get("element_type") or 0)
        xp = expected_points(pid, [event_id], ctx)
        event_break = (xp.breakdown.get("events") or {}).get(str(event_id)) or {}
        components = {
            "minutes": 0.0,
            "attack": 0.0,
            "cs": 0.0,
            "gc": 0.0,
            "defcon": 0.0,
            "bonus": 0.0,
            "saves": 0.0,
            "cards": 0.0,
        }
        if not xp.placeholder and not event_break.get("blank"):
            components["minutes"] = minutes_points(
                float(event_break.get("p_played") or 0.0),
                float(event_break.get("p60") or 0.0),
                table,
            )
            goal_pts = float(table[GOAL_KEYS.get(etype, "goal_mid")])
            components["attack"] = float(event_break.get("xg") or 0.0) * goal_pts + float(
                event_break.get("xa") or 0.0
            ) * float(table["assist"])
            components["cs"] = float(event_break.get("cs_xp") or 0.0)
            components["gc"] = float(event_break.get("gc_xp") or 0.0)
            components["defcon"] = float(event_break.get("defcon_xp") or 0.0)
            components["bonus"] = float(event_break.get("bonus_xp") or 0.0)
            components["saves"] = float(event_break.get("saves_xp") or 0.0)
            components["cards"] = float(event_break.get("cards_xp") or 0.0)
        predicted = float(xp.per_event.get(event_id) or 0.0)
        rows.append(
            {
                "event_id": event_id,
                "taken_at": taken_at,
                "player_id": pid,
                "web_name": player.get("web_name"),
                "element_type": etype,
                "position": POSITION_LABELS.get(etype, str(etype)),
                "team_id": int(player.get("team") or 0),
                "placeholder": bool(xp.placeholder),
                "predicted": predicted,
                "predicted_components": components,
                "predicted_component_sum": round(sum(components.values()), 6),
                "ep_next": _ep_float(player, "ep_next"),
                "ep_this": _ep_float(player, "ep_this"),
                "blank": bool(event_break.get("blank")),
                "late": bool(late),
                "rate_source": xp.breakdown.get("rate_source"),
                "shrinkage": shrinkage.as_dict(),
                "variant": shrinkage.variant_slug(),
                "breakdown": event_break,
            }
        )
    meta = {
        "event_id": event_id,
        "taken_at": taken_at,
        "players": len(rows),
        "placeholder": ctx.features is None,
        "late": bool(late),
        "deadline_time": deadline_time,
        "first_kickoff": first_kickoff,
        "shrinkage": shrinkage.as_dict(),
        "variant": shrinkage.variant_slug(),
    }
    return rows, meta


def build_snapshot(
    event_id: int,
    *,
    sync: bool = False,
    shrinkage: ShrinkageConfig | None = None,
    late: bool = False,
    deadline_time: str | None = None,
    first_kickoff: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if sync:
        sync_fpl()
        sync_understat()
    ctx = load_model_context(shrinkage=shrinkage)
    if event_id <= 0:
        ids = horizon_event_ids(ctx.bootstrap, 1)
        if not ids:
            raise ValueError("no upcoming gameweek in bootstrap")
        event_id = ids[0]
    return snapshot_rows(
        ctx,
        event_id,
        late=late,
        deadline_time=deadline_time,
        first_kickoff=first_kickoff,
    )
