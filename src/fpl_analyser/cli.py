from __future__ import annotations

import argparse
import json
import sys

from fpl_analyser.clients.auth import FplAuthClient, build_auth_client
from fpl_analyser.clients.fpl import FplClient
from fpl_analyser.ingest.sync import default_cache, load_model_context, sync_fpl, sync_understat
from fpl_analyser.squad import load_manager_squad
from fpl_analyser.transfers.rank import rank_replacements


def _client() -> FplClient:
    return FplClient(cache=default_cache())


def cmd_sync(args: argparse.Namespace) -> int:
    fpl_stats = sync_fpl(_client())
    us_stats = sync_understat()
    ctx = load_model_context(_client())
    matched = 0
    if ctx.features:
        matched = len(ctx.features.players) - len(ctx.features.unmatched_players)
    print("FPL", json.dumps(fpl_stats, default=str))
    print("Understat", json.dumps(us_stats, default=str))
    print(f"Identity player matches {matched}/{len((ctx.bootstrap.get('elements') or []))}")
    return 0


def _auth(args: argparse.Namespace) -> FplAuthClient | None:
    return build_auth_client(
        api_token=getattr(args, "api_token", None),
        session_cookie=getattr(args, "session_cookie", None),
    )


def cmd_squad(args: argparse.Namespace) -> int:
    squad = load_manager_squad(
        _client(),
        args.entry,
        budget_remaining=args.bank,
        auth_client=_auth(args),
    )
    print(
        f"Entry {squad.entry_id} {squad.name or ''} | event {squad.current_event} | "
        f"bank £{squad.bank / 10:.1f} ({squad.bank_source}) | auth={squad.authenticated}"
    )
    for player in squad.players:
        print(
            f"  {player.web_name:16} buy {player.now_cost / 10:4.1f} "
            f"paid {player.purchase_price / 10:4.1f} sell {player.selling_price / 10:4.1f} "
            f"[{player.price_source.value}]"
        )
    return 0


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
    print(f"Top {len(options)} 1-for-1 options over {args.horizon} GW ({source})")
    for option in options:
        print(
            f"  {option.out_name} -> {option.in_name}  delta {option.delta:+.2f}  "
            f"in_xP {option.incoming_horizon_xp:.2f}  bank_after £{option.bank_after / 10:.1f}  "
            f"[{option.price_source.value}]"
        )
    return 0


def cmd_xgi(args: argparse.Namespace) -> int:
    ctx = load_model_context(_client())
    features = ctx.features
    if features is None:
        print("No feature set; run sync first.")
        return 1
    names = {int(p["id"]): p.get("web_name") for p in ctx.bootstrap.get("elements") or []}
    teams = {int(t["id"]): t.get("short_name") for t in ctx.bootstrap.get("teams") or []}
    team_of = {int(p["id"]): int(p.get("team") or 0) for p in ctx.bootstrap.get("elements") or []}
    rows = [(rates.xgi90, eid, rates) for eid, rates in features.players.items()]
    rows.sort(reverse=True)
    matched = len(features.players) - len(features.unmatched_players)
    print(
        f"{'player':16} {'club':4} {'src':9} {'min':5} {'xG90':6} {'xA90':6} {'xGI90':6} "
        f"{'BPS':5} {'bonE':5}  matched {matched}/{len(features.players)}"
    )
    for _score, eid, rates in rows[: args.limit]:
        print(
            f"{(names.get(eid) or str(eid)):16} {(teams.get(team_of.get(eid, 0)) or '?'):4} "
            f"{rates.source:9} {rates.minutes:5.0f} {rates.xg90:6.2f} {rates.xa90:6.2f} "
            f"{rates.xgi90:6.2f} {rates.bps_avg:5.1f} {rates.bonus_e:5.2f}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fpl-analyser")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="Pull FPL bootstrap/fixtures and Understat EPL data")
    sync.set_defaults(func=cmd_sync)

    squad = sub.add_parser("squad", help="Show reconstructed manager squad")
    squad.add_argument("--entry", type=int, required=True)
    squad.add_argument("--bank", type=float, default=None, help="Override remaining budget in millions")
    squad.add_argument("--api-token", default=None, help="Bearer token from x-api-authorization")
    squad.add_argument("--session-cookie", default=None, help="Legacy pl_profile cookie if still present")
    squad.set_defaults(func=cmd_squad)

    rec = sub.add_parser("recommend", help="Rank 1-for-1 transfers by xGI-based xP")
    rec.add_argument("--entry", type=int, required=True)
    rec.add_argument("--horizon", type=int, default=1)
    rec.add_argument("--limit", type=int, default=20)
    rec.add_argument("--bank", type=float, default=None)
    rec.add_argument("--api-token", default=None)
    rec.add_argument("--session-cookie", default=None)
    rec.set_defaults(func=cmd_recommend)

    xgi = sub.add_parser("xgi", help="Show player xG/xA/xGI rates from Understat (FPL fallback)")
    xgi.add_argument("--limit", type=int, default=25)
    xgi.set_defaults(func=cmd_xgi)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
