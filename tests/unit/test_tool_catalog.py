from __future__ import annotations

from pathlib import Path

from ag_gateway.prompts.bundle_view import BundleView
from ag_gateway.tools.catalog import compute_available_tools

FIXTURE_BUNDLE = Path(__file__).parent.parent / "fixtures" / "bundle-v1"


def _view():
    return BundleView.from_bundle(FIXTURE_BUNDLE)


def test_subset_perms_returns_matching_tools():
    view = _view()
    tools = compute_available_tools(view, frozenset({"kb:read"}))
    assert "kb.search" in tools
    assert "kb.fetch" in tools
    assert "customer.search_customer" not in tools


def test_empty_perms_returns_only_no_perm_tools():
    view = _view()
    tools = compute_available_tools(view, frozenset())
    # All canonical tools have requires_permissions, so result should be empty.
    assert tools == []


def test_all_perms_returns_all_tools():
    view = _view()
    perms = frozenset({
        "kb:read", "audit:read", "customers:read", "orders:read",
        "customers:write", "transactions:tombstone",
    })
    tools = compute_available_tools(view, perms)
    assert "kb.search" in tools
    assert "customer.create_customer" in tools
    assert "transaction.tombstone_transaction" in tools


def test_output_is_sorted():
    view = _view()
    perms = frozenset({"kb:read", "audit:read"})
    tools = compute_available_tools(view, perms)
    assert tools == sorted(tools)
