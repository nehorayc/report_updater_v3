from __future__ import annotations

from visual_pipeline_helpers import (
    build_figure_marker,
    place_marker_near_relevant_paragraph,
    resolve_visual_for_export,
)


def test_place_marker_near_relevant_paragraph_prefers_contextual_match():
    text = (
        "DNA data storage remains a long-horizon archival technology with high synthesis costs.\n\n"
        "The workflow moves from encoding into synthesis, storage, sequencing, and decoding, "
        "with operational bottlenecks concentrated in writing and retrieval.\n\n"
        "Commercial adoption still depends on better throughput and lower error rates."
    )
    visual = {
        "title": "DNA Storage Lifecycle Overview",
        "description": "Workflow across encoding, synthesis, storage, sequencing, and decoding",
        "query": "dna storage lifecycle workflow diagram",
        "source_context_excerpt": "The workflow moves from encoding into synthesis, storage, sequencing, and decoding.",
    }

    updated_text, placement_mode = place_marker_near_relevant_paragraph(
        text,
        build_figure_marker("feedface1234", "DNA Storage Lifecycle Overview"),
        visual,
    )

    expected_block = (
        "The workflow moves from encoding into synthesis, storage, sequencing, and decoding, "
        "with operational bottlenecks concentrated in writing and retrieval.\n\n"
        "[Figure feedface1234: DNA Storage Lifecycle Overview]"
    )
    assert placement_mode == "contextual"
    assert expected_block in updated_text
    assert not updated_text.rstrip().endswith("[Figure feedface1234: DNA Storage Lifecycle Overview]")


def test_place_marker_near_relevant_paragraph_falls_back_to_chapter_end_without_match():
    text = (
        "The chapter discusses regulation, funding, and market timing.\n\n"
        "No paragraph here describes a lab workflow or technical lifecycle."
    )
    visual = {
        "title": "Satellite imagery of launch infrastructure",
        "description": "Orbital launch pad photo",
        "query": "space launch photo",
    }

    updated_text, placement_mode = place_marker_near_relevant_paragraph(
        text,
        build_figure_marker("deadbeef1234", "Satellite imagery of launch infrastructure"),
        visual,
    )

    assert placement_mode == "chapter_end"
    assert updated_text.rstrip().endswith("[Figure deadbeef1234: Satellite imagery of launch infrastructure]")


def test_resolve_visual_for_export_uses_placeholder_fallback_for_images():
    recorded_calls = []

    def fake_search(query, **kwargs):
        recorded_calls.append((query, kwargs))
        return {"path": "/tmp/placeholder.png", "provider": "placeholder"}

    result = resolve_visual_for_export(
        {"type": "image", "title": "DNA workflow schematic"},
        generate_graph_fn=lambda visual: {"path": "/tmp/graph.png"},
        search_image_fn=fake_search,
    )

    assert result["provider"] == "placeholder"
    assert recorded_calls == [("DNA workflow schematic", {"allow_placeholder_fallback": True})]


def test_resolve_visual_for_export_routes_graphs_to_graph_generator():
    recorded_visuals = []

    def fake_generate_graph(visual):
        recorded_visuals.append(visual)
        return {"path": "/tmp/graph.png", "provider": "graph"}

    result = resolve_visual_for_export(
        {"type": "graph", "title": "Adoption horizon by user category"},
        generate_graph_fn=fake_generate_graph,
        search_image_fn=lambda query, **kwargs: {"path": "/tmp/image.png"},
    )

    assert result["provider"] == "graph"
    assert recorded_visuals == [{"type": "graph", "title": "Adoption horizon by user category"}]
