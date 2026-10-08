"""Entrada para ejecutar el Dev Explorer desde la raíz del repositorio."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from football_data_hub.dev_explorer.app import main  # noqa: E402


main()
