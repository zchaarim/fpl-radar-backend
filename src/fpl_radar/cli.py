from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from fpl_radar.clients.auth import FplAuthClient, build_auth_client
from fpl_radar.clients.fpl import FplClient
from fpl_radar.features import availability_note, rank_xgi_rates
from fpl_radar.fpl_rules import POSITION_LABELS, POSITION_ORDER
from fpl_radar.identity.match import identity_coverage
from fpl_radar.ingest.sync import default_cache, load_model_context, sync_fpl, sync_understat
from fpl_radar.models import TransferOption
from fpl_radar.squad import load_manager_squad
from fpl_radar.transfers.rank import rank_replacements
from fpl_radar.xp.model import expected_points, horizon_event_ids, rank_horizon_xp


def _client() -> FplClient:
    return FplClient(cache=default_cache())


def cmd_sync(args: argparse.Namespace) -> int:
    fpl_stats = sync_fpl(_client())
    us_stats = sync_understat()
    ctx = load_model_context(_client())
    print("FPL", json.dumps(fpl_stats, default=str))
    print("Understat", json.dumps(us_stats, default=str))
    coverage = identity_coverage(
        ctx.bootstrap.get("elements") or [],
        (ctx.understat_league or {}).get("players") or [],
        ctx.player_match,
    )
    print(
        "Identity "
        f"matched {coverage['matched']}/{coverage['understat_players']} Understat players; "
        f"FPL roster {coverage['matched']}/{coverage['fpl_players']} "
        f"(unmatched with minutes: FPL {coverage['unmatched_fpl_with_minutes']}, "
        f"Understat {coverage['unmatched_understat_with_minutes']})"
    )
    return 0


def _auth(args: argparse.Namespace) -> FplAuthClient | None:
    return build_auth_client(
        api_token=getattr(args, "api_token", None),
        session_cookie=getattr(args, "session_cookie", None),
    )


def cmd_squad(args: argparse.Namespace) -> int:
    client = _client()
    squad = load_manager_squad(
        client,
        args.entry,
        budget_remaining=args.bank,
        auth_client=_auth(args),
    )
    ctx = load_model_context(client)
    event_ids = horizon_event_ids(ctx.bootstrap, args.horizon)
    players_by_id = {int(p["id"]): p for p in ctx.bootstrap.get("elements") or []}
    teams = {int(t["id"]): t.get("short_name") for t in ctx.bootstrap.get("teams") or []}
    source = "minutes + xGI + CS/GC + DefCon + bonus + saves + cards"
    if ctx.features is None:
        source = "placeholder xP from FPL ep_next"
    print(
        f"Entry {squad.entry_id} {squad.name or ''} | event {squad.current_event} | "
        f"bank £{squad.bank / 10:.1f} ({squad.bank_source}) | auth={squad.authenticated}"
    )
    print(f"Squad xP over {args.horizon} GW ({source})")
    grouped: dict[int, list[Any]] = {etype: [] for etype in POSITION_ORDER}
    for player in squad.players:
        grouped.setdefault(player.element_type, []).append(player)

    def render(player) -> str:
        row = players_by_id.get(player.element_id) or {}
        club = teams.get(player.team_id, "?")
        xp = expected_points(player.element_id, event_ids, ctx)
        rates = (ctx.features.players.get(player.element_id) if ctx.features else None)
        xgi_txt = f"{rates.xgi90:5.2f}" if rates is not None else "  n/a"
        flag = availability_note(row)
        flag_txt = f"  ({flag})" if flag else ""
        return (
            f"  {player.web_name:16} {club:4} "
            f"buy {player.now_cost / 10:4.1f} paid {player.purchase_price / 10:4.1f} "
            f"sell {player.selling_price / 10:4.1f}  "
            f"xP {xp.horizon_sum:6.2f}  xGI/90 {xgi_txt}  "
            f"[{player.price_source.value}]{flag_txt}"
        )

    _print_position_blocks(grouped, render)
    return 0


def _print_position_blocks(rows_by_type: dict[int, list[Any]], render) -> None:
    for etype in POSITION_ORDER:
        block = rows_by_type.get(etype) or []
        print(f"{POSITION_LABELS[etype]}")
        if not block:
            print("  (none)")
            continue
        for row in block:
            print(render(row))


def cmd_recommend(args: argparse.Namespace) -> int:
    client = _client()
    squad = load_manager_squad(
        client,
        args.entry,
        budget_remaining=args.bank,
        auth_client=_auth(args),
    )
    ctx = load_model_context(client)
    options = rank_replacements(
        squad,
        ctx.bootstrap,
        horizon=args.horizon,
        context=ctx,
        limit=args.limit,
    )
    source = "minutes + xGI + CS/GC + DefCon + bonus + saves + cards"
    if options and options[0].placeholder:
        source = "placeholder xP from FPL ep_next"
    print(
        f"Top {args.limit} 1-for-1 options per position over {args.horizon} GW ({source})"
    )
    grouped: dict[int, list[TransferOption]] = {etype: [] for etype in POSITION_ORDER}
    for option in options:
        grouped.setdefault(option.element_type, []).append(option)

    def render(option: TransferOption) -> str:
        flags = []
        if option.out_flag:
            flags.append(f"out {option.out_flag}")
        if option.in_flag:
            flags.append(f"in {option.in_flag}")
        flag_txt = f"  ({'; '.join(flags)})" if flags else ""
        return (
            f"  {option.out_name} -> {option.in_name}  delta {option.delta:+.2f}  "
            f"in_xP {option.incoming_horizon_xp:.2f}  bank_after £{option.bank_after / 10:.1f}  "
            f"[{option.price_source.value}]{flag_txt}"
        )

    _print_position_blocks(grouped, render)
    return 0


