# Report Updater v3

A Streamlit-based application to modernize legacy reports using Deep Research and AI agents.

## Features
- **Multimodal Extraction**: Extracts text and images from PDF and DOCX files.
- **Vision Analysis**: Transcribes graphs and tables using the selected multimodal LLM provider.
- **Provider Choice**: Runs LLM steps with either Gemini or OpenAI.
- **Agentic Research**: Performs web (DuckDuckGo) and academic research.
- **Draft Generation**: Rewrites chapters with modern data and citations.
- **Visual Production**: Generates custom graphs and sources relevant images.
- **Professional Export**: Assembles a high-quality DOCX with a bibliography.
- **Usage Report**: Shows LLM calls, tokens, latency, and estimated model cost after generation.

## Prerequisites
- Python 3.9+
- Gemini API key or OpenAI API key

## Setup
1. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables:
   Create a `.env` file in the root directory:
   ```env
   # gemini is the default for backward compatibility.
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your_gemini_api_key_here

   # To use OpenAI instead:
   # LLM_PROVIDER=openai
   # OPENAI_API_KEY=your_openai_api_key_here
   # OPENAI_MODEL=gpt-5.4-mini
   ```

   Optional OpenAI role-specific overrides are supported:
   `OPENAI_WRITER_MODEL`, `OPENAI_ANALYZER_MODEL`, `OPENAI_VISION_MODEL`,
   `OPENAI_RESEARCH_RANKER_MODEL`, `OPENAI_TRANSLATOR_MODEL`,
   `OPENAI_GRAPH_MODEL`, and `OPENAI_CHAPTER_JUDGE_MODEL`.

## Dev Container
The repo now includes a VS Code dev container in `.devcontainer/`.

1. Install Docker Desktop and the VS Code Dev Containers extension.
2. Open the repo in VS Code and run `Dev Containers: Reopen in Container`.
3. The container will install `requirements.txt` automatically on first create.
4. Start the app from the container terminal:
   ```bash
   ./run.sh
   ```

Port `8501` is forwarded automatically, and Streamlit is configured to bind to `0.0.0.0` inside the container. Your existing `.env` file stays in the workspace and is available to the app as usual.

If you copied the repo from Windows, recreate `.venv` inside the container before using it there. A Windows virtual environment under `.venv\Scripts\` will not run on Linux, and `run.sh` will fall back to the container Python when that happens.

## Running the App
In Linux or the dev container:
```bash
./run.sh
```

On Windows:
```bash
run.bat
```

Or manually via the command line on any platform:
```bash
python -m streamlit run app.py
```

## Structure
- `app.py`: Main Streamlit orchestration.
- `execution/`: Python scripts for parsing, research, and generation.
- `directives/`: Standard Operating Procedures for AI agents.
- `.tmp/`: Temporary storage for extracted assets and generated visuals.

## LLM Usage Report
After final assembly, the Streamlit UI shows an LLM usage report with total calls,
input/output/total tokens, latency, and estimated cost. The same data is saved
beside the generated report as:

- `<report_name>_<timestamp>_llm_usage.json`
- `<report_name>_<timestamp>_llm_usage.csv`

Cost is an estimate based on the built-in paid-tier pricing table and should not
be treated as a billing source of truth.
