# GPT-SoVITS Voice Platform Skeleton

This directory contains the `LHY-N1` Week 1 engineering skeleton.

## Scope

- Single-entry Gradio app only
- No FastAPI, Flask, Vue, React, database, Redis, or Celery
- No fake audio generation or business logic implementation in this stage

## Structure

```text
.
├─ app.py
├─ ui/
├─ services/
├─ models/
├─ assets/
├─ data/
├─ tests/
└─ requirements.txt
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Expected Result

- A local Gradio page starts from the single `app.py` entrypoint.
- The current stage only shows a minimal shell for later UI integration.
- Page modules, services, and schemas are intentionally deferred to later nodes.
