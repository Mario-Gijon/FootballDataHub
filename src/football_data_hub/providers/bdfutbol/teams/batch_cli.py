"""Sequential, resumable command for future one-team-at-a-time acquisitions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from football_data_hub.core.browser_runtime import BrowserRuntimeError
from football_data_hub.core.browser_session import BrowserSessionError
from football_data_hub.providers.bdfutbol.context import SUPPORTED_SEASON, get_competition_context
from football_data_hub.providers.bdfutbol.access import AccessStatus

from .acquisition import DEFAULT_VIEWS, TeamAcquisitionStopped, acquire_team_profile
from .batch import (
    BatchAccessDenied,
    BatchStop,
    BatchTeamOutcome,
    find_valid_capture,
    run_team_batch,
    write_batch_manifest,
)
from .catalog import load_team_catalog
from .cli import _DEFAULT_MATCH_CATALOGS, _reuse_capture_seed
from .export import export_team_capture


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=(SUPPORTED_SEASON,), default=SUPPORTED_SEASON)
    parser.add_argument("--groups", choices=("I", "II", "both"), default="both")
    parser.add_argument("--view", action="append", choices=tuple(DEFAULT_VIEWS))
    parser.add_argument("--group1-catalog", type=Path)
    parser.add_argument("--group2-catalog", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("data/exports/bdfutbol/teams"))
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get("FDH_BDFUTBOL_PROFILE", str(Path.home() / ".football-data-hub-chromium-pure-cdp"))),
    )
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--startup-timeout-seconds", type=float, default=35.0)
    parser.add_argument("--navigation-timeout-ms", type=int, default=45_000)
    parser.add_argument("--no-xvfb", action="store_false", dest="use_xvfb")
    parser.set_defaults(use_xvfb=True)
    return parser.parse_args(argv)


def _catalog_path(args: argparse.Namespace, group: int) -> Path:
    supplied = args.group1_catalog if group == 1 else args.group2_catalog
    if supplied:
        return supplied
    env = os.environ.get(f"FDH_BDFUTBOL_GROUP{group}_MATCHES") or os.environ.get(f"FDH_GROUP{group}_MATCHES")
    return Path(env).expanduser() if env else _DEFAULT_MATCH_CATALOGS[group]


def _latest_seed_dir(
    output_root: Path,
    season: str,
    team_id: int,
    *,
    team_catalog_record: dict,
    competition,
) -> Path | None:
    team_root = output_root.expanduser() / season / str(team_id)
    if not team_root.is_dir():
        return None
    candidates = []
    for path in team_root.iterdir():
        metadata_path = path / "metadata" / "capture.json"
        if not path.is_dir() or not metadata_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if any(item.get("access_status") == "VALID" for item in metadata.get("source_snapshots", {}).values()):
                candidates.append((str(metadata.get("created_at_utc") or metadata.get("capture_id")), path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    for _, candidate in sorted(candidates, reverse=True):
        try:
            _reuse_capture_seed(
                candidate,
                team_catalog_record=team_catalog_record,
                competition=competition,
            )
            return candidate
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    groups = (1, 2) if args.groups == "both" else ((1,) if args.groups == "I" else (2,))
    selected_views = tuple(dict.fromkeys(args.view)) if args.view else DEFAULT_VIEWS
    output_root = args.output_root.expanduser()
    team_records = {}
    matches_by_group = {}
    references = {}
    for group in groups:
        context = get_competition_context(args.season, group)
        team_records[group], matches_by_group[group], references[group] = load_team_catalog(
            _catalog_path(args, group), competition=context
        )

    def complete(group: int, team_id: int, views: tuple[str, ...]) -> str | None:
        found = find_valid_capture(output_root, season=args.season, team_id=team_id, required_views=views)
        return found[0] if found else None

    def partial(group: int, team_id: int) -> str | None:
        record = next(team for team in team_records[group] if int(team["team_id"]) == team_id)
        context = get_competition_context(args.season, group)
        seed_dir = _latest_seed_dir(
            output_root,
            args.season,
            team_id,
            team_catalog_record=record,
            competition=context,
        )
        if seed_dir is None:
            return None
        try:
            metadata = json.loads((seed_dir / "metadata" / "capture.json").read_text(encoding="utf-8"))
            context = get_competition_context(args.season, group)
            record = next(team for team in team_records[group] if int(team["team_id"]) == team_id)
            _reuse_capture_seed(seed_dir, team_catalog_record=record, competition=context)
            return str(metadata.get("capture_id"))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None

    def process(group: int, record: dict, views: tuple[str, ...]) -> BatchTeamOutcome:
        context = get_competition_context(args.season, group)
        seed_dir = _latest_seed_dir(
            output_root,
            args.season,
            int(record["team_id"]),
            team_catalog_record=record,
            competition=context,
        )
        seed = _reuse_capture_seed(
            seed_dir,
            team_catalog_record=record,
            competition=context,
        ) if seed_dir else None
        requested = tuple(dict.fromkeys(views if seed and "alignment" in seed["raw_views"] else ("alignment", *views)))
        to_acquire = tuple(view for view in requested if seed is None or view not in seed["raw_views"])
        try:
            bundle = acquire_team_profile(
                team_catalog_record=record,
                team_catalog_reference=references[group],
                group_team_catalog=team_records[group],
                known_matches=matches_by_group[group],
                competition=context,
                profile_dir=args.profile,
                requested_views=to_acquire,
                browser="chromium",
                browser_executable_path=args.browser_executable,
                startup_timeout_seconds=args.startup_timeout_seconds,
                navigation_timeout_ms=args.navigation_timeout_ms,
                use_xvfb=args.use_xvfb,
                seed_raw_views=(seed or {}).get("raw_views"),
                seed_access_by_view=(seed or {}).get("access_by_view"),
                seed_view_urls=(seed or {}).get("view_urls"),
                seed_page_titles=(seed or {}).get("page_titles"),
                seed_browser=(seed or {}).get("browser"),
                seed_capture_id=(seed or {}).get("capture_id"),
            )
        except TeamAcquisitionStopped as exc:
            if exc.assessment.status is AccessStatus.CHALLENGE_REQUIRED:
                raise BatchAccessDenied(str(exc), kind="challenge_required") from exc
            if exc.assessment.status is AccessStatus.HTTP_ERROR:
                kind = "http_denial" if exc.assessment.http_status in {401, 403, 407, 429} else "http_error"
                raise BatchStop(str(exc), kind=kind) from exc
            if exc.assessment.status is AccessStatus.NAVIGATION_ERROR:
                raise BatchStop(str(exc), kind="navigation_error") from exc
            raise
        except (BrowserRuntimeError, BrowserSessionError) as exc:
            raise BatchStop(f"{type(exc).__name__}: {exc}", kind="browser_environment_error") from exc
        try:
            paths = export_team_capture(
                output_root,
                bundle,
                profile_dir=args.profile,
                capture_timestamp_basis="browser navigation capture time; reused views retain per-view source timestamps",
            )
        except OSError as exc:
            raise BatchStop(f"{type(exc).__name__}: {exc}", kind="storage_error") from exc
        return BatchTeamOutcome(
            capture_id=bundle.capture_id,
            views=bundle.requested_views,
            valid=bool(bundle.validation.get("valid")) and paths["run_directory"].is_dir(),
        )

    manifest = run_team_batch(
        teams_by_group={group: team_records[group] for group in groups},
        groups=groups,
        requested_views=selected_views,
        find_complete_capture=complete,
        find_partial_capture=partial,
        process_team=process,
    )
    manifest["season"] = args.season
    manifest["source"] = "BDFutbol"
    manifest_path = write_batch_manifest(output_root / args.season, manifest)
    print(json.dumps({"manifest": str(manifest_path), "summary": manifest["summary"], "stopped_on_access_denial": manifest["stopped_on_access_denial"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
