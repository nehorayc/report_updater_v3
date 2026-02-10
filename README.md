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

## Running the App
You can run the app using the batch file:
```bash
run.bat
```
Or manually via the command line:
```bash
streamlit run app.py
```

## Structure
- `app.py`: Main Streamlit orchestration.
- `execution/`: Python scripts for parsing, research, and generation.
- `directives/`: Standard Operating Procedures for AI agents.
- `.tmp/`: Temporary storage for extracted assets and generated visuals.