def cmd_xp(args: argparse.Namespace) -> int:
    ctx = load_model_context(_client())
    if ctx.features is None:
        print("No feature set; run sync first.")
        return 1
    rows = rank_horizon_xp(ctx, horizon=args.horizon, limit_per_position=args.limit)
    teams = {int(t["id"]): t.get("short_name") for t in ctx.bootstrap.get("teams") or []}
    print(f"Top {args.limit} players per position by xP over {args.horizon} GW")
    grouped: dict[int, list[tuple[dict, Any]]] = {etype: [] for etype in POSITION_ORDER}
    for player, xp in rows:
        grouped.setdefault(int(player.get("element_type") or 0), []).append((player, xp))

    def render(row: tuple[dict, Any]) -> str:
        player, xp = row
        club = teams.get(int(player.get("team") or 0), "?")
        flag = availability_note(player)
        flag_txt = f"  ({flag})" if flag else ""
        return (
            f"  {(player.get('web_name') or str(player.get('id'))):16} {club:4} "
            f"{xp.horizon_sum:6.2f}{flag_txt}"
        )

    _print_position_blocks(grouped, render)
    return 0


def cmd_xgi(args: argparse.Namespace) -> int:
    ctx = load_model_context(_client())
    features = ctx.features
    if features is None:
        print("No feature set; run sync first.")
        return 1
    rows = rank_xgi_rates(
        ctx.bootstrap,
        features,
        limit_per_position=args.limit,
        min_minutes=args.min_minutes,
    )
    teams = {int(t["id"]): t.get("short_name") for t in ctx.bootstrap.get("teams") or []}
    matched = len(features.players) - len(features.unmatched_players)
    mins_note = f"  min minutes {args.min_minutes:g}" if args.min_minutes else ""
    print(
        f"Top {args.limit} players per position by xGI/90  "
        f"matched {matched}/{len(features.players)}{mins_note}"
    )
    grouped: dict[int, list[tuple[dict, Any]]] = {etype: [] for etype in POSITION_ORDER}
    for player, rates in rows:
        grouped.setdefault(int(player.get("element_type") or 0), []).append((player, rates))

    def render(row: tuple[dict, Any]) -> str:
        player, rates = row
        club = teams.get(int(player.get("team") or 0), "?")
        return (
            f"  {(player.get('web_name') or str(player.get('id'))):16} {club:4} "
            f"{rates.source:16} {rates.minutes:5.0f} {rates.xg90:6.2f} {rates.xa90:6.2f} "
            f"{rates.xgi90:6.2f} {rates.xg90_raw + rates.xa90_raw:6.2f} "
            f"{rates.bps_avg:5.1f} {rates.bonus_e:5.2f}"
        )

    print(
        f"  {'player':16} {'club':4} {'src':16} {'min':5} {'xG90':6} {'xA90':6} "
        f"{'xGI90':6} {'rawGI':6} {'BPS':5} {'bonE':5}"
    )
    _print_position_blocks(grouped, render)
    return 0


def _limit_help() -> str:
    return "Max rows per position (GKP, DEF, MID, FWD)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fpl-radar-backend")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="Pull FPL bootstrap/fixtures and Understat EPL data")
    sync.set_defaults(func=cmd_sync)

    squad = sub.add_parser("squad", help="Show reconstructed manager squad with xP and xGI")
    squad.add_argument("--entry", type=int, required=True)
    squad.add_argument("--horizon", type=int, default=1, help="Gameweeks of xP to sum")
    squad.add_argument("--bank", type=float, default=None, help="Override remaining budget in millions")
    squad.add_argument("--api-token", default=None, help="Bearer token from x-api-authorization")
    squad.add_argument("--session-cookie", default=None, help="Legacy pl_profile cookie if still present")
    squad.set_defaults(func=cmd_squad)

    rec = sub.add_parser("recommend", help="Rank 1-for-1 transfers by xP, top N per position")
    rec.add_argument("--entry", type=int, required=True)
    rec.add_argument("--horizon", type=int, default=1)
    rec.add_argument("--limit", type=int, default=10, help=_limit_help())
    rec.add_argument("--bank", type=float, default=None)
    rec.add_argument("--api-token", default=None)
    rec.add_argument("--session-cookie", default=None)
    rec.set_defaults(func=cmd_recommend)

    xp = sub.add_parser("xp", help="List players by expected points over a horizon, top N per position")
    xp.add_argument("--horizon", type=int, default=1)
    xp.add_argument("--limit", type=int, default=10, help=_limit_help())
    xp.set_defaults(func=cmd_xp)

    xgi = sub.add_parser("xgi", help="Show player xG/xA/xGI rates, top N per position")
    xgi.add_argument("--limit", type=int, default=10, help=_limit_help())
    xgi.add_argument(
        "--min-minutes",
        type=float,
        default=0.0,
        help="Drop players with fewer season minutes than this",
    )
    xgi.set_defaults(func=cmd_xgi)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
