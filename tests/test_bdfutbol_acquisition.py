from pathlib import Path

import pytest

from football_data_hub.bdfutbol.acquisition import BDFutbolAcquirer


def test_safe_name_normalizes_path_characters() -> None:
    assert BDFutbolAcquirer._safe_name("group 2 / competition") == (
        "group_2_competition"
    )


def test_safe_name_rejects_empty_value() -> None:
    with pytest.raises(ValueError):
        BDFutbolAcquirer._safe_name("../../")


def test_constructor_rejects_zero_attempts(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BDFutbolAcquirer(project_root=tmp_path, max_attempts=0)
