from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv

from chapter_update_evaluator import evaluate_chapter_update
from quality_gate import evaluate_report_quality
from research_agent import (
    consume_runtime_diagnostics as consume_research_runtime_diagnostics,
    perform_comprehensive_research,
    reset_runtime_diagnostics as reset_research_runtime_diagnostics,
)
from writer_agent import write_chapter


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.live_api
@pytest.mark.network
@pytest.mark.slow
def test_live_single_chapter_canary(sample_txt_path: Path, report_metadata: dict[str, str]):
    if os.getenv("RUN_LIVE_API_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_API_TESTS=1 to run live Gemini canaries.")

    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is required for live Gemini canaries.")

    original_text = """
## Enterprise Adoption

Enterprise AI adoption accelerated through 2023 as organizations moved from pilot projects to production deployments.
The chapter should focus on business adoption, governance, and measurable spending or deployment trends.

## Governance and Risk

Decision-makers remained concerned about data protection, compliance, and model reliability.
The refreshed chapter should preserve that structure while updating the evidence through 2026.
""".strip()

    blueprint = {
        "topic": "Enterprise AI adoption and governance",
        "timeframe": "2024-2026",
        "keywords": [
            "enterprise AI adoption",
            "generative AI enterprise spending",
            "AI governance enterprise survey",
        ],
        "ref_paths": [str(sample_txt_path)],
        "baseline_summary": "A legacy chapter on enterprise AI adoption, governance, and business deployment.",
        "baseline_claims": [
            "Enterprises were moving from pilots to production deployments.",
            "Governance and risk management were becoming central to adoption.",
        ],
        "source_chapter_title": "Enterprise Adoption and Governance",
        "chapter_role": "body",
        "original_report_date": report_metadata["original_report_date"],
        "update_start_date": report_metadata["update_start_date"],
        "update_end_date": report_metadata["update_end_date"],
        "target_audience": report_metadata["target_audience"],
        "output_language": report_metadata["output_language"],
        "edition_title": "Enterprise AI Update",
        "report_subject": "Enterprise AI",
        "preserve_original_voice": True,
        "instructions": "Prioritize concrete survey data, named organizations, and governance developments.",
    }

    reset_research_runtime_diagnostics()
    findings = perform_comprehensive_research(blueprint)
    research_diagnostics = consume_research_runtime_diagnostics()

    assert len(findings) >= 3, research_diagnostics
    assert sum(1 for finding in findings if str(finding.get("snippet", "")).strip()) >= 3
    assert any(str(finding.get("url", "")).startswith("http") for finding in findings)

    writer_result = write_chapter(
        original_text=original_text,
        research_findings=findings[:8],
        blueprint=blueprint,
        writing_style="Professional",
        assets_to_update=[],
        prior_chapter_context=[],
        target_word_count=450,
        temperature=0.2,
    )

    assert "error" not in writer_result, writer_result.get("raw_content", "")

    draft_text = writer_result.get("text_content", "")
    references = writer_result.get("references", [])
    visuals = writer_result.get("visual_suggestions", [])

    assert len(draft_text) >= 800
    assert re.search(r"\[\d+\]", draft_text)
    assert len(references) >= 2
    assert len(visuals) >= 2
    assert any(str(visual.get("type", "")).lower() == "graph" for visual in visuals)
    assert not re.search(
        r"(this updated edition|align with the specified user objective|diverging from the original report's focus|user objective)",
        draft_text,
        re.IGNORECASE,
    )

    cited_reference_indices = {
        int(match)
        for match in re.findall(r"\[(\d+)\]", draft_text)
    }
    available_reference_indices = {
        int(ref["index"])
        for ref in references
        if str(ref.get("index", "")).isdigit()
    }
    assert cited_reference_indices
    assert cited_reference_indices.issubset(available_reference_indices)

    update_evaluation = evaluate_chapter_update(
        original_text=original_text,
        generated_text=draft_text,
        research_findings=findings[:8],
        blueprint=blueprint,
        references=references,
        use_llm_judge=os.getenv("RUN_LIVE_LLM_JUDGE") == "1",
    )

    assert update_evaluation["summary"]["passes"] is True, update_evaluation
    assert update_evaluation["summary"]["freshness_pass"] is True, update_evaluation
    assert update_evaluation["summary"]["style_preservation_pass"] is True, update_evaluation
    assert update_evaluation["summary"]["scope_preservation_pass"] is True, update_evaluation
    assert update_evaluation["summary"]["grounding_pass"] is True, update_evaluation
    if os.getenv("RUN_LIVE_LLM_JUDGE") == "1":
        assert update_evaluation["summary"]["llm_judge_pass"] is True, update_evaluation

    quality_report = evaluate_report_quality(
        [
            {
                "title": writer_result.get("chapter_title", blueprint["source_chapter_title"]),
                "draft_text": draft_text,
                "references": references,
                "approved_visuals": [],
            }
        ],
        report_metadata,
    )

    assert quality_report["summary"]["blocking"] is False, quality_report
