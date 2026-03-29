from __future__ import annotations

from typing import Iterable, Mapping, MutableMapping


def asset_selection_widget_key(asset_id: str) -> str:
    return f"asset_select_{asset_id}"


def build_asset_to_chapters(chapters: Iterable[Mapping[str, object]]) -> dict[str, list[str]]:
    asset_to_chapters: dict[str, list[str]] = {}
    for chapter_index, chapter in enumerate(chapters, start=1):
        chapter_label = f"Chapter {chapter_index}"
        for raw_asset_id in chapter.get("asset_ids", []) or []:
            asset_id = str(raw_asset_id)
            asset_to_chapters.setdefault(asset_id, []).append(chapter_label)
    return asset_to_chapters


def initialize_asset_selection_state(
    assets: Iterable[Mapping[str, object]],
    selected_asset_ids: Iterable[str],
    session_state: MutableMapping[str, object],
) -> None:
    selected_ids = {str(asset_id) for asset_id in selected_asset_ids}
    for asset in assets:
        asset_id = str(asset["id"])
        widget_key = asset_selection_widget_key(asset_id)
        session_state.setdefault(widget_key, asset_id in selected_ids)


def selected_asset_ids_from_widget_state(
    assets: Iterable[Mapping[str, object]],
    session_state: Mapping[str, object],
) -> list[str]:
    selected_ids: list[str] = []
    seen_ids: set[str] = set()

    for asset in assets:
        asset_id = str(asset["id"])
        if asset_id in seen_ids:
            continue
        seen_ids.add(asset_id)

        widget_key = asset_selection_widget_key(asset_id)
        if bool(session_state.get(widget_key, False)):
            selected_ids.append(asset_id)

    return selected_ids
