# AI Setup and Usage Guide

How to set up, activate, and use each of the three AI functions, plus the
prerequisites they depend on. Every step here was verified against the real
application. All AI runs **locally** — no student text ever leaves the machine.

The three functions:

| # | Function | What it does | Where it appears |
|---|----------|--------------|------------------|
| 1 | **Core AI 2** — answer-region detector (YOLO) | Proposes answer/question regions on scanned pages | Subject Profile editor + Separate Answer Paper |
| 2 | **Core AI 1** — Kertas 2 scoring Cross-Encoder | Drafts a score + feedback category per essay | Marking Editor ("Generate AI Drafts") |
| 3 | **Local feedback runtime** (Ollama) | Writes natural-language feedback per essay | Marking Editor ("Draft Feedback Wording") |

Safety design shared by all three: AI output is always a **suggestion** —
nothing is applied automatically, a teacher decision is required everywhere,
manual marking works fully when any AI part is missing, and failures fall back
gracefully (empty proposals / "failed" drafts / template wording).

---

## 0. Prerequisites

- Python 3.12 with the app dependencies (`pip install -r requirements.txt`)
  and the optional AI dependencies (`pip install -r requirements-ai.txt`:
  torch + CUDA build, ultralytics, transformers, paddleocr).
- Run the app from this folder: `python main.py`. The app's data root is
  `english_grading_system/data` (override with the
  `ENGLISH_GRADING_SYSTEM_DATA_ROOT` environment variable — models, datasets
  and the DB all live under whichever root is active, so **register models in
  the root you actually run with**).
- The AI model registry lives at `data/ai/` (models, evaluations, active
  pointers, activation history). Activation is checksum- and
  evaluation-gated: a model cannot be activated without a passing evaluation
  record, and a tampered checkpoint refuses to load.

---

## 1. Core AI 2 — answer-region detector

### Data it trains on
Subject Profile exports (ZIPs from "Export" on the Marking page) containing
page images + teacher-drawn regions. The emergency pipeline reads them from
`dataset_raw/core_ai2/DONE/`.

### Train / register / activate (script pipeline)
```
# 1. Convert profile exports into a leakage-safe YOLO dataset (profile-grouped
#    splits, seed 42; duplicates deduplicated; every region validated):
python scripts/emergency_prepare_core_ai2_dataset.py ^
    --source "../dataset_raw/core_ai2/DONE" ^
    --workspace "../FYP-Data/core_ai2_emergency_training"

# 2. Train (YOLO nano, 640px) - GPU recommended:
python scripts/emergency_train_core_ai2.py --run-root <run folder from step 1>

# 3. Register + evaluate + activate through the production registry
#    (verifies checksums, records real val/test metrics, runs one real
#    inference, and only then activates):
python scripts/emergency_register_core_ai2_model.py ^
    --run-root <run folder> ^
    --data-root "C:/Users/User/Documents/AutoMarkingSystem/english_grading_system/data"
```

In-app alternative (fully supported): admin → **AI Models** → "Core AI 2
datasets" / "Core AI 2 training, evaluation & activation" sections. Export a
dataset → **Freeze** → **Convert to YOLO** → **Start training** (you pick the
YOLO conversion and a local base checkpoint `.pt` such as `yolo11n.pt`) →
**Evaluate** → **Activate**. Training runs in a background worker; the base
checkpoint is never downloaded automatically.

### Verify it is active
Admin → **AI Models**: the "Answer Region Detection" card shows
*Status: Active version in use (…)*, and the registry table shows the row as
`evaluated / active`.

### Use it (teacher)
- **Subject Profile editor**: open a profile (Marking → Open / Edit), render a
  page, click **"Core AI 2 Region Proposals (Page)"** — or
  **"Core AI 2 Region Proposals (All Pages)"** to detect on every rendered
  page in one run (per-page progress shown). Review dialog: each proposal has
  class + confidence + geometry; Accept (optionally retype/move/resize
  afterwards - an accepted proposal becomes a normal editable region), Reject,
  Defer, or Edit — or use **"Apply All Proposals"** to accept every pending
  proposal at once after a single confirmation. Existing manual regions are
  never overwritten either way.
