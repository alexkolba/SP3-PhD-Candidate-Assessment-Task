from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, send_from_directory, flash)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict
import json, os, uuid

# ── App setup ────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-please")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(hours=24)

ADMIN_INVITE_CODE = os.environ.get("ADMIN_INVITE_CODE", "admin1234")
DATA_FILE  = "/data/feedback.json"
CASES_DIR  = "/cases"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."

# ── User model ───────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(16), nullable=False, default="annotator")
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)
    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_admin(self):     return self.role == "admin"
    @property
    def is_reviewer(self):  return self.role in ("admin", "reviewer")
    @property
    def is_annotator(self): return self.role in ("admin", "annotator")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ── Role decorators ──────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

def reviewer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_reviewer:
            flash("Reviewer access required.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ── Mock case data ───────────────────────────────────────────────────────────

# LUNA16-style nodule characteristics schema (used by both models and clinician ROI)
# malignancy: 1=Highly Unlikely, 2=Unlikely, 3=Indeterminate, 4=Suspicious, 5=Highly Suspicious
# lobulation/spiculation/calcification/texture: LUNA16 standard scales
# size fields removed — derived from ROI bounding box
IMAGING_CASE = {
    "id": "case_img_001",
    "type": "comparison",
    "specialty": "Oncological Radiology",
    "modality": "CT Thorax",
    "prompt": (
        "Male patient, CT thorax with contrast. Evaluate for pulmonary malignancy. "
        "Identify and localise any suspicious lesion using the LUNA16 nodule "
        "characterisation schema. Provide lesion size, location, morphology, "
        "malignancy suspicion score, and management recommendation."
    ),
    "slices": ["001.jpg","002.jpg","003.jpg","004.jpg","005.jpg","006.jpg"],
    "case_folder": "lung_ct_001",
    "outputs": [
        {
            "model": "LungNet-v2.1", "label": "Model A", "color": "#4af0c4",
            "detections": {
                "0": None,
                "1": {"x":0.13,"y":0.50,"w":0.09,"h":0.08,"conf":0.61},
                "2": {"x":0.13,"y":0.51,"w":0.10,"h":0.09,"conf":0.88},
                "3": {"x":0.13,"y":0.52,"w":0.10,"h":0.08,"conf":0.94},
                "4": {"x":0.14,"y":0.52,"w":0.09,"h":0.07,"conf":0.91},
                "5": {"x":0.14,"y":0.53,"w":0.08,"h":0.07,"conf":0.72},
            },
            # Structured fields matching LUNA16 + report sections
            "nodule_chars": {
                "location":      "Left lower lobe, posterior segment",
                "texture":       4,   # 1=Non-solid, 2=Part-solid, 3=Solid, 4=Heterogeneous
                "lobulation":    4,   # 1=No lobulation … 5=Marked lobulation
                "spiculation":   4,   # 1=No spiculation … 5=Marked spiculation
                "calcification": 1,   # 1=None, 2=Central, 3=Laminated, 4=Popcorn, 5=Eccentric, 6=Absent
                "malignancy":    5,   # 1=Highly Unlikely … 5=Highly Suspicious
            },
            "report_sections": {
                "location":        "Left lower lobe, abutting posterior mediastinum and left heart border.",
                "size":            "8.5 × 7.2 cm on index slice (slice 3–4).",
                "morphology":      "Lobulated, spiculated margins. Heterogeneous attenuation with central necrosis. No calcification.",
                "differential":    "1. Primary bronchogenic carcinoma (NSCLC) — highly likely.\n2. Large solitary metastasis — less likely given no known primary.",
                "recommendation":  "CT-guided biopsy. PET-CT for metabolic staging. MDT referral. Assess pericardial invasion (possible T4).",
            },
        },
        {
            "model": "ThoraxAI-Pro-3B", "label": "Model B", "color": "#f0c34a",
            "detections": {
                "0": None,
                "1": {"x":0.11,"y":0.48,"w":0.13,"h":0.12,"conf":0.54},
                "2": {"x":0.11,"y":0.49,"w":0.14,"h":0.12,"conf":0.82},
                "3": {"x":0.10,"y":0.50,"w":0.14,"h":0.13,"conf":0.85},
                "4": {"x":0.11,"y":0.51,"w":0.13,"h":0.11,"conf":0.78},
                "5": {"x":0.12,"y":0.52,"w":0.11,"h":0.10,"conf":0.63},
            },
            "nodule_chars": {
                "location":      "Left hemithorax, lower lobe origin",
                "texture":       4,
                "lobulation":    3,
                "spiculation":   3,
                "calcification": 1,
                "malignancy":    4,
            },
            "report_sections": {
                "location":        "Left lower lobe, with contact to the pericardium — invasion not definitively established.",
                "size":            "~7.8 × 6.9 cm axial plane.",
                "morphology":      "Lobulated contour, irregular margins. Internal heterogeneity consistent with necrosis or cavitation.",
                "differential":    "1. Primary NSCLC (adenocarcinoma or squamous cell).\n2. Pleural-based mass (mesothelioma) — lower probability.",
                "recommendation":  "Tissue sampling via CT-guided biopsy or bronchoscopy. PET-CT for full metabolic staging.",
            },
        },
    ],
}

MOCK_CASES = [
    {
        "id": "case_001", "type": "comparison", "specialty": "Cardiology",
        "prompt": (
            "A 58-year-old male presents with chest pain radiating to the left arm, "
            "diaphoresis, and shortness of breath for the past 2 hours. ECG shows "
            "ST-elevation in leads II, III, and aVF. BP 95/60 mmHg, HR 110 bpm. "
            "What is the immediate management?"
        ),
        "outputs": [
            {"model":"MedLLM-Alpha-7B","label":"Model A","text":(
                "This presentation is consistent with an inferior STEMI. Immediate management:\n\n"
                "1. **Activate cath lab** — door-to-balloon time target <90 minutes\n"
                "2. **Dual antiplatelet therapy** — Aspirin 325 mg PO + Ticagrelor 180 mg PO\n"
                "3. **Anticoagulation** — UFH 60 units/kg IV bolus (max 4000 units)\n"
                "4. **Oxygen** if SpO₂ <90%; avoid routine O₂\n"
                "5. **Right-sided ECG** to rule out RV infarction\n\n"
                "Hypotension raises concern for RV infarction — fluid challenge before vasopressors."
            )},
            {"model":"MedLLM-Beta-13B","label":"Model B","text":(
                "Inferior STEMI with haemodynamic compromise.\n\n"
                "**Reperfusion:** Primary PCI preferred. Activate cath lab immediately.\n\n"
                "**Pharmacotherapy:** Aspirin 300 mg + Ticagrelor 180 mg. Heparin per protocol.\n"
                "Avoid beta-blockers and nitrates given hypotension.\n\n"
                "**Haemodynamic:** Right-sided leads for RV infarct. Cautious IV fluids if confirmed.\n\n"
                "**Monitoring:** ICU-level, repeat ECG post-intervention."
            )},
        ],
    },
    {
        "id": "case_002", "type": "rating", "specialty": "Oncology",
        "prompt": (
            "A 45-year-old non-smoker female presents with a 3 cm right upper lobe "
            "pulmonary nodule found incidentally on CT. PET scan shows SUV max 8.2. "
            "No systemic symptoms. No mediastinal or distant metastases. EGFR mutation positive. "
            "What is the recommended treatment approach?"
        ),
        "outputs": [
            {"model":"MedLLM-Gamma-70B","label":"Model A","text":(
                "Stage IA2 NSCLC, EGFR-mutant.\n\n"
                "**Surgical resection** — VATS lobectomy preferred. Mediastinal lymph node dissection required.\n\n"
                "**Adjuvant:** Osimertinib 80 mg/day × 3 years post-resection (ADAURA data).\n\n"
                "**If surgery declined:** SABR as curative alternative.\n\nMDT discussion essential."
            )},
            {"model":"MedLLM-Delta-34B","label":"Model B","text":(
                "Stage IA-IB NSCLC, EGFR-mutant. MDT discussion required.\n\n"
                "**Primary:** VATS lobectomy + systematic lymphadenectomy. Pre-op PFTs required.\n\n"
                "**Adjuvant osimertinib:** Established for stage IB-IIIA; stage IA benefit less clear.\n\n"
                "Upfront TKI monotherapy NOT standard for resectable disease.\n\n"
                "Follow-up: CT every 6 months × 2 years, then annually."
            )},
        ],
    },
    {
        "id": "case_003", "type": "ranking", "specialty": "Neurology",
        "prompt": (
            "A 72-year-old hypertensive male, sudden onset right-sided weakness and aphasia, "
            "90 minutes ago. NIHSS 14. No haemorrhage on CT. Large ischaemic penumbra on CTP. "
            "BP 185/100 mmHg. Rank treatment options by priority."
        ),
        "outputs": [
            {"model":"MedLLM-Alpha-7B","label":"Model A","text":(
                "1. IV alteplase 0.9 mg/kg — within 3h window\n"
                "2. Mechanical thrombectomy — concurrent workup\n"
                "3. BP management — permit up to 185/110 pre-tPA\n"
                "4. Stroke unit admission, monitoring"
            )},
            {"model":"MedLLM-Beta-13B","label":"Model B","text":(
                "Tier 1: IV thrombolysis + CTA head/neck simultaneously\n"
                "Tier 2: EVT if LVO confirmed. BP <185/110 for tPA eligibility\n"
                "Tier 3: Stroke unit, NPO, glycaemia management"
            )},
            {"model":"MedLLM-Gamma-70B","label":"Model C","text":(
                "Immediate: Confirm tPA eligibility → administer.\n"
                "Concurrent: CTA → thrombectomy if LVO confirmed.\n"
                "BP: Permissive until tPA. Nicardipine if >185/110.\n"
                "Post: MRI DWI at 24h, AF workup, secondary prevention."
            )},
        ],
    },
    {
        "id": "case_004", "type": "comparison", "specialty": "Paediatrics",
        "prompt": (
            "4-year-old boy, 5 days fever, conjunctivitis, strawberry tongue, cracked lips, "
            "cervical lymphadenopathy (2 cm), generalised erythematous rash. "
            "CRP 180, WBC 18k, platelets 520k. Echo pending. Diagnosis and management?"
        ),
        "outputs": [
            {"model":"MedLLM-Epsilon-8B","label":"Model A","text":(
                "**Kawasaki Disease (complete)**\n\n"
                "- IVIG 2 g/kg over 10–12h\n- Aspirin 80–100 mg/kg/day → 3–5 mg/kg/day once afebrile\n"
                "- Echo at baseline, 2 weeks, 6–8 weeks\n- IVIG resistance: infliximab/corticosteroids"
            )},
            {"model":"MedLLM-Zeta-20B","label":"Model B","text":(
                "Kawasaki Disease. IVIG 2 g/kg + high-dose aspirin → low-dose once afebrile.\n\n"
                "Echo now — Z-scores >2.5. Repeat at 2 and 6–8 weeks.\n\n"
                "IVIG-refractory (fever >36h post-infusion): repeat IVIG or steroids/biologics."
            )},
        ],
    },
    IMAGING_CASE,
]


# ── Persistence helpers ───────────────────────────────────────────────────────

def load_json(path, default):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def get_cases():
    return MOCK_CASES

def get_feedback():
    return load_json(DATA_FILE, [])


# ── Analytics helpers ─────────────────────────────────────────────────────────

def compute_analytics(feedback, cases):
    """Return inter-annotator agreement and per-model statistics."""
    case_map = {c["id"]: c for c in cases}

    # ── Inter-annotator agreement ────────────────────────────────────────────
    # Group by case_id, collect preferred/ranking values per annotator
    case_annotations = defaultdict(list)
    for f in feedback:
        case_annotations[f["case_id"]].append(f)

    iaa = []
    for case_id, entries in case_annotations.items():
        if len(entries) < 2:
            continue
        case = case_map.get(case_id, {})
        ctype = case.get("type", "")
        annotators = [e.get("annotator_id", "?") for e in entries]

        if ctype == "comparison":
            labels = [e.get("preferred") for e in entries]
            labels = [l for l in labels if l is not None]
            if len(labels) >= 2:
                agreement = _pairwise_agreement(labels)
                iaa.append({
                    "case_id": case_id,
                    "specialty": case.get("specialty",""),
                    "type": ctype,
                    "annotators": annotators,
                    "metric": "% agreement",
                    "value": f"{agreement*100:.0f}%",
                    "n": len(labels),
                })

        elif ctype == "ranking":
            rankings = [tuple(e.get("ranking", [])) for e in entries]
            rankings = [r for r in rankings if r]
            if len(rankings) >= 2:
                agreement = _pairwise_agreement(rankings)
                iaa.append({
                    "case_id": case_id,
                    "specialty": case.get("specialty",""),
                    "type": ctype,
                    "annotators": annotators,
                    "metric": "% agreement",
                    "value": f"{agreement*100:.0f}%",
                    "n": len(rankings),
                })

        elif ctype == "rating":
            # Average per-model per-dimension rating agreement
            dim_scores = defaultdict(list)
            for e in entries:
                for model_idx, dims in e.get("ratings", {}).items():
                    for dim, val in dims.items():
                        dim_scores[f"M{model_idx}/{dim}"].append(int(val))
            if dim_scores:
                # Compute std dev as a spread measure; low std = high agreement
                spreads = []
                for key, vals in dim_scores.items():
                    if len(vals) >= 2:
                        mean = sum(vals)/len(vals)
                        std  = (sum((v-mean)**2 for v in vals)/len(vals))**0.5
                        spreads.append(std)
                if spreads:
                    avg_std = sum(spreads)/len(spreads)
                    iaa.append({
                        "case_id": case_id,
                        "specialty": case.get("specialty",""),
                        "type": ctype,
                        "annotators": annotators,
                        "metric": "avg rating std",
                        "value": f"{avg_std:.2f}",
                        "n": len(entries),
                    })

    # ── Per-model statistics ─────────────────────────────────────────────────
    model_stats = defaultdict(lambda: {
        "wins": 0, "losses": 0, "comparisons": 0,
        "ratings": defaultdict(list),
        "rank_positions": [],
        "flags": defaultdict(int),
        "cases": set(),
    })

    for f in feedback:
        case = case_map.get(f["case_id"], {})
        outputs = case.get("outputs", [])
        ctype   = f.get("type", "")

        if ctype == "comparison" and f.get("preferred") is not None:
            pref = int(f["preferred"])
            for i, out in enumerate(outputs):
                key = out["model"]
                model_stats[key]["comparisons"] += 1
                model_stats[key]["cases"].add(f["case_id"])
                if i == pref:
                    model_stats[key]["wins"] += 1
                elif pref != -1:
                    model_stats[key]["losses"] += 1

        elif ctype == "rating":
            for idx_str, dims in f.get("ratings", {}).items():
                idx = int(idx_str)
                if idx < len(outputs):
                    key = outputs[idx]["model"]
                    model_stats[key]["cases"].add(f["case_id"])
                    for dim, val in dims.items():
                        model_stats[key]["ratings"][dim].append(int(val))

        elif ctype == "ranking":
            ranking = f.get("ranking", [])
            for pos, idx in enumerate(ranking):
                if idx is not None and int(idx) < len(outputs):
                    key = outputs[int(idx)]["model"]
                    model_stats[key]["rank_positions"].append(pos + 1)
                    model_stats[key]["cases"].add(f["case_id"])

        # Per-model flags from model_feedback
        for mi_str, mf in f.get("model_feedback", {}).items():
            mi = int(mi_str)
            if mi < len(outputs):
                key = outputs[mi]["model"]
                for flag in mf.get("flags", []):
                    model_stats[key]["flags"][flag] += 1

    # ── Per-model IAA: for each model, agreement across annotators on that model's score ──
    # Group by (case_id, model) -> list of per-annotator preferred/rank/rating values
    model_iaa = {}  # model_name -> list of agreement values
    for case_id, entries in case_annotations.items():
        if len(entries) < 2:
            continue
        case    = case_map.get(case_id, {})
        outputs = case.get("outputs", [])
        ctype   = case.get("type", "")

        if ctype == "comparison":
            for i, out in enumerate(outputs):
                key    = out["model"]
                votes  = [1 if e.get("preferred") == i else 0
                          for e in entries if e.get("preferred") is not None]
                if len(votes) >= 2:
                    model_iaa.setdefault(key, []).append(_pairwise_agreement(votes))

        elif ctype == "ranking":
            for i, out in enumerate(outputs):
                key    = out["model"]
                positions = []
                for e in entries:
                    ranking = e.get("ranking", [])
                    if i in ranking:
                        positions.append(ranking.index(i) + 1)
                if len(positions) >= 2:
                    model_iaa.setdefault(key, []).append(_pairwise_agreement(positions))

        elif ctype == "rating":
            for i, out in enumerate(outputs):
                key = out["model"]
                for dim in ("accuracy", "completeness", "safety", "clarity"):
                    vals = [int(e.get("ratings", {}).get(str(i), {}).get(dim, 0))
                            for e in entries
                            if e.get("ratings", {}).get(str(i), {}).get(dim) is not None]
                    if len(vals) >= 2:
                        mean = sum(vals) / len(vals)
                        std  = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
                        # Convert std to a 0-1 agreement score (std=0 → 1.0, std=4 → 0.0)
                        model_iaa.setdefault(key, []).append(max(0, 1 - std / 4))

    # Serialise (sets aren't JSON-able)
    result = []
    for model, stats in model_stats.items():
        avg_ratings = {dim: round(sum(vals)/len(vals), 2)
                       for dim, vals in stats["ratings"].items() if vals}
        avg_rank = (round(sum(stats["rank_positions"])/len(stats["rank_positions"]), 2)
                    if stats["rank_positions"] else None)
        win_rate = (round(stats["wins"] / stats["comparisons"] * 100)
                    if stats["comparisons"] > 0 else None)
        iaa_vals = model_iaa.get(model, [])
        avg_iaa  = round(sum(iaa_vals) / len(iaa_vals) * 100) if iaa_vals else None
        result.append({
            "model":        model,
            "n_cases":      len(stats["cases"]),
            "win_rate":     win_rate,
            "comparisons":  stats["comparisons"],
            "avg_ratings":  avg_ratings,
            "avg_rank":     avg_rank,
            "flags":        dict(stats["flags"]),
            "avg_iaa":      avg_iaa,
        })

    return iaa, result


def _pairwise_agreement(labels):
    """Fraction of pairs that agree."""
    n = len(labels)
    if n < 2:
        return 1.0
    matches = sum(1 for i in range(n) for j in range(i+1, n) if labels[i] == labels[j])
    pairs   = n * (n-1) / 2
    return matches / pairs


# ── Accuracy helpers ──────────────────────────────────────────────────────────

CHAR_FIELDS = ("malignancy", "lobulation", "spiculation", "texture", "calcification")
CHAR_MAX    = {"malignancy": 4, "lobulation": 4, "spiculation": 4, "texture": 3, "calcification": 5}


def _iou_fractions(a, b):
    """IoU between two boxes in fraction coords {x,y,w,h}."""
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = ax1 + a["w"], ay1 + a["h"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = bx1 + b["w"], by1 + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = (a["w"]*a["h"]) + (b["w"]*b["h"]) - inter
    return inter / union if union > 0 else 0.0


def _char_accuracy(model_chars, clin_chars):
    """Mean normalised accuracy across LUNA16 fields (1.0 = perfect)."""
    scores = []
    for field in CHAR_FIELDS:
        mv = model_chars.get(field)
        cv = clin_chars.get(field)
        if mv is None or cv is None:
            continue
        try:
            diff  = abs(int(mv) - int(cv))
            max_d = CHAR_MAX.get(field, 4)
            scores.append(1.0 - diff / max_d)
        except (TypeError, ValueError):
            pass
    return round(sum(scores) / len(scores), 3) if scores else None


def compute_imaging_accuracy(feedback, cases):
    """
    For every feedback entry on an imaging case, emit a row.
    If the entry has clinician_annotation with nodule ROIs, compute IoU and
    characterisation accuracy; otherwise the row shows "awaiting annotation".
    Returns:
      per_case  – list of {case_id, model, avg_iou, char_acc, annotator, has_clin}
      per_model – dict {model_name: {avg_iou, avg_char_acc}}
    """
    case_map     = {c["id"]: c for c in cases}
    imaging_ids  = {c["id"] for c in cases if c.get("case_folder")}
    per_case     = []
    model_acc    = defaultdict(lambda: {"ious": [], "char_accs": []})

    for f in feedback:
        if f.get("case_id") not in imaging_ids:
            continue
        ca      = f.get("clinician_annotation")
        case    = case_map.get(f["case_id"], {})
        outputs = case.get("outputs", [])

        # Collect all clinician ROIs across nodules
        clin_rois_by_slice = {}
        has_clin = False
        if ca:
            nodule_list = ca.get("nodules", [])
            for nodule in nodule_list:
                clin_chars = nodule.get("chars", {})
                for roi in nodule.get("rois", []):
                    s = roi.get("slice")
                    if s is not None:
                        has_clin = True
                        clin_rois_by_slice.setdefault(s, []).append({
                            "box": roi, "chars": clin_chars
                        })
            # Legacy single-roi fallback
            legacy_roi = ca.get("roi")
            if legacy_roi and not nodule_list:
                s = legacy_roi.get("slice")
                if s is not None:
                    has_clin = True
                    clin_rois_by_slice.setdefault(s, []).append({
                        "box": legacy_roi, "chars": ca.get("chars", {})
                    })

        for out in outputs:
            model      = out["model"]
            detections = out.get("detections", {})
            ious, char_accs = [], []

            if has_clin:
                for slice_str, det in detections.items():
                    if det is None:
                        continue
                    s = int(slice_str)
                    for clin in clin_rois_by_slice.get(s, []):
                        iou = _iou_fractions(det, clin["box"])
                        ious.append(iou)
                        ca_score = _char_accuracy(out.get("nodule_chars", {}), clin["chars"])
                        if ca_score is not None:
                            char_accs.append(ca_score)

            avg_iou      = round(sum(ious)      / len(ious),      3) if ious      else None
            avg_char_acc = round(sum(char_accs)  / len(char_accs), 3) if char_accs else None

            per_case.append({
                "case_id":  f["case_id"],
                "model":    model,
                "annotator": f.get("annotator_id", "?"),
                "avg_iou":  avg_iou,
                "char_acc": avg_char_acc,
                "has_clin": has_clin,
            })

            if avg_iou is not None:
                model_acc[model]["ious"].append(avg_iou)
            if avg_char_acc is not None:
                model_acc[model]["char_accs"].append(avg_char_acc)

    per_model = {}
    for model, vals in model_acc.items():
        per_model[model] = {
            "avg_iou":      round(sum(vals["ious"])      / len(vals["ious"]),      3) if vals["ious"]      else None,
            "avg_char_acc": round(sum(vals["char_accs"])  / len(vals["char_accs"]), 3) if vals["char_accs"] else None,
        }

    return per_case, per_model


def enrich_feedback(feedback, cases):
    case_map = {c["id"]: c for c in cases}
    enriched = []
    for f in feedback:
        c = case_map.get(f["case_id"], {})
        enriched.append({**f,
            "specialty":      c.get("specialty", ""),
            "prompt_snippet": c.get("prompt", "")[:80] + "…",
            "output_labels":  [o["label"] for o in c.get("outputs", [])],
            "output_models":  [o["model"] for o in c.get("outputs", [])],
        })
    return enriched


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username    = request.form.get("username", "").strip()
        password    = request.form.get("password", "")
        password2   = request.form.get("password2", "")
        role        = request.form.get("role", "annotator")
        invite_code = request.form.get("invite_code", "").strip()

        if not username or not password:
            error = "Username and password are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != password2:
            error = "Passwords do not match."
        elif role not in ("annotator", "reviewer", "admin"):
            error = "Invalid role."
        elif role == "admin" and invite_code != ADMIN_INVITE_CODE:
            error = "Invalid admin invite code."
        elif User.query.filter_by(username=username).first():
            error = "Username already taken."
        else:
            is_first = User.query.count() == 0
            user = User(username=username, role="admin" if is_first else role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            return redirect(url_for("index"))

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            return redirect(request.args.get("next") or url_for("index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    users = User.query.order_by(User.created_at).all()
    return render_template("admin.html", users=users,
                           admin_invite_code=ADMIN_INVITE_CODE)


@app.route("/admin/user/<int:user_id>/role", methods=["POST"])
@login_required
@admin_required
def change_role(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "Not found"}), 404
    new_role = request.json.get("role")
    if new_role not in ("annotator", "reviewer", "admin"):
        return jsonify({"error": "Invalid role"}), 400
    user.role = new_role
    db.session.commit()
    return jsonify({"status": "ok", "role": new_role})


@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        return jsonify({"error": "Cannot delete yourself"}), 400
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({"status": "ok"})


# ── App routes ────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    cases    = get_cases()
    feedback = get_feedback()
    if current_user.is_reviewer:
        rated_ids = {f["case_id"] for f in feedback}
    else:
        rated_ids = {f["case_id"] for f in feedback
                     if f.get("annotator_id") == current_user.username}
    pending   = [c for c in cases if c["id"] not in rated_ids]
    completed = len(rated_ids)
    return render_template("index.html", cases=cases, pending=pending,
                           completed=completed, total=len(cases))


@app.route("/case/<case_id>")
@login_required
def case_view(case_id):
    cases = get_cases()
    case  = next((c for c in cases if c["id"] == case_id), None)
    if not case:
        return redirect(url_for("index"))

    # Reviewers see read-only view; annotators see full form
    readonly = not current_user.is_annotator
    feedback = get_feedback()
    existing = next((f for f in feedback
                     if f["case_id"] == case_id
                     and f.get("annotator_id") == current_user.username), None)
    template = "case_imaging.html" if case.get("case_folder") else "case.html"
    return render_template(template, case=case, existing=existing, readonly=readonly)


@app.route("/cases/<folder>/<filename>")
@login_required
def serve_case_image(folder, filename):
    return send_from_directory(os.path.join(CASES_DIR, folder), filename)


@app.route("/api/feedback", methods=["POST"])
@login_required
def submit_feedback():
    if not current_user.is_annotator:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json()
    if not data or "case_id" not in data:
        return jsonify({"error": "Missing case_id"}), 400

    feedback = get_feedback()
    feedback = [f for f in feedback
                if not (f["case_id"] == data["case_id"]
                        and f.get("annotator_id") == current_user.username)]
    entry = {
        "id":                   str(uuid.uuid4()),
        "case_id":              data["case_id"],
        "type":                 data.get("type"),
        "ratings":              data.get("ratings", {}),
        "ranking":              data.get("ranking", []),
        "preferred":            data.get("preferred"),
        "model_feedback":       data.get("model_feedback", {}),
        "comments":             data.get("comments", ""),
        "flags":                data.get("flags", []),
        "annotator_id":         current_user.username,
        "annotator_role":       current_user.role,
        "timestamp":            datetime.utcnow().isoformat() + "Z",
        "time_on_task_seconds": data.get("time_on_task_seconds", 0),
    }
    feedback.append(entry)
    save_json(DATA_FILE, feedback)
    return jsonify({"status": "ok", "id": entry["id"]})


@app.route("/api/feedback/<entry_id>", methods=["DELETE"])
@login_required
def delete_feedback(entry_id):
    feedback = get_feedback()
    entry = next((f for f in feedback if f["id"] == entry_id), None)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    # Annotators can only delete their own; reviewers/admins can delete any
    if not current_user.is_reviewer and entry.get("annotator_id") != current_user.username:
        return jsonify({"error": "Forbidden"}), 403
    feedback = [f for f in feedback if f["id"] != entry_id]
    save_json(DATA_FILE, feedback)
    return jsonify({"status": "ok"})


@app.route("/results")
@login_required
@reviewer_required
def results():
    feedback = get_feedback()
    cases    = get_cases()
    enriched = enrich_feedback(feedback, cases)
    iaa, model_stats = compute_analytics(feedback, cases)
    img_per_case, img_per_model = compute_imaging_accuracy(feedback, cases)
    # Merge imaging accuracy into model_stats
    for ms in model_stats:
        acc = img_per_model.get(ms["model"], {})
        ms["avg_iou"]      = acc.get("avg_iou")
        ms["avg_char_acc"] = acc.get("avg_char_acc")
    return render_template("results.html", feedback=enriched,
                           total_cases=len(cases), iaa=iaa,
                           model_stats=model_stats,
                           img_per_case=img_per_case)


@app.route("/my-results")
@login_required
def my_results():
    all_feedback = get_feedback()
    feedback = [f for f in all_feedback
                if f.get("annotator_id") == current_user.username]
    cases    = get_cases()
    enriched = enrich_feedback(feedback, cases)
    return render_template("my_results.html", feedback=enriched,
                           total_cases=len(cases))


@app.route("/api/export")
@login_required
@reviewer_required
def export_feedback():
    return jsonify(get_feedback())


@app.route("/api/reset", methods=["POST"])
@login_required
@admin_required
def reset_feedback():
    save_json(DATA_FILE, [])
    return jsonify({"status": "reset"})


# ── DB init ───────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
