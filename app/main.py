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
    "id": "lung_ct_textimg",
    "title": "Lung — CT — Text+Image",
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

IMAGING_CASE_CXR = {
    "id": "lung_cxr_textimg",
    "title": "Lung — CXR — Text+Image",
    "type": "ranking",
    "specialty": "Oncological Radiology",
    "modality": "Chest X-Ray",
    "prompt": (
        "Male patient, history of chronic airways obstruction and bullous emphysema. "
        "Chest radiograph PA view. An unusual right upper lobe opacity has been identified "
        "with a highly atypical horizontal inferior border. Evaluate for pulmonary malignancy, "
        "characterise the lesion, and provide a differential diagnosis with management plan."
    ),
    "slices": ["001.jpg"],
    "case_folder": "chest_xr_001",
    "outputs": [
        {
            "model": "ThoraxAI-Pro-3B", "label": "Model A", "color": "#0065bd",
            # ROI: shifted/enlarged relative to ground truth (x1=0.20,x2=0.36,y1=0.37,y2=0.49)
            "detections": {
                "0": {"x": 0.17, "y": 0.33, "w": 0.21, "h": 0.18, "conf": 0.87},
            },
            "report_sections": {
                "location":       "Right upper zone, anterior segment. Lesion abuts the minor fissure inferiorly, producing the characteristic horizontal inferior border.",
                "size":           "Approximately 6.5 × 5.0 cm on PA radiograph. True axial dimensions require CT.",
                "morphology":     "Lobulated opacity with a sharp, horizontal inferior border at the level of the minor fissure. Poorly defined superior margin. No calcification. Background hyperinflation and bullous change consistent with emphysema.",
                "differential":   "1. Primary NSCLC (squamous cell or adenocarcinoma) — most likely given age, smoking history, and morphology.\n2. Pancoast-type apical tumour — less likely, no superior sulcus involvement.\n3. Obstructive pneumonia distal to endobronchial lesion.\n4. Carcinoid tumour — less likely given size.",
                "recommendation": "Urgent CT thorax with contrast for lesion characterisation, mediastinal staging, and biopsy planning. PET-CT if CT confirms malignancy. Bronchoscopy if central lesion suspected. MDT referral. Pulmonary function tests given underlying emphysema.",
            },
        },
        {
            "model": "LungNet-v2.1", "label": "Model B", "color": "#f0c34a",
            # Slightly different ROI estimate
            "detections": {
                "0": {"x": 0.23, "y": 0.34, "w": 0.19, "h": 0.17, "conf": 0.79},
            },
            "report_sections": {
                "location":       "Right upper lobe opacity. The inferior border aligns precisely with the minor fissure — a sign indicating the mass expands to fill the entire anterior segment.",
                "size":           "Estimated 6 × 5 cm. CT mandatory for accurate sizing and chest wall/mediastinal invasion assessment.",
                "morphology":     "Dense, lobulated solid mass. The straight inferior border is a classical radiographic sign of a lobe-filling lesion bounded by the minor fissure. Overlying bullous emphysema complicates assessment of margins. No visible satellite nodules on plain film.",
                "differential":   "1. Primary bronchogenic carcinoma — highly suspicious. The horizontal inferior border and solid morphology in a patient with emphysema is a high-risk pattern.\n2. Lymphoma — possible if systemic symptoms present.\n3. Large pulmonary abscess — unlikely without clinical sepsis.\n4. Rounded atelectasis — does not fit morphology.",
                "recommendation": "Same-day CT thorax with IV contrast is strongly recommended. Do not delay for additional plain films. If CT confirms malignancy, proceed to tissue diagnosis (CT-guided biopsy preferred over bronchoscopy for peripheral lesion). Staging PET-CT. Lung function testing essential prior to any surgical planning given emphysema.",
            },
        },
        {
            "model": "CheXpert-Dx-1B", "label": "Model C", "color": "#c44af0",
            "detections": {
                "0": {"x": 0.16, "y": 0.35, "w": 0.22, "h": 0.19, "conf": 0.62},
            },
            "report_sections": {
                "location":       "Right upper zone opacity. Precise lobe localisation limited on PA view alone; lateral radiograph or CT required.",
                "size":           "Largest dimension approximately 5.5 cm. Measurement unreliable without cross-sectional imaging.",
                "morphology":     "Homogeneous opacification of the right upper zone with an unusually flat inferior border. The background lung shows features of chronic obstructive airways disease with bullae. No pleural effusion or obvious rib destruction on this view.",
                "differential":   "1. Bronchogenic carcinoma — must be excluded urgently.\n2. Post-obstructive consolidation secondary to endobronchial tumour.\n3. Pleural-based mass (mesothelioma, fibrous tumour of pleura) — less likely.\n4. Hydatid cyst — atypical in this demographic.",
                "recommendation": "CT thorax with contrast required to clarify lesion characteristics and extent. Given emphysematous background, surgical risk stratification will be critical. Refer to thoracic oncology MDT. Sputum cytology while awaiting CT is low yield but non-invasive.",
            },
        },
    ],
}

