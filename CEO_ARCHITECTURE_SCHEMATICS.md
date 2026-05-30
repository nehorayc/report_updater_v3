# Report App Architecture Schematics For CEO Presentation

This version avoids implementation-level file names and presents the app as business capabilities, decision points, and user-facing flow.

## 1. App Modules: Logic And Flow

```mermaid
flowchart LR
    INPUT["Legacy Report Input<br/>PDF or DOCX<br/>optional reference docs"]

    subgraph APP["Report Modernization App"]
        ORCH["Workflow Orchestrator<br/>controls step order<br/>stores run state<br/>routes each task"]

        INTAKE["Document Intake Module<br/>extract text<br/>split chapters<br/>extract visuals<br/>infer report date"]

        ASSETS["Source Asset Module<br/>select retained visuals<br/>analyze charts and tables<br/>plan refresh or conversion"]

        PLAN["Research Planning Module<br/>set topic and timeframe<br/>define audience<br/>attach reference material"]

        RESEARCH["Research Engine<br/>search web sources<br/>search academic sources<br/>search internal references<br/>rank evidence"]

        DRAFT["Writing Engine<br/>rewrite chapters<br/>preserve useful claims<br/>add new findings<br/>create citations"]

        VISUALS["Visual Intelligence Module<br/>discover graph opportunities<br/>refresh source charts<br/>rank graph candidates<br/>source images"]

        QA["Quality Gate Module<br/>check citations<br/>check evidence freshness<br/>validate figure markers<br/>clean fixable issues"]

        EXPORT["Delivery Module<br/>assemble DOCX<br/>assemble Markdown<br/>translate optional versions<br/>export usage and cost report"]
    end

    subgraph SERVICES["External Intelligence Services"]
        LLM["LLM Provider<br/>Gemini or OpenAI<br/>vision, research support, writing"]
        WEB["Web Search<br/>current public sources"]
        ACADEMIC["Academic Search<br/>research literature"]
        IMAGE["Image Providers<br/>licensed or searchable images"]
    end

    subgraph OUTPUT["Final Business Outputs"]
        REPORT["Modernized Report<br/>DOCX + Markdown"]
        TRANS["Optional Translations"]
        USAGE["Usage Report<br/>LLM calls, tokens, latency, cost"]
    end

    INPUT --> ORCH
    ORCH --> INTAKE
    INTAKE --> ASSETS
    ASSETS --> PLAN
    PLAN --> RESEARCH
    RESEARCH --> DRAFT
    DRAFT --> VISUALS
    VISUALS --> QA
    QA --> EXPORT

    QA -- "needs revision" --> PLAN
    QA -- "regenerate chapter" --> RESEARCH

    ASSETS --> LLM
    RESEARCH --> WEB
    RESEARCH --> ACADEMIC
    RESEARCH --> LLM
    DRAFT --> LLM
    VISUALS --> LLM
    VISUALS --> IMAGE
    EXPORT --> LLM

    EXPORT --> REPORT
    EXPORT --> TRANS
    EXPORT --> USAGE
```

### Executive Readout

- The app is a controlled modernization pipeline, not a one-shot AI prompt.
- Each module has a clear business function: understand the old report, research what changed, rewrite with evidence, improve visuals, validate quality, and export.
- Human review is built into the process before final delivery.
- AI is used for judgment-heavy tasks, while document handling, validation, visual rendering, and export are handled by deterministic modules.

## 2. User UI Process: Screen Flow

```mermaid
flowchart TD
    START["Start<br/>Open Report Updater"]

    S1["1. Upload Source Report<br/>choose PDF or DOCX<br/>confirm extraction"]
    SYS1["System prepares source material<br/>chapters extracted<br/>visuals detected<br/>report date inferred"]

    S2["2. Keep Source Visuals<br/>review extracted figures<br/>select what belongs in the new report"]
    SYS2["System analyzes selected visuals<br/>chart/table meaning captured<br/>source assets mapped to chapters"]

    S3["3. Plan Visual Updates<br/>keep original<br/>refresh with newer data<br/>convert table to editable text"]

    S4["4. Research Planning<br/>confirm update window<br/>edit chapter topics<br/>set keywords and audience<br/>upload internal references"]

    S5["5. Generate Draft<br/>run research<br/>rewrite chapters<br/>produce citations<br/>suggest visuals"]

    S6["6. Review Draft And Visuals<br/>edit chapter text<br/>approve source visuals<br/>choose new graphs/images<br/>run quality gate"]

    DECISION{"Ready To Finalize?"}

    LOOP1["Adjust plan<br/>change topic, timeframe, keywords, or references"]
    LOOP2["Regenerate chapter<br/>rerun research and writing for selected chapter"]

    S7["7. Final Assembly<br/>generate approved graphs<br/>fetch approved images<br/>build final report"]

    END["Deliverables<br/>updated DOCX<br/>Markdown version<br/>optional translations<br/>usage and cost report"]

    START --> S1
    S1 --> SYS1
    SYS1 --> S2
    S2 --> SYS2
    SYS2 --> S3
    S3 --> S4
    S4 --> S5
    S5 --> S6
    S6 --> DECISION

    DECISION -- "No: refine scope" --> LOOP1
    LOOP1 --> S4

    DECISION -- "No: improve chapter" --> LOOP2
    LOOP2 --> S5

    DECISION -- "Yes" --> S7
    S7 --> END
```

### Slide Talking Points

- The user stays in control of scope, source visuals, evidence settings, draft text, and final visual approvals.
- The app reduces manual report refresh work by sequencing research, drafting, visual production, QA, and export.
- The final output is not just text. It includes refreshed visuals, citations, translations when needed, and a cost/usage audit trail.

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
