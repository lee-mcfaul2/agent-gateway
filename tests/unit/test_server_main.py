from __future__ import annotations


def test_imports() -> None:
    from ag_gateway.server import main

    assert callable(main)


def test_main_module_runnable() -> None:
    import importlib

    mod = importlib.import_module("ag_gateway.__main__")
    assert hasattr(mod, "main")
