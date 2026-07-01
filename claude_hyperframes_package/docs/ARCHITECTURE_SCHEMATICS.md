# Report App Architecture Schematics

These schematics reflect the current implementation in `app.py`, `PROJECT_OVERVIEW.md`, and the `execution/` layer.

## 1. Functional And Modular Architecture

```mermaid
flowchart LR
    U[User]
    D["Layer 1 Directives<br/>directives/*.md"]

    subgraph O[Layer 2 Orchestration]
        APP["app.py<br/>Streamlit UI + 7-step state machine"]
        SS[Session State<br/>chapters, assets, metadata,<br/>approvals, usage, exports]
    end

    subgraph E[Layer 3 Execution Modules]
        subgraph INGEST[Ingestion And Understanding]
            PDF["parse_pdf.py"]
            DOCX["parse_docx.py"]
            CA["chapter_analyzer.py"]
            RMA["report_metadata_analyzer.py"]
        end

        subgraph ASSET[Asset Intelligence]
            ASH["asset_selection_helpers.py"]
            VS["vision_service.py"]
            GUH["graph_update_helpers.py"]
        end

        subgraph RW[Research And Writing]
            RC["report_context.py"]
            RA["research_agent.py"]
            WA["writer_agent.py"]
            GQD["graph_question_discovery.py"]
            GR["graph_ranking.py"]
        end

        subgraph OUTPUT[Visual Production, QA, And Export]
            VPH["visual_pipeline_helpers.py"]
            GG["graph_generator.py"]
            IS["image_search.py"]
            QG["quality_gate.py"]
            DCB["doc_builder.py"]
            TR["translator.py"]
            RCS["report_change_summary.py"]
        end

        subgraph PLATFORM[Shared Platform Services]
            LLM["llm_client.py + gemini_client.py"]
            JSON["llm_json_utils.py"]
            USAGE["llm_usage.py + llm_pricing.py"]
            LOG["logger_config.py"]
        end
    end

    subgraph EXT[External Services]
        MODEL[Gemini or OpenAI]
        WEB[DuckDuckGo / DDGS]
        ACAD[OpenAlex]
        IMGAPI[Pixabay / Pexels / SerpApi]
    end

    subgraph FILES[Files And Artifacts]
        INPUT[Source report + optional reference docs]
        TMP[".tmp/<br/>extracted assets, previews,<br/>generated visuals, temp files"]
        EXP["exports/<br/>DOCX, Markdown, translations,<br/>LLM usage JSON/CSV"]
    end

    U --> APP
    D -. guides .-> APP
    APP <--> SS

    INPUT --> PDF
    INPUT --> DOCX

    APP --> PDF
    APP --> DOCX
    APP --> CA
    APP --> RMA

    APP --> ASH
    APP --> VS
    APP --> GUH

    APP --> RC
    APP --> RA
    APP --> WA
    APP --> GQD
    APP --> GR

    APP --> VPH
    APP --> GG
    APP --> IS
    APP --> QG
    APP --> DCB
    APP --> TR
    APP --> RCS

    VS --> LLM
    RA --> LLM
    WA --> LLM
    GG --> LLM
    TR --> LLM
    RCS --> LLM

    LLM --> MODEL
    RA --> WEB
    RA --> ACAD
    IS --> WEB
    IS --> IMGAPI

    PDF --> TMP
    DOCX --> TMP
    VS --> TMP
    GG --> TMP
    IS --> TMP

    DCB --> EXP
    TR --> EXP
    USAGE --> EXP
```

### Read This Diagram As

- `app.py` is the orchestration hub and owns the end-to-end workflow.
- `directives/` defines intended behavior, while `execution/` performs deterministic work.
- `llm_client.py` centralizes provider routing so Gemini and OpenAI stay behind one contract.
- `.tmp/` holds regenerable intermediates; `exports/` holds user-facing deliverables.

## 2. Usage And Operating Flow

```mermaid
flowchart TD
    A[User uploads legacy PDF or DOCX] --> B[App extracts chapters, text, and embedded visuals]
    B --> C[User keeps or drops source visuals]
    C --> D[App analyzes selected visuals and chapter baselines]
    D --> E[User plans source visual handling<br/>keep, refresh, or convert to text]
    E --> F[User defines research blueprint per chapter<br/>topic, timeframe, keywords, instructions, refs]
    F --> G[App researches each chapter<br/>web + academic + internal references]
    G --> H[App rewrites chapters and proposes visuals]
    H --> I[User reviews and edits draft text]
    I --> J[User approves retained visuals,<br/>updated visuals, and new suggestions]
    J --> K[App runs quality gate and optional cleanup]
    K --> L{Changes needed?}
    L -- Yes, update blueprint --> F
    L -- Yes, regenerate chapter --> G
    L -- No --> M[App generates approved graphs and fetches approved images]
    M --> N[App assembles final DOCX and Markdown]
    N --> O[Optional translation exports]
    O --> P["Final artifacts saved to exports/<br/>plus LLM usage and cost reports"]
```

### Presentation Summary

- The app is not a single prompt; it is a staged modernization pipeline.
- The user makes approval decisions at three control points: source visuals, research blueprint, and final draft/visual approval.
- AI is used inside bounded stages, while export, validation, and file assembly stay deterministic.
