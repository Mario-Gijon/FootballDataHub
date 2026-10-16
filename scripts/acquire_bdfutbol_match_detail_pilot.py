"""Offline preflight by default; real acquisition requires two explicit confirmations."""

from football_data_hub.providers.bdfutbol.match_details.pilot_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
