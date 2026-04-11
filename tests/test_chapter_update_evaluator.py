from __future__ import annotations

import chapter_update_evaluator
from chapter_update_evaluator import evaluate_chapter_update


def _passing_fixture() -> tuple[str, str, list[dict], dict, list[dict]]:
    original_text = """
## Enterprise Adoption

Enterprises moved from pilots toward broader production deployments in 2023, but most spending remained concentrated in experimentation.

## Governance and Risk

Leaders emphasized data protection, model reliability, and internal oversight as the main constraints on adoption.
""".strip()

    generated_text = """
## Enterprise Adoption

By 2025, enterprise adoption moved beyond isolated pilots as Deloitte reported that 78% of surveyed organizations were increasing generative AI investment and scaling deployments into core workflows [1]. McKinsey's 2026 enterprise survey likewise described a shift toward broader operating-model redesign rather than narrow experimentation [2].

## Governance and Risk

The governance agenda also became more operational. IBM's 2025 research found that organizations were formalizing controls around model monitoring, data lineage, and risk review as deployments expanded [3]. That keeps the chapter anchored in enterprise rollout and oversight rather than treating adoption as a purely technical trend.
""".strip()

    research_findings = [
        {
            "title": "Deloitte State of Generative AI in the Enterprise 2025",
            "url": "https://example.com/deloitte-2025",
            "snippet": "Deloitte reported in 2025 that 78% of surveyed organizations expected to increase generative AI spending and scale deployment.",
            "published_date": "2025-07-01",
        },
        {
            "title": "McKinsey Global Survey on AI 2026",
            "url": "https://example.com/mckinsey-2026",
            "snippet": "McKinsey's 2026 survey found enterprises were redesigning workflows and governance as AI adoption expanded.",
            "published_date": "2026-02-10",
        },
        {
            "title": "IBM AI Governance Outlook 2025",
            "url": "https://example.com/ibm-2025",
            "snippet": "IBM research in 2025 highlighted data lineage, model monitoring, and oversight committees as key governance measures.",
            "published_date": "2025-09-10",
        },
    ]

    blueprint = {
        "topic": "Enterprise AI adoption and governance",
        "source_chapter_title": "Enterprise Adoption and Governance",
        "report_subject": "Enterprise AI",
        "update_start_date": "2024-01-01",
        "update_end_date": "2026-12-31",
    }

    references = [
        {"index": 1, "title": "Deloitte State of Generative AI in the Enterprise 2025", "url": "https://example.com/deloitte-2025", "category": "Web"},
        {"index": 2, "title": "McKinsey Global Survey on AI 2026", "url": "https://example.com/mckinsey-2026", "category": "Web"},
        {"index": 3, "title": "IBM AI Governance Outlook 2025", "url": "https://example.com/ibm-2025", "category": "Web"},
    ]
    return original_text, generated_text, research_findings, blueprint, references


def test_evaluate_chapter_update_passes_for_grounded_fresh_rewrite():
    original_text, generated_text, research_findings, blueprint, references = _passing_fixture()

    result = evaluate_chapter_update(
        original_text=original_text,
        generated_text=generated_text,
        research_findings=research_findings,
        blueprint=blueprint,
        references=references,
    )

    assert result["summary"]["passes"] is True
    assert result["summary"]["freshness_pass"] is True
    assert result["summary"]["style_preservation_pass"] is True
    assert result["summary"]["scope_preservation_pass"] is True
    assert result["summary"]["grounding_pass"] is True
    assert result["signals"]["new_update_window_years"] == [2025, 2026]
    assert result["scores"]["matched_reference_ratio"] == 1.0


def test_evaluate_chapter_update_flags_stale_rewrite_that_is_too_close_to_original():
    original_text, _, research_findings, blueprint, references = _passing_fixture()
    generated_text = """
## Enterprise Adoption

Enterprises moved from pilots toward broader production deployments in 2023, and spending remained concentrated in experimentation [1].

## Governance and Risk

Leaders emphasized data protection, model reliability, and internal oversight as the main constraints on adoption [2].
""".strip()

    result = evaluate_chapter_update(
        original_text=original_text,
        generated_text=generated_text,
        research_findings=research_findings,
        blueprint=blueprint,
        references=references[:2],
    )

    codes = {issue["code"] for issue in result["issues"]}

    assert result["summary"]["passes"] is False
    assert "insufficient_new_information" in codes
    assert "too_similar_to_original" in codes


