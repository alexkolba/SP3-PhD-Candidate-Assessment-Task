from flask import (Flask, render_template, jsonify, request,
                   redirect, url_for, send_from_directory, flash)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
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
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(64), unique=True, nullable=False)
    password_hash= db.Column(db.String(256), nullable=False)
    role         = db.Column(db.String(16), nullable=False, default="annotator")
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_admin(self):    return self.role == "admin"
    @property
    def is_reviewer(self): return self.role in ("admin", "reviewer")
    @property
    def is_annotator(self):return self.role in ("admin", "annotator")


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

IMAGING_CASE = {
    "id": "case_img_001",
    "type": "comparison",
    "specialty": "Oncological Radiology",
    "modality": "CT Thorax",
    "prompt": (
        "Male patient, CT thorax with contrast. "
        "Evaluate for pulmonary malignancy. "
        "Identify and localise any suspicious lesion. "
        "Provide lesion characterisation and differential diagnosis."
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
            "report": (
                "**Lesion detected — left lower lobe**\n\n"
                "Large lobulated soft-tissue mass in the left lower lobe, abutting the posterior "
                "mediastinum and left heart border. Measures approximately 8.5 × 7.2 cm.\n\n"
                "**Characteristics:** Heterogeneous attenuation, central necrosis, spiculated margins.\n\n"
                "**Differential:** Primary bronchogenic carcinoma (NSCLC) — most likely.\n\n"
                "**Staging note:** Pericardial contact; T4 cannot be excluded."
            ),
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
            "report": (
                "**Finding: Large left-sided pulmonary mass**\n\n"
                "Dominant mass in the left hemithorax, left lower lobe origin. ~7.8 × 6.9 cm.\n\n"
                "**Morphology:** Lobulated, irregular margins, internal heterogeneity.\n\n"
                "**Differential:**\n"
                "1. Primary lung carcinoma (NSCLC)\n"
                "2. Pleural-based mass (lower probability)\n\n"
                "**Recommendation:** CT-guided biopsy + PET-CT for staging."
            ),
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
                "The hypotension raises concern for RV infarction — fluid challenge before vasopressors."
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
            # First ever user always becomes admin regardless
            is_first = User.query.count() == 0
            user = User(username=username, role="admin" if is_first else role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            return redirect(url_for("index"))

    return render_template("register.html", error=error,
                           admin_invite_required=True)


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
    # Annotators only see their own progress; reviewers/admins see totals
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
    if not current_user.is_annotator:
        flash("Annotation access required.", "error")
        return redirect(url_for("index"))
    cases = get_cases()
    case  = next((c for c in cases if c["id"] == case_id), None)
    if not case:
        return redirect(url_for("index"))
    feedback = get_feedback()
    existing = next((f for f in feedback
                     if f["case_id"] == case_id
                     and f.get("annotator_id") == current_user.username), None)
    template = "case_imaging.html" if case.get("case_folder") else "case.html"
    return render_template(template, case=case, existing=existing)


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
    # Remove previous entry by this annotator for this case
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


@app.route("/results")
@login_required
@reviewer_required
def results():
    feedback = get_feedback()
    cases    = get_cases()
    case_map = {c["id"]: c for c in cases}
    enriched = []
    for f in feedback:
        c = case_map.get(f["case_id"], {})
        enriched.append({**f,
            "specialty":     c.get("specialty", ""),
            "prompt_snippet": c.get("prompt", "")[:80] + "…"})
    return render_template("results.html", feedback=enriched,
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
