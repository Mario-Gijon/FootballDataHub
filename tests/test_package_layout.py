from importlib import import_module


def test_v2_package_skeleton_imports() -> None:
    modules = (
        "football_data_hub",
        "football_data_hub.core",
        "football_data_hub.providers",
        "football_data_hub.providers.bdfutbol",
        "football_data_hub.collectors",
        "football_data_hub.parsers",
        "football_data_hub.schemas",
        "football_data_hub.storage",
        "football_data_hub.orchestration",
    )

    for module in modules:
        assert import_module(module).__file__ is not None
