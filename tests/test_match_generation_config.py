from __future__ import annotations

from football_data_hub_api.config import ApiSettings


def test_api_defaults_to_explicit_active_pointer_when_present(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "football-data"
    pointer = data_root / "matches/active-generation.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("FDH_LOCAL_DATA_ROOT", str(data_root))
    monkeypatch.delenv("FDH_MATCH_GENERATION_ROOT", raising=False)

    assert ApiSettings.from_env().match_generation_root == data_root / "matches"


def test_api_keeps_legacy_pinned_generation_when_no_active_pointer_exists(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "football-data"
    monkeypatch.setenv("FDH_LOCAL_DATA_ROOT", str(data_root))
    monkeypatch.delenv("FDH_MATCH_GENERATION_ROOT", raising=False)

    assert ApiSettings.from_env().match_generation_root == (
        data_root / "matches/generations/match-00-4ad1d610507e425d"
    )


def test_explicit_match_generation_configuration_takes_precedence(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "football-data"
    pointer = data_root / "matches/active-generation.json"
    pointer.parent.mkdir(parents=True)
    pointer.touch()
    explicit = tmp_path / "operator-selected-generation"
    monkeypatch.setenv("FDH_LOCAL_DATA_ROOT", str(data_root))
    monkeypatch.setenv("FDH_MATCH_GENERATION_ROOT", str(explicit))

    assert ApiSettings.from_env().match_generation_root == explicit
