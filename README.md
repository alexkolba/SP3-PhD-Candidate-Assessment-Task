# DECIPHER-M — Clinical RLHF Annotation Tool

A containerised web platform for collecting structured human preference data on
clinical LLM outputs. Designed for preference optimisation (RLHF / DPO / RLAIF)
pipelines in medical AI. Supports text-only and text+image cases, with specialised
CT and CXR viewers for radiology annotation.

---

## Quick Start

**Prerequisites:**
- [Docker Desktop](https://docs.docker.com/desktop/) (includes Docker Compose)
- Make sure Docker Desktop is running before you proceed

**Run:**

```bash
docker compose up --build
```

Open **http://localhost:8080** in your browser.

To stop: `Ctrl+C`, then `docker compose down`

---

## Accounts & Roles

Three roles exist: **annotator**, **reviewer**, and **admin**.

| Role | Can annotate | View all results | Manage users |
|---|---|---|---|
| annotator | ✓ | — | — |
| reviewer | — | ✓ | — |
| admin | ✓ | ✓ | ✓ |

**Registration:**

1. Go to **http://localhost:8080/register**
2. Choose a username and password
3. Select role — annotators and reviewers register freely
4. Admin accounts require the invite code:

```
admin1234
```

The invite code is set via the `ADMIN_INVITE_CODE` environment variable in
`docker-compose.yml` and defaults to `admin1234` if unset.

---

## Architecture Overview

```
gitproject/
├── docker-compose.yml          # Service definition, port mapping, volumes
│
├── app/
│   ├── Dockerfile              # Python 3.12-slim, gunicorn 2-worker server
│   ├── requirements.txt        # Flask, Flask-Login, Flask-SQLAlchemy, gunicorn,
│   │                           # scikit-learn, numpy
│   ├── main.py                 # Entire backend: routes, case definitions,
│   │                           # analytics, Fleiss κ IAA, imaging accuracy
│   │
│   ├── static/
│   │   ├── css/style.css       # All styling (dark theme, component library)
│   │   └── js/app.js           # Minimal global JS (auth page helpers)
│   │
│   └── templates/
│       ├── base.html           # Shared nav, layout, font imports
│       ├── index.html          # Case list dashboard with progress stats
│       ├── case.html           # Text-only cases (comparison / rating / ranking)
│       ├── case_imaging.html   # Imaging cases: CT viewer, CXR viewer,
│       │                       # ROI drawing, LUNA16 nodule annotation (CT only)
│       ├── results.html        # All-results view (reviewer/admin only):
│       │                       # Fleiss κ IAA table, per-model stats,
│       │                       # imaging accuracy panel
│       ├── my_results.html     # Annotator's own submission history
│       ├── admin.html          # User management panel
│       ├── login.html          # Login page
│       └── register.html       # Registration page
│
└── cases/
    ├── lung_ct_001/            # CT thorax — 6 axial slices (001–006.jpg)
    │                           # Case courtesy of Frank Gaillard,
    │                           # Radiopaedia.org (rID: 8524)
    └── chest_xr_001/           # Chest X-ray PA — single image (001.jpg)
                                # Case courtesy of Chris O'Donnell,
                                # Radiopaedia.org (rID: 17945)
```

### Backend (`main.py`)

**Case data** is defined as Python dicts at the top of the file: `IMAGING_CASE`
(CT), `IMAGING_CASE_CXR` (CXR), and `MOCK_CASES` (text cases). Each case has an
`id`, `type`, `title`, `specialty`, `prompt`, and `outputs`.

**Persistence** uses two storage mechanisms in the `/data` Docker volume:

| File | Contents |
|---|---|
| `/data/users.db` | SQLite database — user accounts, roles, password hashes |
| `/data/feedback.json` | JSON array — all annotation submissions |

**Analytics** (`compute_analytics`) runs on every `/results` page load:
- **Fleiss' κ** inter-annotator agreement per case (comparison, ranking, rating, imaging nodule characteristics)
- **Per-model statistics** — win rate, avg rating, avg rank, avg κ, flag counts
- **Imaging accuracy** (`compute_imaging_accuracy`) — IoU of clinician ROI vs model detections, LUNA16 characteristic accuracy (CT only)

**Roles and access control** are enforced with `@login_required`,
`@reviewer_required`, and `@admin_required` decorators.

### Frontend — Text Cases (`case.html`)

- **Comparison**: side-by-side cards, click to prefer, per-model flags + comments
- **Rating**: 1–5 star sliders per model per dimension (Accuracy, Completeness, Safety, Clarity)
- **Ranking**: dropdown selects (1st / 2nd / 3rd) with live duplicate prevention and validation indicator

### Frontend — Imaging Cases (`case_imaging.html`)

- Single-model view with tab switching; side-by-side compare view
- Scroll wheel or vertical slider for CT slice navigation
- Model detection bounding boxes rendered on canvas with confidence badges
- **ROI drawing**: click-drag on any canvas (single or compare view); ROIs are stored per-nodule per-slice in normalised fraction coordinates
- **LUNA16 nodule characterisation** (CT only): malignancy, texture, lobulation, spiculation, calcification scales per annotated nodule
- Ranking UI (CXR case) uses dropdown selects matching the text ranking design

---

## Current Cases

| ID | Title | Type | Modality |
|---|---|---|---|
| `colon_crc_text` | Colon — CRC — Text | comparison | Text |
| `breast_her2_text` | Breast — HER2+ — Text | rating | Text |
| `lymphoma_dlbcl_text` | Lymphoma — DLBCL — Text | ranking | Text |
| `lung_ct_textimg` | Lung — CT — Text+Image | comparison | CT Thorax |
| `lung_cxr_textimg` | Lung — CXR — Text+Image | ranking | Chest X-Ray |

---

## Exported JSON Schema

`GET /api/export` returns all annotations as a JSON array. Each entry:

```json
{
  "id": "uuid",
  "case_id": "colon_crc_text",
  "type": "comparison",
  "preferred": 0,
  "ratings": {},
  "ranking": [],
  "model_feedback": {
    "0": { "flags": ["Factual error"], "comments": "..." },
    "1": { "flags": [], "comments": "" }
  },
  "clinician_annotation": {
    "nodules": [
      {
        "id": 1,
        "label": "N1",
        "location": "Left lower lobe, posterior",
        "chars": {
          "malignancy": 4,
          "texture": 3,
          "lobulation": 4,
          "spiculation": 3,
          "calcification": 1
        },
        "rois": [
          { "slice": 2, "x": 0.13, "y": 0.51, "w": 0.10, "h": 0.09 }
        ]
      }
    ]
  },
  "flags": ["Factual error"],
  "comments": "Model A missed pericardial involvement",
  "annotator_id": "dr_smith",
  "annotator_role": "annotator",
  "timestamp": "2026-03-10T22:01:24Z",
  "time_on_task_seconds": 187
}
```

`clinician_annotation` is only present for imaging cases. `chars` and `rois`
are only populated for CT cases; CXR cases omit the LUNA16 characteristic fields.

---

## Adding Cases

### Text case

Add a dict to `MOCK_CASES` in `app/main.py`:

```python
{
    "id":       "organ_condition_text",
    "title":    "Organ — Condition — Text",
    "type":     "comparison",          # or "rating" / "ranking"
    "specialty":"Oncology",
    "prompt":   "Clinical vignette...",
    "outputs": [
        {"model": "ModelName-7B", "label": "Model A", "text": "Response..."},
        {"model": "ModelName-13B","label": "Model B", "text": "Response..."},
    ],
}
```

### Imaging case

1. Create `cases/<folder_name>/` and place slice images as `001.jpg`, `002.jpg`, …
2. Add a dict to `main.py` before `MOCK_CASES` (see `IMAGING_CASE` as reference):
   - Set `"case_folder": "<folder_name>"` and `"slices": ["001.jpg", ...]`
   - Set `"modality"` to `"CT Thorax"` or `"Chest X-Ray"`
   - `"detections"` keys are slice indices (strings): `{"0": {"x":..,"y":..,"w":..,"h":..,"conf":..}}`
   - ROI coordinates are normalised fractions (0–1) of image width/height
   - LUNA16 `nodule_chars` are used for accuracy scoring — omit for CXR

Rebuild after any changes: `docker compose up --build`

---

## Data Reset

When logged in to an admin account, from the home page, click **↺ Reset all feedback** (removes all submissions).

Admin reset via API:

```bash
curl -X POST http://localhost:8080/api/reset
```

---

## Image Credits

**Chest X-Ray** (`cases/chest_xr_001/`):
Case courtesy of Chris O'Donnell, [Radiopaedia.org](https://radiopaedia.org/?lang=us).
From the case [rID: 17945](https://radiopaedia.org/cases/17945?lang=us).

**CT Thorax** (`cases/lung_ct_001/`):
Case courtesy of Frank Gaillard, [Radiopaedia.org](https://radiopaedia.org/?lang=us).
From the case [rID: 8524](https://radiopaedia.org/cases/8524?lang=us).
