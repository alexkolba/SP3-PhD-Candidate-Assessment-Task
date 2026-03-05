# MedEval — Clinical RLHF Annotation Tool

A containerised web frontend for collecting structured human preference data on
clinical LLM outputs. Built for preference optimisation (RLHF / DPO) pipelines.

CT images are case courtesy of Frank Gaillard, [Radiopaedia](https://radiopaedia.org/?lang=us). From the case [rID: 8524](https://radiopaedia.org/cases/8524?lang=us)

---

## Quick Start (Windows 10)

**Prerequisites:**
- [Docker Desktop for Windows](https://docs.docker.com/desktop/windows/install/) (includes Docker Compose)
- Make sure Docker Desktop is running before you proceed

**Run the app:**

```
docker compose up --build
```

Then open your browser at: **http://localhost:5000**

To stop: `Ctrl+C`, then `docker compose down`

---

## Features

| Feature | Details |
|---|---|
| **Comparison** | Side-by-side output comparison, select preferred response |
| **Rating** | Rate each model on Accuracy, Completeness, Safety, Clarity (1–5 stars) |
| **Ranking** | Drag-and-drop ranking of 3+ outputs |
| **Flags** | Tag outputs: Factual error, Dangerous advice, Hallucination, etc. |
| **Comments** | Free-text annotator notes per case |
| **Persistence** | Feedback stored in a named Docker volume — survives `docker compose restart` |
| **Resume** | Previously submitted feedback is restored when revisiting a case |
| **Export** | Download all annotations as JSON via `/api/export` |

---

## Exported JSON Schema

Each annotation entry looks like:

```json
{
  "id": "uuid",
  "case_id": "case_001",
  "type": "comparison",
  "preferred": 0,
  "ratings": {},
  "ranking": [],
  "flags": ["Factual error"],
  "comments": "Model A missed RV infarction workup",
  "annotator_id": "dr_smith",
  "timestamp": "2025-01-15T14:23:01Z",
  "time_on_task_seconds": 142
}
```

---

## Adding Your Own Cases

Edit `app/main.py` and modify the `MOCK_CASES` list at the top of the file.

Each case needs:
- `id` — unique string
- `type` — `"comparison"`, `"rating"`, or `"ranking"`
- `specialty` — display label
- `prompt` — the clinical prompt shown to the annotator
- `outputs` — list of `{ "model": "...", "label": "...", "text": "..." }`

Rebuild after changes: `docker compose up --build`

---

## Data Reset

Visit **http://localhost:5000** and click "Reset all feedback" at the bottom,
or call the API directly:

```
curl -X POST http://localhost:5000/api/reset
```
