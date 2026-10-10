"""Central competition identity for the supported BDFutbol season/groups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SUPPORTED_SEASON = "2026-27"
CompetitionGroup = Literal[1, 2]
_TAB_BY_SECTION = {
    "results": "results",
    "top": "top",
    "statistics": "stats",
    "referees": "referees",
}


@dataclass(frozen=True, slots=True)
class CompetitionContext:
    competition: str
    season: str
    group_number: CompetitionGroup
    bdfutbol_code: str
    group_roman: str
    group_label: str
    group_key: str
    base_url: str

    @property
    def season_label(self) -> str:
        return self.season.replace("-", "/")

    def section_url(self, section: str) -> str:
        if section == "classification":
            return self.base_url
        try:
            tab = _TAB_BY_SECTION[section]
        except KeyError as exc:
            raise ValueError(f"Sección BDFutbol no admitida: {section!r}") from exc
        return f"{self.base_url}?tab={tab}"

    def referee_scope_url(self, group_number: CompetitionGroup) -> str:
        target = get_competition_context(self.season, group_number)
        return f"{target.section_url('referees')}&grups=1"

    def export_directory(self, root: Path, section: str) -> Path:
        if section not in {"classification", "top", "statistics"}:
            raise ValueError(f"Sección de export no admitida: {section!r}")
        return root / f"{self.group_key}_{section}"


def get_competition_context(
    season: str = SUPPORTED_SEASON,
    group: int = 2,
) -> CompetitionContext:
    """Resolve season/group into one immutable source and export identity."""
    if season != SUPPORTED_SEASON:
        raise ValueError(f"Solo está habilitada la temporada {SUPPORTED_SEASON}")
    if group not in (1, 2):
        raise ValueError("El grupo debe ser 1 o 2")
    roman = "I" if group == 1 else "II"
    key = f"group{group}"
    code = f"1rf{group}"
    base_url = f"https://www.bdfutbol.com/es/t/t{season}{code}.html"
    return CompetitionContext(
        competition="Primera Federación",
        season=season,
        group_number=group,  # type: ignore[arg-type]
        bdfutbol_code=code,
        group_roman=roman,
        group_label=f"Grupo {roman}",
        group_key=key,
        base_url=base_url,
    )