- **Separate Answer Paper**: in the attempt's SAP workspace, run proposals on
  a registered page; accepting requires assigning a logical target and creates
  an attempt-only mapping (the shared profile is untouched).

Current active model: `core_ai2_detector_emergency_v1`
(val mAP50 0.9332 / test mAP50 0.9665 on held-out profile-grouped splits).

---

## 2. Core AI 1 — Kertas 2 draft scoring

### Data it trains on
Teacher-marked Kertas 2 essays with **explicit** evidence only: a blue
student-answer text layer, red teacher corrections (`old -> new` pairs), and
an explicit red score (`N/20`). The extractor refuses to guess: answers with
mixed correction types are excluded (`ambiguous_category`), score-only
answers are excluded (`no_explicit_corrections`), Kertas 1 papers are never
used, and duplicated essay text across files is excluded
(`duplicate_answer_text`).

Marked PDFs go in `dataset_raw/core_ai2/marked student answer/` with their
unmarked originals in `dataset_raw/core_ai2/Student Answer/<family>/`.
Recognised name patterns: `2022_K<n>_<Tier>_Marked`, `2023_K<n>_<Tier>_Marked`,
`2024_KM<n>_<Tier>_Marked`, `2025_Form5_Test5_<Tier>_Marked`, and
`Variant_<NN>_<family>_<Tier>` for additional attempts on the same paper.

### Train / register / activate
```
# 1. Extract honest records (writes candidate records + a full exclusion report):
python scripts/emergency_prepare_core_ai1_records.py ^
    --source "../dataset_raw/core_ai2" ^
    --workspace "../FYP-Data/core_ai1_emergency_training"

# 2. Export + audit with the REAL production exporter (blocks training below
#    30 records / 5 per category / 4 leakage-safe groups)  - see the printed
#    readiness audit. Only proceed when training_ready is true.

# 3. Train + evaluate + activate through the production pipeline (dataset is
#    frozen first; activation requires the passing evaluation):
python scripts/emergency_train_core_ai1_cross_encoder.py ^
    --dataset-src "<run>/frozen_dataset/dataset_<version>" ^
    --data-root "C:/Users/User/Documents/AutoMarkingSystem/english_grading_system/data" ^
    --base-model "<local MiniLM folder>"
```
The local base transformer (e.g. `sentence-transformers/all-MiniLM-L6-v2`)
must exist on disk; download once with
`python -c "from huggingface_hub import snapshot_download; snapshot_download('sentence-transformers/all-MiniLM-L6-v2', local_dir=r'<folder>')"`.

In-app alternative (fully supported): admin → **AI Models** → "Core AI 1
datasets, training & activation" → **Export from finalised records** →
**Freeze** → **Start training** (you pick a frozen training-ready dataset,
name the model version, and choose the local base Transformer folder) →
**Evaluate** → **Activate**. Training runs in a background worker.

### Verify it is active
Admin → **AI Models**: "Kertas 2 Short-Answer Scoring" card shows
*Active version in use (…)*; evaluation metrics are stored per model under
`data/ai/evaluations/core_ai1/`.

### Use it (teacher)
1. Marking → **Use for Marking** on a profile → upload/mark a student PDF →
   open its **Marking Editor**.
2. Click **"Generate AI Drafts"**. Each Kertas 2 essay row gets a draft
   score + feedback category in the *Draft (suggestion)* column.
3. Per row: **View Draft Details** (provenance: model version, checksum,
   dataset lineage, confidence, truncation), **Apply Draft to My Score**
   (copies score + category into YOUR review - still editable),
   **Dismiss Draft**, or simply enter your own score.
4. Nothing reaches a student until **Finalise Marking**.

Current active model: `core_ai1_cross_encoder_emergency_v2`, trained on 50
deduplicated records — test MAE ≈ 2.2 marks of 20, category accuracy 89%,
**small evaluation support (9 test samples)**: treat drafts as rough
suggestions and expect quality to grow with more marked papers.

