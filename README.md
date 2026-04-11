# Report Updater v3

A Streamlit-based application to modernize legacy reports using Deep Research and AI agents.

## Features
- **Multimodal Extraction**: Extracts text and images from PDF and DOCX files.
- **Vision Analysis**: Transcribes graphs and tables using Gemini Vision.
- **Agentic Research**: Performs web (DuckDuckGo) and academic research.
- **Draft Generation**: Rewrites chapters with modern data and citations.
- **Visual Production**: Generates custom graphs and sources relevant images.
- **Professional Export**: Assembles a high-quality DOCX with a bibliography.

## Prerequisites
- Python 3.9+
- Gemini API Key

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
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

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
