from importlib import import_module


def test_browser_foundation_modules_import() -> None:
    modules = (
        "football_data_hub",
        "football_data_hub.core",
        "football_data_hub.core.browser_runtime",
        "football_data_hub.core.browser_session",
        "football_data_hub.providers",
        "football_data_hub.providers.bdfutbol",
        "football_data_hub.providers.bdfutbol.access",
    )

    for module in modules:
        assert import_module(module).__file__ is not None
