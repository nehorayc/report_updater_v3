from __future__ import annotations

from graph_ranking import build_ranked_graph_candidate_group


def test_ranked_graph_candidates_prefer_log_scale_for_extreme_ratios():
    group = build_ranked_graph_candidate_group(
        {
            "id": "densityslot111111111111111111111111",
            "marker_id": "densityslot111111111111111111111111",
            "type": "graph",
            "title": "Storage density comparison",
            "description": "Compare DNA storage density with tape media.",
            "chart_type": "bar",
            "data_points": {
                "labels": ["Synthetic DNA", "LTO-9 Tape"],
                "values": [215000000, 45],
                "unit": "TB per gram",
            },
        },
        chapter_title="Quantitative Analysis",
        draft_text=(
            "DNA storage density is far higher than tape, but the graph needs to keep both values visible.\n\n"
            "[Figure densityslot111111111111111111111111: Storage density comparison]"
        ),
        chapter_role="quantitative analysis",
    )

    shortlist = group["shortlist"]

    assert shortlist
    assert shortlist[0]["y_axis_scale"] == "log"
    assert shortlist[0]["scorecard"]["overall_score"] > shortlist[-1]["scorecard"]["overall_score"]
    assert group["selection_mode"] in {"auto", "manual"}


def test_ranked_graph_candidates_block_invalid_update_graphs():
    group = build_ranked_graph_candidate_group(
        {
            "id": "feed2023aa1111111111111111111111",
            "marker_id": "feed2023aa1111111111111111111111",
            "original_asset_id": "feed2023aa1111111111111111111111",
            "type": "graph",
            "title": "Invalid updated graph",
            "description": "This update drifts from the preserved history.",
            "chart_type": "bar",
            "update_end_date": "2026-03-22",
            "extracted_data_points": {
                "labels": ["2020", "2021", "2022", "2023"],
                "values": [42, 58, 79, 101],
                "unit": "Thousand Units",
            },
            "data_points": {
                "labels": ["2020", "2021", "2022", "2023", "2024", "2025"],
                "values": [45, 58, 79, 101, 120, 185],
                "unit": "Thousand Units",
            },
        },
        chapter_title="Quantitative Analysis",
        draft_text="[Figure feed2023aa1111111111111111111111: Invalid updated graph]",
        chapter_role="quantitative analysis",
    )

    assert group["selection_mode"] == "skip"
    assert group["shortlist"][0]["blocked"] is True
    assert any("preserved historical values" in reason.lower() for reason in group["shortlist"][0]["blocked_reasons"])


def test_ranked_graph_candidates_canonicalize_dataset_payloads():
    group = build_ranked_graph_candidate_group(
        {
            "id": "annualcounts1111111111111111111111",
            "marker_id": "annualcounts1111111111111111111111",
            "type": "graph",
            "title": "Annual articles and patents",
            "description": "Track annual output through the update window.",
            "chart_type": "line",
            "data_points": {
                "labels": ["2024", "2025", "2026"],
                "datasets": [
                    {"label": "Articles", "values": [120, 155, 190], "unit": "Count"},
                    {"label": "Patents", "data": [14, 19, 28], "unit": "Count"},
                ],
            },
        },
        chapter_title="Research Activity",
        draft_text="[Figure annualcounts1111111111111111111111: Annual articles and patents]",
        chapter_role="quantitative analysis",
    )

    candidate = group["shortlist"][0]

    assert candidate["blocked"] is False
    assert candidate["data_points"]["values"]["Articles"] == [120, 155, 190]
    assert candidate["data_points"]["values"]["Patents"] == [14, 19, 28]


def test_ranked_graph_candidates_attach_best_graphable_question():
    group = build_ranked_graph_candidate_group(
        {
            "id": "patentslot11111111111111111111111",
            "marker_id": "patentslot11111111111111111111111",
            "type": "graph",
            "title": "Annual patent activity",
            "description": "Patent filings by year.",
            "chart_type": "line",
            "data_points": {
                "labels": ["2021", "2022", "2023", "2024"],
                "values": [14, 19, 28, 41],
                "unit": "Count",
            },
        },
        chapter_title="Quantitative Analysis",
        draft_text="[Figure patentslot11111111111111111111111: Annual patent activity]",
        chapter_role="quantitative analysis",
        graphable_questions=[
            {
                "graph_question_id": "gq_1",
                "question_text": "How has annual patent activity changed from 2021 to 2024?",
                "question_type": "trend",
                "candidate_metric": "Annual patent activity",
                "target_claim_text": "Patent filings increased each year.",
                "preferred_chart_families": ["line", "bar"],
                "graphable": True,
            },
            {
                "graph_question_id": "gq_2",
                "question_text": "How is project maturity distributed across TRL stages?",
                "question_type": "composition",
                "candidate_metric": "TRL distribution",
                "target_claim_text": "Projects span several TRL stages.",
                "preferred_chart_families": ["pie", "bar"],
                "graphable": True,
            },
        ],
    )

    assert group["graph_question_id"] == "gq_1"
    assert group["question_type"] == "trend"
    assert group["shortlist"][0]["blocked"] is False


def test_ranked_graph_candidates_block_graphs_without_vetted_question_match():
    group = build_ranked_graph_candidate_group(
        {
            "id": "workflowslot111111111111111111111",
            "marker_id": "workflowslot111111111111111111111",
            "type": "graph",
            "title": "Retrieval workflow stages",
            "description": "Pipeline stages for retrieval.",
            "chart_type": "bar",
            "data_points": {
                "labels": ["Ingest", "Decode", "Retrieve"],
                "values": [1, 2, 3],
                "unit": "Steps",
            },
        },
        chapter_title="Quantitative Analysis",
        draft_text="[Figure workflowslot111111111111111111111: Retrieval workflow stages]",
        chapter_role="quantitative analysis",
        graphable_questions=[
            {
                "graph_question_id": "gq_1",
                "question_text": "How has annual patent activity changed from 2021 to 2024?",
                "question_type": "trend",
                "candidate_metric": "Annual patent activity",
                "target_claim_text": "Patent filings increased each year.",
                "preferred_chart_families": ["line", "bar"],
                "graphable": True,
            }
        ],
    )

    assert group["selection_mode"] == "skip"
    assert group["shortlist"][0]["blocked"] is True
    assert any("vetted graphable question" in reason.lower() for reason in group["shortlist"][0]["blocked_reasons"])
