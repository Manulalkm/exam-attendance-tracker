# Exam Attendance Tracker

A localhost-first web app for exam rosters and attendance, with an optional AI assistant powered by a model running locally through Ollama. Student data and the SQLite database stay on your machine; the app sends AI prompts only to the configured Ollama URL.

## Features

- Create exam sessions and student rosters
- Record Present, Absent, or Late attendance
- Search by student name or ID
- Attendance totals and CSV export
- AI Q&A over one session's attendance data (optional local Ollama model)
- Local SQLite database, no hosted service required

## Run the app

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://localhost:5000> in your browser. The database `attendance.db` is created in the project directory on first run.

## Enable AI features (optional)

1. Install Ollama from <https://ollama.com/> and start it.
2. Download a model, for example:

   ```bash
   ollama pull llama3.2
   ```

3. Start this app. By default, it calls Ollama at `http://localhost:11434` using model `llama3.2`.
4. Open an exam session and choose **AI assistant**.

You can select a different local model or Ollama endpoint with environment variables:

```bash
# macOS/Linux
export OLLAMA_MODEL=qwen2.5:3b
export OLLAMA_URL=http://localhost:11434
python app.py
```

```powershell
# Windows PowerShell
$env:OLLAMA_MODEL = "qwen2.5:3b"
$env:OLLAMA_URL = "http://localhost:11434"
python app.py
```

Without Ollama installed and running, attendance management works normally; AI questions show a connection message. AI responses can be inaccurate, so verify any operational decisions against the roster. The assistant is intended for attendance summaries and must not be used to infer grades or reasons for absence.

## Privacy and network access

The web server binds to `127.0.0.1`, so it is only accessible from the same computer by default. AI queries go to the Ollama endpoint you configure. Keep the computer and database file protected as they contain student information. For multi-computer school use, hosting and access controls should be added before exposing the app to a network.
