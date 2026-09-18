from __future__ import annotations

import argparse
import json
import sys

from fpl_analyser.clients.auth import FplAuthClient, build_auth_client
from fpl_analyser.clients.fpl import FplClient
from fpl_analyser.ingest.store import JsonCache
from fpl_analyser.ingest.sync import default_cache, sync_fpl, sync_understat
from fpl_analyser.squad import load_manager_squad
from fpl_analyser.transfers.rank import rank_replacements
from fpl_analyser.xp.model import ModelContext


def _client() -> FplClient:
    return FplClient(cache=default_cache())


def cmd_sync(args: argparse.Namespace) -> int:
    fpl_stats = sync_fpl(_client())
    us_stats = sync_understat()
    print("FPL", json.dumps(fpl_stats, default=str))
    print("Understat", json.dumps(us_stats, default=str))
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
    bootstrap = client.bootstrap_static()
    squad = load_manager_squad(
        client,
        args.entry,
        budget_remaining=args.bank,
        auth_client=_auth(args),
    )
    options = rank_replacements(
        squad,
        bootstrap,
        horizon=args.horizon,
        context=ModelContext(bootstrap=bootstrap),
        limit=args.limit,
    )
    print(
        f"Top {len(options)} 1-for-1 options over {args.horizon} GW "
        "(placeholder xP from FPL ep_next)"
    )
    for option in options:
        print(
            f"  {option.out_name} -> {option.in_name}  delta {option.delta:+.2f}  "
            f"in_xP {option.incoming_horizon_xp:.2f}  bank_after £{option.bank_after / 10:.1f}  "
            f"[{option.price_source.value}]"
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

    rec = sub.add_parser("recommend", help="Rank 1-for-1 transfers (placeholder xP)")
    rec.add_argument("--entry", type=int, required=True)
    rec.add_argument("--horizon", type=int, default=1)
    rec.add_argument("--limit", type=int, default=20)
    rec.add_argument("--bank", type=float, default=None)
    rec.add_argument("--api-token", default=None)
    rec.add_argument("--session-cookie", default=None)
    rec.set_defaults(func=cmd_recommend)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
