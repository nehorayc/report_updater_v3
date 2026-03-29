from asset_selection_helpers import (
    asset_selection_widget_key,
    build_asset_to_chapters,
    initialize_asset_selection_state,
    selected_asset_ids_from_widget_state,
)


def test_build_asset_to_chapters_tracks_shared_assets():
    chapters = [
        {"asset_ids": ["asset-1", "asset-2"]},
        {"asset_ids": ["asset-2", "asset-3"]},
        {"asset_ids": []},
    ]

    mapping = build_asset_to_chapters(chapters)

    assert mapping == {
        "asset-1": ["Chapter 1"],
        "asset-2": ["Chapter 1", "Chapter 2"],
        "asset-3": ["Chapter 2"],
    }


def test_initialize_asset_selection_state_preserves_existing_widget_choices():
    assets = [{"id": "asset-1"}, {"id": "asset-2"}]
    session_state = {asset_selection_widget_key("asset-1"): False}

    initialize_asset_selection_state(assets, ["asset-1", "asset-2"], session_state)

    assert session_state[asset_selection_widget_key("asset-1")] is False
    assert session_state[asset_selection_widget_key("asset-2")] is True


def test_selected_asset_ids_from_widget_state_uses_canonical_keys_once():
    assets = [{"id": "asset-1"}, {"id": "asset-2"}, {"id": "asset-1"}]
    session_state = {
        asset_selection_widget_key("asset-1"): True,
        asset_selection_widget_key("asset-2"): False,
    }

    selected_ids = selected_asset_ids_from_widget_state(assets, session_state)

    assert selected_ids == ["asset-1"]
