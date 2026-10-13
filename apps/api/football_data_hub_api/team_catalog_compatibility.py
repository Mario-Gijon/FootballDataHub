"""Historical team-capture catalog verification for published API profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.context import get_competition_context
from football_data_hub.providers.bdfutbol.teams.capture_store import compare_catalog_versions
from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog

from .config import PROJECT_ROOT


class TeamCatalogCompatibilityError(ValueError):
    """A profile's original catalog cannot be verified against the active one."""


def verify_team_catalog_compatibility(
    capture_metadata: dict[str, Any],
    *,
    matches_path: Path,
    group: str,
    season: str,
    active_capture_id: str | None = None,
) -> dict[str, Any]:
    """Verify the exact historical catalog hash and stable match identities.

    Results and statuses may advance between snapshots. Team IDs and each
    shared match's ID, matchday, home team, and away team may not change.
    """
    group_number = {"I": 1, "II": 2}.get(group)
    if group_number is None:
        raise TeamCatalogCompatibilityError("El grupo del perfil no es válido.")
    source_reference = capture_metadata.get("related_team_catalog")
    if not isinstance(source_reference, dict):
        raise TeamCatalogCompatibilityError("La captura no referencia su catálogo original.")
    if source_reference.get("group") != group or source_reference.get("season") != season:
        raise TeamCatalogCompatibilityError("El catálogo original pertenece a otro grupo o temporada.")

    competition = get_competition_context(group=group_number)
    try:
        active_teams, active_matches, active_reference = load_team_catalog(
            matches_path, competition=competition
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise TeamCatalogCompatibilityError(f"No se pudo verificar el catálogo activo: {exc}") from exc
    if active_capture_id and active_reference.get("source_capture_id") != active_capture_id:
        raise TeamCatalogCompatibilityError("El catálogo activo no coincide con el bootstrap de la API.")

    historical_path_value = source_reference.get("path")
    if not isinstance(historical_path_value, str) or not historical_path_value:
        raise TeamCatalogCompatibilityError("Falta la ruta del catálogo original.")
    historical_path = Path(historical_path_value).expanduser()
    if not historical_path.is_absolute():
        historical_path = PROJECT_ROOT / historical_path
    try:
        source_teams, source_matches, loaded_source_reference = load_team_catalog(
            historical_path, competition=competition
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise TeamCatalogCompatibilityError(f"No se pudo verificar el catálogo histórico original: {exc}") from exc

    for key in ("group", "season", "source_capture_id", "source_captured_at_utc", "sha256"):
        if source_reference.get(key) != loaded_source_reference.get(key):
            raise TeamCatalogCompatibilityError(
                f"La referencia histórica no coincide con el catálogo original ({key})."
            )

    comparison = compare_catalog_versions(
        source_reference=loaded_source_reference,
        source_teams=source_teams,
        source_matches=source_matches,
        active_reference=active_reference,
        active_teams=active_teams,
        active_matches=active_matches,
    )
    if not comparison["compatible"]:
        raise TeamCatalogCompatibilityError(
            "El catálogo histórico no es compatible con el activo: "
            f"faltan partidos={comparison['match_ids_missing']}; "
            f"conflictos de identidad={comparison['identity_conflicts']}; "
            f"IDs de equipo conservados={comparison['team_ids_conserved']}."
        )
    return comparison