MOCK_CASES = [
    {
        "id": "colon_crc_text", "title": "Colon — CRC — Text", "type": "comparison", "specialty": "Oncology",
        "prompt": (
            "A 63-year-old male presents with a 6-week history of altered bowel habit, "
            "rectal bleeding, and a 6 kg unintentional weight loss. Colonoscopy confirms "
            "a partially obstructing adenocarcinoma at the hepatic flexure. CT staging: "
            "T3N1M0 (stage IIIB). MSS/pMMR. KRAS exon 2 mutant. ECOG PS 0. "
            "What is the optimal perioperative management strategy?"
        ),
        "outputs": [
            {"model":"MedLLM-Alpha-7B","label":"Model A","text":(
                "Stage IIIB colon adenocarcinoma (T3N1M0), MSS, KRAS-mutant.\n\n"
                "**Primary: Surgical resection** — right hemicolectomy with D3 lymphadenectomy. "
                "Laparoscopic approach preferred if technically feasible.\n\n"
                "**Adjuvant chemotherapy:** FOLFOX × 6 months (MOSAIC/FLOX data). "
                "CAPOX × 3 months acceptable (IDEA trial: non-inferior for low-risk T3N1; "
                "consider 6 months given T3N1 disease).\n\n"
                "**Anti-EGFR:** Cetuximab/panitumumab NOT indicated — KRAS exon 2 mutant.\n\n"
                "**Bevacizumab:** Not used in adjuvant colon cancer — no OS benefit.\n\n"
                "MDT discussion pre-op. Genetic counselling if Lynch syndrome suspected."
            )},
            {"model":"MedLLM-Beta-13B","label":"Model B","text":(
                "T3N1M0 MSS colon cancer, KRAS-mutant. Curative-intent resection is the priority.\n\n"
                "**Surgery:** Right hemicolectomy. Ensure adequate proximal/distal margins and "
                "CME (complete mesocolic excision) for optimal nodal yield.\n\n"
                "**Adjuvant:** CAPOX × 3 months or FOLFOX × 6 months. IDEA trial supports "
                "3-month CAPOX for low-risk stage III; 6-month FOLFOX for higher-risk features.\n\n"
                "**MSI testing:** MSS confirms no benefit from pembrolizumab in adjuvant setting.\n\n"
                "**Follow-up:** CT CAP at 12 and 36 months. CEA every 3–6 months × 3 years. "
                "Colonoscopy at 1 year post-op."
            )},
        ],
    },
    {
        "id": "breast_her2_text", "title": "Breast — HER2+ — Text", "type": "rating", "specialty": "Oncology",
        "prompt": (
            "A 48-year-old pre-menopausal female presents with a 2.8 cm grade 3 "
            "invasive ductal carcinoma, right breast, ER 2%, PR 0%, HER2 3+ (IHC). "
            "Sentinel node biopsy: 2/3 nodes positive (macrometastases). No distant metastases "
            "(cT2N1M0, stage IIB). ECOG PS 0. What is the recommended treatment sequence?"
        ),
        "outputs": [
            {"model":"MedLLM-Gamma-70B","label":"Model A","text":(
                "HER2-positive, HR-low, stage IIB breast cancer.\n\n"
                "**Neoadjuvant (preferred):** Pertuzumab + Trastuzumab + Docetaxel + Carboplatin "
                "(TCHP) × 6 cycles — maximises pCR rate (BERENICE/NeoSphere).\n\n"
                "**Surgery:** Breast-conserving surgery or mastectomy depending on response. "
                "Axillary management per sentinel node/ALN status post-NAC.\n\n"
                "**Adjuvant:** If residual disease → T-DM1 × 14 cycles (KATHERINE trial). "
                "If pCR → complete trastuzumab to 1 year total.\n\n"
                "**Pertuzumab continuation:** 1 year total in HER2+ node-positive disease.\n\n"
                "**Endocrine:** ER 2% — consider OFS + AI given pre-menopausal status after chemo."
            )},
            {"model":"MedLLM-Delta-34B","label":"Model B","text":(
                "Stage IIB HER2+ IDC. Neoadjuvant dual HER2 blockade preferred.\n\n"
                "**NAC:** TCHP (docetaxel/carboplatin/trastuzumab/pertuzumab) × 6 cycles. "
                "Dose-dense AC → THP is an alternative (longer but avoids carboplatin toxicity).\n\n"
                "**pCR (ypT0/Tis ypN0):** Complete 1 year of trastuzumab + pertuzumab.\n\n"
                "**Non-pCR:** Switch to T-DM1 × 14 cycles (KATHERINE: 50% reduction in iDFS events). "
                "Add neratinib × 1 year post T-DM1 if HR+ residual (ExteNET-adjacent data).\n\n"
                "**ER 2%:** Low expression — endocrine therapy decision at MDT; many would treat "
                "as HER2-enriched rather than ER+ disease."
            )},
        ],
    },
    {
        "id": "lymphoma_dlbcl_text", "title": "Lymphoma — DLBCL — Text", "type": "ranking", "specialty": "Oncology",
        "prompt": (
            "A 58-year-old male presents with rapidly enlarging bilateral cervical and "
            "axillary lymphadenopathy, B-symptoms, LDH 3× ULN, and a large mediastinal mass. "
            "Excisional biopsy confirms diffuse large B-cell lymphoma (DLBCL), GCB subtype, "
            "Ki-67 90%. PET-CT: stage IV (bone marrow involvement). IPI score 4 (high-risk). "
            "Rank the following first-line treatment approaches by appropriateness."
        ),
        "outputs": [
            {"model":"MedLLM-Alpha-7B","label":"Model A","text":(
                "1. **R-CHOP × 6 cycles** — standard of care for stage IV DLBCL; well-established OS benefit\n"
                "2. **Pola-R-CHP × 6 cycles** — polatuzumab vedotin + R-CHP (POLARIX trial): superior PFS vs R-CHOP in IPI ≥2; reasonable alternative at high IPI\n"
                "3. **DA-EPOCH-R** — preferred for MYC/BCL2 double-hit (check FISH); superior for high-grade B-cell lymphoma\n"
                "4. **R-CHOP + consolidation auto-SCT** — not standard in first-line for DLBCL; reserved for relapsed/refractory"
            )},
            {"model":"MedLLM-Beta-13B","label":"Model B","text":(
                "Tier 1: Check MYC/BCL2/BCL6 FISH — if double/triple-hit → DA-EPOCH-R; if GCB without DHL → Pola-R-CHP\n"
                "Tier 2: R-CHOP × 6 — still widely used; POLARIX PFS benefit modest, no OS difference to date\n"
                "Tier 3: CNS prophylaxis (IT MTX or HD-MTX) — high CNS-IPI risk given IPI 4, bone marrow involvement\n"
                "Tier 4: Upfront auto-SCT consolidation — investigational in first-line; not standard practice"
            )},
            {"model":"MedLLM-Gamma-70B","label":"Model C","text":(
                "1. FISH for MYC rearrangement — mandatory before selecting regimen; DHL/THL → DA-EPOCH-R\n"
                "2. Pola-R-CHP × 6 if non-DHL GCB — POLARIX: statistically significant PFS improvement at IPI ≥2\n"
                "3. R-CHOP × 6 — acceptable if Pola-R-CHP unavailable; equivalent OS in current data\n"
                "4. PET-guided consolidation (auto-SCT) — investigational; not recommended outside clinical trial in CR1"
            )},
        ],
    },
    IMAGING_CASE,
    IMAGING_CASE_CXR,
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
    """Return inter-annotator agreement (Fleiss' κ) and per-model statistics."""
    case_map = {c["id"]: c for c in cases}

    # Group annotations by case
    case_annotations = defaultdict(list)
    for f in feedback:
        case_annotations[f["case_id"]].append(f)

    iaa = []
    for case_id, entries in case_annotations.items():
        if len(entries) < 2:
            continue
        case      = case_map.get(case_id, {})
        ctype     = case.get("type", "")
        annotators = [e.get("annotator_id", "?") for e in entries]

        if ctype == "comparison":
            labels = [e.get("preferred") for e in entries if e.get("preferred") is not None]
            if len(labels) >= 2:
                cats  = sorted(set(labels))
                kappa = 1.0 if len(cats) == 1 else _fleiss_kappa([labels], cats)
                iaa.append({
                    "case_id":    case_id,
                    "specialty":  case.get("specialty", ""),
                    "type":       ctype,
                    "annotators": annotators,
                    "metric":     "Fleiss κ",
                    "value":      _kappa_str(kappa),
                    "n":          len(labels),
                })

        elif ctype == "ranking":
            n_models = len(case.get("outputs", []))
            rankings = [e.get("ranking", []) for e in entries if e.get("ranking")]
            if len(rankings) >= 2 and n_models > 0:
                kappas = []
                for pos in range(n_models):
                    assignments = [r[pos] for r in rankings if len(r) > pos and r[pos] is not None]
                    if len(assignments) >= 2:
                        cats = sorted(set(assignments))
                        k = 1.0 if len(cats) == 1 else _fleiss_kappa([assignments], cats)
                        if k is not None:
                            kappas.append(k)
                kappas = [v for v in kappas if v is not None]
                kappa = sum(kappas) / len(kappas) if kappas else None
                iaa.append({
                    "case_id":    case_id,
                    "specialty":  case.get("specialty", ""),
                    "type":       ctype,
                    "annotators": annotators,
                    "metric":     "Fleiss κ (mean rank pos)",
                    "value":      _kappa_str(kappa),
                    "n":          len(rankings),
                })

        elif ctype == "rating":
            dim_ratings = defaultdict(list)
            for e in entries:
                for model_idx, dims in e.get("ratings", {}).items():
                    for dim, val in dims.items():
                        dim_ratings[f"M{model_idx}/{dim}"].append(int(val))
            kappas = []
            for key, vals in dim_ratings.items():
                if len(vals) >= 2:
                    cats = sorted(set(vals))
                    k = 1.0 if len(cats) == 1 else _fleiss_kappa([vals], cats)
                    if k is not None:
                        kappas.append(k)
            kappas = [v for v in kappas if v is not None]
            if kappas:
                mean_k = sum(kappas) / len(kappas)
                iaa.append({
                    "case_id":    case_id,
                    "specialty":  case.get("specialty", ""),
                    "type":       ctype,
                    "annotators": annotators,
                    "metric":     "Fleiss κ (mean dim)",
                    "value":      _kappa_str(mean_k),
                    "n":          len(entries),
                })

        # ── Imaging cases: also compute κ over nodule characterisation ──────
        if case.get("case_folder"):
            char_kappas = _nodule_char_kappa(entries)
            if char_kappas:
                mean_k = sum(v for v in char_kappas.values() if v is not None) / max(1, sum(1 for v in char_kappas.values() if v is not None))
                detail = ", ".join(f"{k}: {_kappa_str(v)}" for k, v in char_kappas.items())
                iaa.append({
                    "case_id":    case_id,
                    "specialty":  case.get("specialty", ""),
                    "type":       "imaging-chars",
                    "annotators": annotators,
                    "metric":     "Fleiss κ nodule chars",
                    "value":      f"{_kappa_str(mean_k)} ({detail})",
                    "n":          len(entries),
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

    # ── Per-model IAA: Fleiss κ per model across annotators ─────────────────
    model_iaa = {}  # model_name -> list of kappa values
    for case_id, entries in case_annotations.items():
        if len(entries) < 2:
            continue
        case    = case_map.get(case_id, {})
        outputs = case.get("outputs", [])
        ctype   = case.get("type", "")

        if ctype == "comparison":
            for i, out in enumerate(outputs):
                key   = out["model"]
                votes = [1 if e.get("preferred") == i else 0
                         for e in entries if e.get("preferred") is not None]
                if len(votes) >= 2:
                    cats = sorted(set(votes))
                    k = 1.0 if len(cats) == 1 else _fleiss_kappa([votes], [0, 1])
                    if k is not None:
                        model_iaa.setdefault(key, []).append(k)

        elif ctype == "ranking":
            for i, out in enumerate(outputs):
                key       = out["model"]
                positions = [ranking.index(i) + 1
                             for e in entries
                             for ranking in [e.get("ranking", [])]
                             if i in ranking]
                if len(positions) >= 2:
                    cats = sorted(set(positions))
                    k = 1.0 if len(cats) == 1 else _fleiss_kappa([positions], cats)
                    if k is not None:
                        model_iaa.setdefault(key, []).append(k)

        elif ctype == "rating":
            for i, out in enumerate(outputs):
                key = out["model"]
                for dim in ("accuracy", "completeness", "safety", "clarity"):
                    vals = [int(e.get("ratings", {}).get(str(i), {}).get(dim, 0))
                            for e in entries
                            if e.get("ratings", {}).get(str(i), {}).get(dim) is not None]
                    if len(vals) >= 2:
                        cats = sorted(set(vals))
                        k = 1.0 if len(cats) == 1 else _fleiss_kappa([vals], cats)
                        if k is not None:
                            model_iaa.setdefault(key, []).append(k)

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
        avg_iaa  = round(sum(iaa_vals) / len(iaa_vals), 3) if iaa_vals else None
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


def _fleiss_kappa(rater_labels, categories):
    """
    Fleiss' κ for N subjects each rated by (possibly different) raters.
    rater_labels: list of lists — rater_labels[i] = list of category labels
                  assigned to subject i (length = number of raters for that subject).
    categories:   all possible category values.
    Returns κ (float), or None if not computable.
    """
    if not categories or len(categories) < 2:
        return None
    cat_idx = {c: j for j, c in enumerate(categories)}
    k = len(categories)
    n_subj = len(rater_labels)
    if n_subj < 1:
        return None

    # Build rating matrix n_ij: subjects × categories
    matrix = []
    n_raters_per_subj = []
    for labels in rater_labels:
        row = [0] * k
        for l in labels:
            if l in cat_idx:
                row[cat_idx[l]] += 1
        matrix.append(row)
        n_raters_per_subj.append(sum(row))

    n_total = sum(n_raters_per_subj)
    if n_total == 0:
        return None
    # Assume equal raters per subject (use max for normalisation)
    n = max(n_raters_per_subj) if n_raters_per_subj else 1
    if n < 2:
        return None

    # P_i: proportion of agreeing pairs for subject i
    P_i = []
    for row, ni in zip(matrix, n_raters_per_subj):
        if ni < 2:
            P_i.append(0.0)
        else:
            P_i.append((sum(c*(c-1) for c in row)) / (ni * (ni - 1)))
    P_bar = sum(P_i) / n_subj

    # p_j: marginal proportion for each category
    total_ratings = sum(sum(row) for row in matrix)
    if total_ratings == 0:
        return None
    p_j = [sum(row[j] for row in matrix) / total_ratings for j in range(k)]
    P_e  = sum(pj**2 for pj in p_j)

    if P_e >= 1.0:
        return 1.0
    return (P_bar - P_e) / (1.0 - P_e)


def _kappa_str(kappa):
    """Format kappa with interpretation label."""
    if kappa is None:
        return "n/a"
    label = ("poor" if kappa < 0 else
             "slight" if kappa < 0.2 else
             "fair"   if kappa < 0.4 else
             "moderate" if kappa < 0.6 else
             "substantial" if kappa < 0.8 else "almost perfect")
    return f"{kappa:.3f} ({label})"


def _nodule_char_kappa(entries):
    """
    Compute per-field Fleiss κ over nodule characterisation annotations.
    Collects (field → list of values) across all annotators' first nodule,
    then returns {field: kappa} for fields with ≥2 non-None values.
    """
    FIELDS = ("malignancy", "texture", "lobulation", "spiculation", "calcification")
    field_vals = defaultdict(list)
    for e in entries:
        ca = e.get("clinician_annotation") or {}
        nodules = ca.get("nodules", [])
        if not nodules:
            continue
        chars = nodules[0].get("chars", {})
        for f in FIELDS:
            v = chars.get(f)
            if v is not None:
                field_vals[f].append(v)
    result = {}
    for f, vals in field_vals.items():
        if len(vals) >= 2:
            cats = sorted(set(vals))
            k = 1.0 if len(cats) == 1 else _fleiss_kappa([vals], cats)
            if k is not None:
                result[f] = k
    return result


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
        "clinician_annotation": data.get("clinician_annotation"),
        "annotator_id":         current_user.username,
        "annotator_role":       current_user.role,
        "timestamp":            datetime.utcnow().isoformat() + "Z",
        "time_on_task_seconds": data.get("time_on_task_seconds", 0),
    }
    feedback.append(entry)
    save_json(DATA_FILE, feedback)
    ca = entry.get("clinician_annotation")
    nodule_count = len(ca.get("nodules", [])) if ca else 0
    roi_count = sum(len(n.get("rois",[])) for n in ca.get("nodules",[])) if ca else 0
    app.logger.info(f"[feedback saved] case={entry['case_id']} annotator={entry['annotator_id']} nodules={nodule_count} rois={roi_count}")
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


@app.route("/api/debug-latest")
@login_required
def debug_latest():
    feedback = get_feedback()
    if not feedback:
        return jsonify({"error": "no feedback"})
    latest = feedback[-1]
    return jsonify({
        "case_id": latest.get("case_id"),
        "annotator_id": latest.get("annotator_id"),
        "clinician_annotation": latest.get("clinician_annotation"),
    })


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
