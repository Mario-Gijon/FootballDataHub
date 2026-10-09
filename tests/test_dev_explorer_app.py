from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_navigation_opens_club_history_without_exceptions() -> None:
    app_path = Path(__file__).parents[1] / "src" / "football_data_hub" / "dev_explorer" / "app.py"
    app = AppTest.from_file(str(app_path)).run(timeout=90)
    assert not app.exception

    app.sidebar.radio[0].set_value("Clubes")
    app.run(timeout=90)

    assert not app.exception
    assert any(item.value == "Clubes" for item in app.title)
    assert any(item.label == "Club participante" for item in app.selectbox)