def test_evaluate_chapter_update_flags_scope_and_structure_drift():
    original_text = """
## Marine Logistics

Ports were investing in berth capacity and intermodal coordination during 2023.

## Port Investment

The original chapter focused on shipping infrastructure, freight bottlenecks, and coastal terminal upgrades.
""".strip()

    generated_text = """
- AI assistants became common across office workflows in 2025 [1].
- Model providers announced new foundation models in 2026 [2].
- Enterprises debated chatbot procurement and developer tooling [3].
""".strip()

    research_findings = [
        {"title": "AI market outlook", "url": "https://example.com/a", "snippet": "Foundation model competition intensified in 2025 and 2026."},
        {"title": "Chatbot adoption survey", "url": "https://example.com/b", "snippet": "Enterprises scaled copilots and internal assistants."},
        {"title": "Developer tools report", "url": "https://example.com/c", "snippet": "AI developer tooling spending increased by 34%."},
    ]
    blueprint = {
        "topic": "Marine logistics",
        "source_chapter_title": "Marine Logistics",
        "report_subject": "Shipping infrastructure",
        "update_start_date": "2024-01-01",
        "update_end_date": "2026-12-31",
    }
    references = [
        {"index": 1, "title": "AI market outlook", "url": "https://example.com/a", "category": "Web"},
        {"index": 2, "title": "Chatbot adoption survey", "url": "https://example.com/b", "category": "Web"},
        {"index": 3, "title": "Developer tools report", "url": "https://example.com/c", "category": "Web"},
    ]

    result = evaluate_chapter_update(
        original_text=original_text,
        generated_text=generated_text,
        research_findings=research_findings,
        blueprint=blueprint,
        references=references,
    )

    codes = {issue["code"] for issue in result["issues"]}

    assert result["summary"]["passes"] is False
    assert "scope_drift" in codes
    assert "style_structure_drift" in codes


def test_evaluate_chapter_update_can_include_llm_judge(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("CHAPTER_UPDATE_JUDGE_MODEL", "gemini-3-flash-preview")

    class FakeResponse:
        text = """
        {
          "freshness_score": 0.88,
          "style_preservation_score": 0.84,
          "scope_preservation_score": 0.81,
          "evidence_grounding_score": 0.86,
          "contains_meaningful_new_information": true,
          "preserves_original_style": true,
          "preserves_original_scope": true,
          "is_well_grounded_in_findings": true,
          "reasoning_summary": "The rewritten chapter adds concrete 2025-2026 evidence while keeping the original enterprise-adoption structure.",
          "strengths": ["Uses recent data", "Keeps chapter scope"],
          "failures": []
        }
        """

    def fake_generate_content(*, api_key, model, contents, response_mime_type=None, temperature=None):
        assert api_key == "test-key"
        assert model == "gemini-3-flash-preview"
        assert response_mime_type == "application/json"
        assert "Original chapter" in contents
        assert "Generated chapter" in contents
        return FakeResponse()

    monkeypatch.setattr(chapter_update_evaluator, "gemini_generate_content", fake_generate_content)

    original_text, generated_text, research_findings, blueprint, references = _passing_fixture()
    result = evaluate_chapter_update(
        original_text=original_text,
        generated_text=generated_text,
        research_findings=research_findings,
        blueprint=blueprint,
        references=references,
        use_llm_judge=True,
    )

    assert result["summary"]["passes"] is True
    assert result["summary"]["llm_judge_pass"] is True
    assert result["llm_judge"]["passes"] is True
    assert result["llm_judge"]["preserves_original_style"] is True


def test_evaluate_chapter_update_flags_off_topic_citation():
    original_text = """
## DNA Storage

The original chapter focused on DNA-based archival storage systems and synthesis constraints.
""".strip()

    generated_text = """
## DNA Storage

Recent work in personalized nutrition demonstrates data-fusion opportunities for future storage systems [1].
""".strip()

    research_findings = [
        {
            "title": "Personalized nutrition: perspectives on challenges, opportunities, and guiding principles for data use and fusion",
            "url": "https://example.com/nutrition",
            "snippet": "A paper about personalized nutrition and data fusion.",
            "published_date": "2025-01-01",
            "directly_on_topic": False,
            "background_only": True,
            "cross_domain_analogy": True,
            "approved_for_writing": False,
        }
    ]
    blueprint = {
        "topic": "DNA digital data storage",
        "source_chapter_title": "DNA Storage",
        "report_subject": "DNA digital data storage",
        "update_start_date": "2024-01-01",
        "update_end_date": "2026-12-31",
    }
    references = [
        {
            "index": 1,
            "title": "Personalized nutrition: perspectives on challenges, opportunities, and guiding principles for data use and fusion",
            "url": "https://example.com/nutrition",
            "category": "Academic",
        }
    ]

    result = evaluate_chapter_update(
        original_text=original_text,
        generated_text=generated_text,
        research_findings=research_findings,
        blueprint=blueprint,
        references=references,
    )

    codes = {issue["code"] for issue in result["issues"]}
    assert "off_topic_citation" in codes
    assert result["summary"]["passes"] is False


def test_evaluate_chapter_update_flags_source_reinterpretation_drift():
    original_text, _, research_findings, blueprint, references = _passing_fixture()
    generated_text = """
## Enterprise Adoption

By 2025, adoption expanded with stronger spending and deployment evidence [1].

## Governance and Risk

The original report's statement that governance concerns were limited to experimentation requires clarification from previous reports, because enterprises now treat governance as an operational system [2].
""".strip()

    result = evaluate_chapter_update(
        original_text=original_text,
        generated_text=generated_text,
        research_findings=research_findings,
        blueprint=blueprint,
        references=references[:2],
    )

    codes = {issue["code"] for issue in result["issues"]}
    assert "source_reinterpretation_drift" in codes
    assert result["summary"]["passes"] is False