### Improving it
Add more marked papers (new essays — verbatim duplicates are excluded
automatically), rerun steps 1–3 with a new dataset/model version, and
activate the new version. Old versions stay in the registry with their
evaluations; **Roll back** is available in the admin registry section.

---

## 3. Natural-language feedback (Ollama)

Two tiers, chosen automatically per generation:
- **Local LLM runtime** (when configured & reachable) — unique feedback about
  the specific essay.
- **Built-in deterministic templates** (always available offline) — wording
  from the flagged category + the teacher's score bands.

### One-time machine setup
```
winget install Ollama.Ollama        # installs + auto-starts on login
ollama pull llama3.2                # ~2 GB; or qwen2.5:7b for better quality
```

### Per-teacher app setup
Teacher sidebar → **Local AI Settings** → *Local Feedback Runtime*:
- Adapter: `ollama`
- Endpoint: `http://localhost:11434/api/chat`  (localhost only, by design)
- Model name: `llama3.2` (must match a pulled model)
- Timeout: `60` seconds (first call loads the model into VRAM, ~30 s)
- **Save Feedback Runtime**, then **Check Runtime** to confirm reachability.

(Any OpenAI-compatible local server also works: adapter `openai-compatible`
with e.g. `http://localhost:11434/v1/chat/completions`.)

### Use it (teacher)
In the Marking Editor, single-click an essay row → **"Draft Feedback
Wording"**. A dialog shows the drafted text and its provenance
(`your local runtime (llama3.2)` or `the built-in offline templates`);
**Save as my feedback** stores it as your editable feedback — nothing is
saved without that confirmation, and scores are never stated or changed
(score-like output is stripped; over-length output is shortened at a
sentence boundary).

If wording comes back as template text with "runtime unavailable", Ollama is
not running — start it and retry.

---

## 4. Prerequisite: the Kertas 2 answer key (marking scheme text)

Both draft scoring and feedback read the marking scheme from the profile's
**answer key**. Fill it per profile with one click:

Marking → **Open / Edit** the profile → **"Extract Answer Key from Answer
Scheme"**. This now fills BOTH papers:
- Kertas 1: OCRs the scheme's printed answers into Q1–Q40 entries.
- Kertas 2: extracts each writing Part's guidance/sample-answer text from the
  scheme's text layer into the Part 1/2/3 answer-box entries (20-mark default;
  a scanned scheme with no text layer reports the Parts as *missing* — enter
  the scheme text manually in Answer Key Setup in that case).

**Important:** the scheme text is copied into an attempt when **Mark
Answers** runs — for attempts marked before the answer key was filled, click
Mark Answers again so drafts/feedback can see the scheme.

---

## 5. Quick health checklist

| Check | Where | Expected |
|---|---|---|
| Core AI 2 active | Admin → AI Models → Answer Region Detection card | "Active version in use (…)" |
| Core AI 1 active | Admin → AI Models → Kertas 2 Short-Answer Scoring card | "Active version in use (…)" |
| Runtime diagnostics | Admin → AI Models → registry sections → Runtime check | torch + CUDA + GPU listed |
| Feedback runtime | Teacher → Local AI Settings → Check Runtime | reachable, model found |
| Region proposals | Profile editor → Core AI 2 Region Proposals (Page) | review dialog with proposals |
| Draft scoring | Marking Editor → Generate AI Drafts | "N draft suggestion(s)" |
| Natural feedback | Marking Editor → Draft Feedback Wording | wording sourced from "your local runtime" |

Common failure causes seen in practice:
- **"No active/compatible model"** → the model registry in the *current data
  root* has no active model (check which root you launched with).
- **Feedback is template wording** → Ollama not running, wrong model name, or
  endpoint typo; run Check Runtime.
- **Draft metadata says "truncated"** → essay + scheme exceed the model's
  input window (384 tokens); the draft still generates, but long schemes cost
  accuracy.
