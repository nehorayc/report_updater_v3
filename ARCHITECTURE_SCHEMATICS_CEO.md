# Report App Architecture

## CEO Presentation Version

This version is intentionally high-level. It emphasizes business modules and what each module does, rather than implementation files.

## 1. Executive Functional Architecture

```mermaid
flowchart LR
    USER[Analyst / Report Owner]

    subgraph UX[User Experience Layer]
        UI[Workflow Workspace<br/>upload, configure, review, approve]
    end

    subgraph ORCH[Workflow Control Layer]
        WF[Process Orchestration<br/>step management, approvals, handoffs, session state]
    end

    subgraph CORE[Core Business Modules]
        INTAKE[Report Intake<br/>extract text, split chapters, capture visuals]
        UNDERSTAND[Content Understanding<br/>infer metadata, summarize chapters, identify claims]
        RESEARCH[Research Engine<br/>gather market, academic, and internal evidence]
        DRAFT[Drafting Engine<br/>rewrite chapters, update insights, propose visuals]
        VISUALS[Visual Intelligence<br/>assess source visuals, refresh charts, source images]
        QA[Quality And Governance<br/>check citations, evidence, figure links, export readiness]
        PACK[Publishing And Reporting<br/>assemble report, translate, package outputs, track usage]
    end

    subgraph PLATFORM[Shared AI And Platform Services]
        AI[AI Service Router<br/>provider selection, response normalization, resilience]
        OPS[Monitoring And Cost Control<br/>usage tracking, diagnostics, logging]
    end

    subgraph EXT[External Knowledge Sources]
        MODELS[AI Models]
        WEB[Web And News Sources]
        ACADEMIC[Academic Sources]
        INTERNAL[Internal Reference Documents]
        MEDIA[Image Sources]
    end

    subgraph OUTPUTS[Business Outputs]
        REPORT[Updated Report<br/>DOCX / Markdown]
        VISPACK[Approved Visual Pack]
        SUMMARY[Change Summary]
        AUDIT[Usage And Cost Report]
    end

    USER --> UI
    UI --> WF

    WF --> INTAKE
    WF --> UNDERSTAND
    WF --> RESEARCH
    WF --> DRAFT
    WF --> VISUALS
    WF --> QA
    WF --> PACK

    UNDERSTAND --> AI
    RESEARCH --> AI
    DRAFT --> AI
    VISUALS --> AI
    PACK --> AI

    AI --> MODELS
    RESEARCH --> WEB
    RESEARCH --> ACADEMIC
    RESEARCH --> INTERNAL
    VISUALS --> MEDIA

    WF --> OPS
    AI --> OPS

    PACK --> REPORT
    PACK --> VISPACK
    PACK --> SUMMARY
    PACK --> AUDIT
```

### Executive Readout

- The app behaves like a guided production line for modernizing legacy reports.
- Human approval remains in the loop at key checkpoints, while AI accelerates analysis, research, writing, and visual refresh.
- Governance is built in through evidence checks, citation validation, and usage tracking.

## 2. Executive Usage Flow

```mermaid
flowchart TD
    A[Legacy report enters the system] --> B[System understands structure, chapters, and visuals]
    B --> C[User sets modernization scope and keeps or refreshes visuals]
    C --> D[System researches new evidence and market developments]
    D --> E[System produces updated draft chapters and recommended visuals]
    E --> F[User reviews, edits, and approves content and visuals]
    F --> G[Quality and governance checks validate readiness]
    G --> H[System publishes final report and supporting outputs]
```

### Boardroom Summary

- Input: a legacy report.
- Core value: the system turns static historical material into a current, evidence-backed edition.
- Output: a polished updated report with visuals, traceability, and optional multilingual delivery.

## 3. Simplified Source-To-Report Flow

```mermaid
flowchart LR
    subgraph SOURCES["Outside Inputs And Sources"]
        OLD["Old Report<br/>text, chapters, original visuals"]
        PUBLIC["Public Web Sources<br/>news, market reports, current data"]
        ACADEMIC["Academic Sources<br/>papers, datasets, institutions"]
        INTERNAL["Internal Documents<br/>uploaded references and notes"]
        MEDIA["Image Sources<br/>approved visual media"]
        AI["AI Models<br/>vision, language, reasoning"]
    end

    subgraph ACTIONS["App Actions"]
        A1["Extract Source Material<br/>split chapters<br/>extract visual assets<br/>capture original context"]
        A2["Build Chapter Summary<br/>summarize each chapter<br/>identify claims<br/>find dated facts and keywords"]
        A3["Understand Existing Visuals<br/>read charts and tables<br/>extract data points<br/>map visuals to chapters"]
        A4["Research Updates<br/>search outside evidence<br/>rank useful sources<br/>collect citations"]
        A5["Modernize Content<br/>rewrite chapters<br/>retain valid claims<br/>add new evidence"]
        A6["Update Old Graphs And Assets<br/>refresh old graphs<br/>convert tables to text<br/>generate new charts or images"]
        A7["Validate And Publish<br/>check citations<br/>check visual links<br/>assemble final report"]
    end

    subgraph DELIVERABLES["Updated Report Package"]
        CHAPTERS["Updated Chapters<br/>new text + citations"]
        VISUALPACK["Visual Pack<br/>refreshed graphs + approved images"]
        REPORT["Final Report<br/>DOCX + Markdown"]
        AUDIT["Audit Trail<br/>sources + AI usage + cost"]
    end

    OLD --> A1
    A1 --> A2
    A2 --> A3
    A3 --> A4
    A4 --> A5
    A5 --> A6
    A6 --> A7

    PUBLIC --> A4
    ACADEMIC --> A4
    INTERNAL --> A4
    MEDIA --> A6

    AI --> A2
    AI --> A3
    AI --> A5
    AI --> A6

    A7 --> CHAPTERS
    A7 --> VISUALPACK
    A7 --> REPORT
    A7 --> AUDIT
```

### Simple Talk Track

- The app starts with the old report and pulls it apart into chapters, visual assets, claims, dates, and topics.
- It brings in outside sources only where they are needed: public web, academic evidence, internal references, image sources, and AI models.
- The main business action is modernization: update chapter content, refresh old graphs, add citations, validate quality, and publish a clean report package.

## 4. One-Slide Talk Track

- Ingest and understand the original report.
- Research what has changed since publication.
- Rewrite the report into a current edition.
- Refresh visuals and recommendations.
- Validate quality before publishing.
- Deliver the final report with transparency on sources and AI usage.
