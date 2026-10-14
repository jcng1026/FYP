"""Stage 12G-2 - the global AI Models page, owned by the technical developer/
admin role.

This page (model-family cards for Core AI 1 Kertas 2 scoring and Core AI 2
answer-region detection, plus dataset export / training / evaluation controls)
was previously on the TeacherDashboard. It is now a mixin inherited ONLY by the
DeveloperDashboard so teachers cannot reach the global registry through
navigation. The admin-only policy is additionally enforced at the service layer
by ai_admin_access_service.require_ai_models_access.

The mixin depends on the host dashboard providing:
- ``self._user`` (the logged-in User) - used for the access guard;
- being a QWidget (dialog parent).

It owns ``self._ai_owner_id`` (the admin's user id, used as the record owner in
the still-teacher-scoped registry/dataset services, whose guards were widened to
accept the admin - see user_service.validate_ai_manager_exists).
"""
import json
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHeaderView

from app.database.db import get_connection
from app.models import ai_admin_audit_model as ai_audit
from app.models.ai_model_registry_model import (
    MODEL_KEY_ANSWER_REGION_DETECTION,
    MODEL_KEY_K2_SHORT_ANSWER_SCORING,
)
from app.services import ai_admin_access_service as ai_access
from app.services import ai_models_core1_dataset_service as core1_admin
from app.services import ai_models_dataset_service as ds_admin
from app.services import ai_models_job_service as jobs_admin
from app.services.ai_backend_port import (
    BackendError,
    JOB_CANCELLING,
    NONTERMINAL_JOB_STATES,
    CONVERSION_FORMAT_COCO,
    CONVERSION_FORMAT_YOLO,
    JOB_COMPLETED,
    MODEL_FAMILY_CORE_AI1,
    MODEL_FAMILY_CORE_AI2,
    TERMINAL_JOB_STATES,
)
from app.services.ai_model_registry_service import (
    get_active_ai_model_version,
    get_supported_ai_model_specs,
    list_ai_training_jobs,
)
from app.services.k2_cross_encoder_evaluation_service import (
    has_active_k2_model_version,
    is_k2_evaluation_job,
    list_k2_training_only_jobs,
)
from app.services.k2_cross_encoder_training_service import has_k2_training_dataset
from app.services.k2_training_dataset_service import (
    export_k2_training_dataset,
    list_k2_training_datasets,
)
from app.services.region_detection_dataset_service import (
    export_region_detection_dataset_global,
    has_exportable_subject_profiles_global,
    list_region_detection_datasets,
)
from app.ui.components import CircularProgressWidget, CollapsibleSection, apply_card_shadow, create_page
from app.ui.dialogs import (
    CANCELLED,
    prompt_confirm,
    prompt_input,
    prompt_select,
    show_detail,
    show_error,
    show_success,
)
from app.ui.k2_evaluation_worker import K2EvaluationWorker
from app.ui.k2_training_worker import K2TrainingWorker

AI_MODEL_CARD_LABEL_MAX_WIDTH = 900


def _shorten_path_for_display(path_str: Optional[str], keep_parts: int = 3) -> str:
    """Return the last keep_parts path segments instead of a full, unbroken
    path - a QLabel can't word-wrap a path with no spaces, so shortening the
    text itself is what actually prevents page overflow."""
    if not path_str:
        return "Not available"
    parts = Path(path_str).parts
    if len(parts) <= keep_parts:
        return str(Path(path_str))
    return ".../" + "/".join(parts[-keep_parts:])


def _format_training_metrics_summary(metrics: Optional[dict]) -> str:
    """Short, readable one-line summary of training metrics - never raw JSON."""
    if not metrics:
        return "Not available"
    row_count = metrics.get("usable_row_count", metrics.get("row_count", "-"))
    val_mae = metrics.get("val_mae")
    val_mae_text = f"{val_mae:.4f}" if isinstance(val_mae, (int, float)) else "N/A"
    category_accuracy = metrics.get("category_accuracy")
    category_text = f"{category_accuracy:.1%}" if isinstance(category_accuracy, (int, float)) else "N/A"
    demo_text = "Demo data" if metrics.get("demo_mode") else "Real data"
    return f"Rows: {row_count} | Val MAE: {val_mae_text} | Category accuracy: {category_text} | {demo_text}"


def _format_evaluation_metrics_summary(metrics: Optional[dict]) -> str:
    """Short, readable one-line summary of evaluation metrics - never raw JSON."""
    if not metrics:
        return "None yet"
    row_count = metrics.get("usable_row_count", "-")
    mae = metrics.get("mean_absolute_error")
    mae_text = f"{mae:.4f}" if isinstance(mae, (int, float)) else "N/A"
    category_accuracy = metrics.get("category_accuracy")
    category_text = f"{category_accuracy:.1%}" if isinstance(category_accuracy, (int, float)) else "N/A"
    demo_text = "Demo evaluation" if metrics.get("demo_mode") else "Real evaluation"
    return f"Rows: {row_count} | MAE: {mae_text} | Category accuracy: {category_text} | {demo_text}"


class _AIBackendWorker(QThread):
    """Runs one potentially-long backend op off the UI thread.

    Carries a cooperative cancellation token so a long training or evaluation
    run can be stopped from the interface. Cancellation is requested, never
    forced: the operation stops at its next checkpoint, so nothing is left
    half-written.
    """
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, op, parent=None, cancellation_token=None) -> None:
        super().__init__(parent)
        self._op = op
        from app.services.ai_resilience_service import CancellationToken
        self.cancellation_token = cancellation_token or CancellationToken()

    def request_cancel(self) -> None:
        self.cancellation_token.cancel()

    def run(self) -> None:  # noqa: N802 - Qt override
        try:
            self.succeeded.emit(self._op())
        except Exception as exc:  # surfaced via failed signal
            self.failed.emit(str(exc))


class AIModelsAdminPageMixin:
    """AI Models page + handlers, inherited by the DeveloperDashboard only."""

    @property
    def _ai_owner_id(self) -> Optional[int]:
        user = getattr(self, "_user", None)
        return user.user_id if user is not None else None

    # --- page construction --------------------------------------------------

    def _build_ai_models_page(self) -> QWidget:
        page, layout = create_page()

        title = QLabel("AI Models")
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        subtitle = QLabel(
            "Global registry of this system's models - Core AI 1 (Kertas 2 scoring & feedback-category "
            "Cross-Encoder) and Core AI 2 (answer-region detector). Restricted to the technical "
            "developer/admin. Local AI Settings (a per-teacher page) is separate and unaffected.")
        subtitle.setObjectName("StatusLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self._ai_model_cards = {}
        for spec in get_supported_ai_model_specs():
            layout.addWidget(self._build_ai_model_card(spec))

        layout.addWidget(self._build_core_ai1_section())
        layout.addWidget(self._build_core_ai2_dataset_section())
        layout.addWidget(self._build_core_ai2_training_section())

        audit_section = CollapsibleSection("Recent AI-admin audit", expanded=False)
        self.ai_admin_audit_table = QTableWidget(0, 6)
        self.ai_admin_audit_table.setHorizontalHeaderLabels(
            ["Time", "Actor", "Role", "Action", "Outcome", "Target"])
        self.ai_admin_audit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ai_admin_audit_table.verticalHeader().setVisible(False)
        self.ai_admin_audit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ai_admin_audit_table.setMaximumHeight(220)
        audit_section.add_widget(self.ai_admin_audit_table)
        layout.addWidget(audit_section)

        layout.addStretch()
        return page

    def _build_ai_model_card(self, spec) -> QWidget:
        card = QGroupBox(spec.model_name)
        apply_card_shadow(card)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(4)

        purpose_label = QLabel(spec.purpose)
        purpose_label.setWordWrap(True)
        card_layout.addWidget(purpose_label)

        technique_label = QLabel(f"Technique: {spec.technique}")
        technique_label.setObjectName("StatusLabel")
        card_layout.addWidget(technique_label)

        status_label = QLabel("Status: Not trained yet")
        status_label.setObjectName("StatusLabel")
        card_layout.addWidget(status_label)

        active_version_label = QLabel("Active version: None")
        active_version_label.setObjectName("StatusLabel")
        card_layout.addWidget(active_version_label)

        last_job_label = QLabel("Last training job: None yet")
        last_job_label.setObjectName("StatusLabel")
        card_layout.addWidget(last_job_label)

        metrics_label = QLabel("Latest training: Not available")
        metrics_label.setObjectName("StatusLabel")
        metrics_label.setWordWrap(True)
        metrics_label.setMaximumWidth(AI_MODEL_CARD_LABEL_MAX_WIDTH)
        card_layout.addWidget(metrics_label)

        storage_label = QLabel("Storage path: Not available")
        storage_label.setObjectName("StatusLabel")
        storage_label.setWordWrap(True)
        storage_label.setMaximumWidth(AI_MODEL_CARD_LABEL_MAX_WIDTH)
        card_layout.addWidget(storage_label)

        recent_datasets_label = None
        if spec.model_key in (MODEL_KEY_K2_SHORT_ANSWER_SCORING, MODEL_KEY_ANSWER_REGION_DETECTION):
            recent_datasets_label = QLabel("Recent datasets: None yet")
            recent_datasets_label.setObjectName("StatusLabel")
            recent_datasets_label.setWordWrap(True)
            recent_datasets_label.setMaximumWidth(AI_MODEL_CARD_LABEL_MAX_WIDTH)
            card_layout.addWidget(recent_datasets_label)

        last_evaluation_label = None
        if spec.model_key == MODEL_KEY_K2_SHORT_ANSWER_SCORING:
            last_evaluation_label = QLabel("Last evaluation: None yet")
            last_evaluation_label.setObjectName("StatusLabel")
            last_evaluation_label.setWordWrap(True)
            last_evaluation_label.setMaximumWidth(AI_MODEL_CARD_LABEL_MAX_WIDTH)
            card_layout.addWidget(last_evaluation_label)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)

        is_k2 = spec.model_key == MODEL_KEY_K2_SHORT_ANSWER_SCORING
        start_training_button = QPushButton("Start Training")
        start_training_button.setEnabled(False)
        start_training_button.setToolTip(
            "Export a Kertas 2 training dataset first to enable this button."
            if is_k2 else "Use the Core AI 2 training section below for this model family.")
        if is_k2:
            start_training_button.clicked.connect(self.handle_start_k2_training)
        buttons_row.addWidget(start_training_button)

        evaluate_button = QPushButton("Evaluate")
        evaluate_button.setEnabled(False)
        evaluate_button.setToolTip(
            "Train a Kertas 2 model first to enable this button."
            if is_k2 else "Use the Core AI 2 training section below for this model family.")
        if is_k2:
            evaluate_button.clicked.connect(self.handle_evaluate_k2_model)
        buttons_row.addWidget(evaluate_button)

        export_dataset_button = None
        if spec.model_key == MODEL_KEY_K2_SHORT_ANSWER_SCORING:
            export_dataset_button = QPushButton("Export Training Dataset")
            export_dataset_button.setObjectName("RowActionButton")
            export_dataset_button.setCursor(Qt.CursorShape.PointingHandCursor)
            export_dataset_button.clicked.connect(self.handle_export_k2_training_dataset)
            buttons_row.addWidget(export_dataset_button)
        elif spec.model_key == MODEL_KEY_ANSWER_REGION_DETECTION:
            export_dataset_button = QPushButton("Export Training Dataset")
            export_dataset_button.setObjectName("RowActionButton")
            export_dataset_button.setCursor(Qt.CursorShape.PointingHandCursor)
            export_dataset_button.clicked.connect(self.handle_export_region_detection_dataset)
            buttons_row.addWidget(export_dataset_button)

        view_logs_button = QPushButton("View Logs")
        view_logs_button.setObjectName("RowActionButton")
        view_logs_button.setCursor(Qt.CursorShape.PointingHandCursor)
        view_logs_button.clicked.connect(
            lambda _checked=False, key=spec.model_key: self.handle_view_ai_model_logs(key))
        buttons_row.addWidget(view_logs_button)

        buttons_row.addStretch()
        card_layout.addLayout(buttons_row)

        self._ai_model_cards[spec.model_key] = {
            "status_label": status_label,
            "active_version_label": active_version_label,
            "last_job_label": last_job_label,
            "metrics_label": metrics_label,
            "storage_label": storage_label,
            "start_training_button": start_training_button,
            "evaluate_button": evaluate_button,
            "recent_datasets_label": recent_datasets_label,
            "export_dataset_button": export_dataset_button,
            "last_evaluation_label": last_evaluation_label,
        }
        return card

    # --- Core AI 2 dataset controls (Subsystem 2) ---------------------------
    #
    # Discovery / inspection / readiness audit / comparison / permanent freeze /
    # COCO+YOLO conversion, over the narrow CoreAI2DatasetPort (deterministic
    # fake until the Codex façade is merged - the descriptor + method names
    # already match the façade, so integration is a drop-in). Export validity,
    # frozen state and training readiness are shown as three SEPARATE columns;
    # there is no unfreeze and no conversion overwrite; training stays disabled
    # while readiness blockers remain.

    CORE_AI2_DATASET_COLUMNS = [
        "Version", "Export valid", "Frozen", "Training ready", "Regions", "Classes",
        "Excluded", "Split", "Leakage-safe", "Blockers"]

    def _build_core_ai2_dataset_section(self) -> QWidget:
        section = CollapsibleSection("Core AI 2 datasets (answer-region detector)", expanded=False)

        self.core_ai2_dataset_status = QLabel(
            "Frozen, export-valid and training-ready are independent. Freezing is permanent; there is "
            "no unfreeze. Conversions never overwrite an existing version. Training is blocked while "
            "readiness blockers remain.")
        self.core_ai2_dataset_status.setObjectName("StatusLabel")
        self.core_ai2_dataset_status.setWordWrap(True)
        section.add_widget(self.core_ai2_dataset_status)

        self.core_ai2_dataset_table = QTableWidget(0, len(self.CORE_AI2_DATASET_COLUMNS))
        self.core_ai2_dataset_table.setHorizontalHeaderLabels(self.CORE_AI2_DATASET_COLUMNS)
        self.core_ai2_dataset_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.core_ai2_dataset_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.core_ai2_dataset_table.verticalHeader().setVisible(False)
        self.core_ai2_dataset_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.core_ai2_dataset_table.setMaximumHeight(200)
        self.core_ai2_dataset_table.itemSelectionChanged.connect(self._on_core_ai2_dataset_selected)
        section.add_widget(self.core_ai2_dataset_table)

        self._core_ai2_dataset_versions = []

        buttons = QHBoxLayout()
        for text, slot, attr in (
            ("Refresh", self.handle_refresh_core_ai2_datasets, "core_ai2_refresh_button"),
            ("Inspect", self.handle_inspect_core_ai2_dataset, "core_ai2_inspect_button"),
            ("Re-check integrity", self.handle_audit_core_ai2_dataset, "core_ai2_audit_button"),
            ("Compare two", self.handle_compare_core_ai2_datasets, "core_ai2_compare_button"),
            ("Freeze (permanent)", self.handle_freeze_core_ai2_dataset, "core_ai2_freeze_button"),
            ("Convert to YOLO", lambda: self.handle_convert_core_ai2_dataset(CONVERSION_FORMAT_YOLO),
             "core_ai2_yolo_button"),
            ("Convert to COCO", lambda: self.handle_convert_core_ai2_dataset(CONVERSION_FORMAT_COCO),
             "core_ai2_coco_button"),
        ):
            button = QPushButton(text)
            button.setObjectName("RowActionButton")
            button.clicked.connect(slot)
            setattr(self, attr, button)
            buttons.addWidget(button)
        buttons.addStretch()
        buttons_wrap = QWidget()
        buttons_wrap.setLayout(buttons)
        section.add_widget(buttons_wrap)

        self.core_ai2_dataset_section = section
        return section

    def _selected_core_ai2_dataset(self):
        row = self.core_ai2_dataset_table.currentRow()
        versions = getattr(self, "_core_ai2_dataset_versions", [])
        return versions[row] if 0 <= row < len(versions) else None

    def _refresh_core_ai2_datasets(self, conn) -> None:
        if not hasattr(self, "core_ai2_dataset_table"):
            return
        try:
            datasets = ds_admin.list_datasets(conn, getattr(self, "_user", None))
        except ai_access.AIPermissionError:
            return
        except BackendError as exc:
            self.core_ai2_dataset_status.setText(f"Backend unavailable: {exc.safe_message}")
            self.core_ai2_dataset_table.setRowCount(0)
            self._core_ai2_dataset_versions = []
            return
        self._core_ai2_dataset_versions = [d.version for d in datasets]
        self.core_ai2_dataset_table.setRowCount(len(datasets))
        for r, d in enumerate(datasets):
            stats = d.statistics
            cells = [
                d.version, "Yes" if d.export_valid else "No", "Yes" if d.frozen else "No",
                "Yes" if d.training_ready else "No", stats.get("region_count", "-"),
                stats.get("class_count", "-"), stats.get("excluded_region_count", "-"),
                d.split_mode or "-",
                "Yes" if stats.get("leakage_safe_split") else "No",
                "; ".join(d.blockers) if d.blockers else "-",
            ]
            for c, value in enumerate(cells):
                self.core_ai2_dataset_table.setItem(r, c, QTableWidgetItem(str(value)))
        self._on_core_ai2_dataset_selected()

    def _on_core_ai2_dataset_selected(self) -> None:
        # Freeze only an export-valid, not-yet-frozen dataset; convert only a
        # frozen one - the button states never contradict the backend rules.
        if not hasattr(self, "core_ai2_freeze_button"):
            return
        version = self._selected_core_ai2_dataset()
        descriptor = None
        if version is not None:
            conn = get_connection()
            try:
                descriptor = ds_admin.inspect_dataset(conn, getattr(self, "_user", None), version)
            except (ai_access.AIPermissionError, BackendError):
                descriptor = None
            finally:
                conn.close()
        can_freeze = bool(descriptor and descriptor.export_valid and not descriptor.frozen)
        can_convert = bool(descriptor and descriptor.frozen)
        self.core_ai2_freeze_button.setEnabled(can_freeze)
        self.core_ai2_yolo_button.setEnabled(can_convert)
        self.core_ai2_coco_button.setEnabled(can_convert)
        for attr in ("core_ai2_inspect_button", "core_ai2_audit_button"):
            getattr(self, attr).setEnabled(descriptor is not None)

    def handle_refresh_core_ai2_datasets(self) -> None:
        conn = get_connection()
        try:
            self._refresh_core_ai2_datasets(conn)
        finally:
            conn.close()

    def handle_inspect_core_ai2_dataset(self) -> None:
        version = self._selected_core_ai2_dataset()
        if version is None:
            show_error(self, "Inspect Dataset", "Select a dataset first.")
            return
        conn = get_connection()
        try:
            d = ds_admin.inspect_dataset(conn, self._user, version)
        except BackendError as exc:
            show_error(self, "Inspect Dataset", exc.safe_message)
            return
        finally:
            conn.close()
        stats = d.statistics
        show_detail(
            self, f"Dataset {d.version}",
            f"Export valid: {d.export_valid}\nFrozen: {d.frozen}\nTraining ready: {d.training_ready}\n"
            f"Schema: {d.schema_version or '-'} | Mapping: {d.mapping_version or '-'}\n"
            f"Split mode: {d.split_mode or '-'} | Leakage-safe: {stats.get('leakage_safe_split')}\n"
            f"Profiles: {stats.get('profile_count','-')} | Pages: {stats.get('page_count','-')} | "
            f"Regions: {stats.get('region_count','-')} | Classes: {stats.get('class_count','-')}\n"
            f"Excluded/unsupported regions: {stats.get('excluded_region_count','-')}/"
            f"{stats.get('unsupported_region_count','-')}\n"
            f"Supported conversions: {', '.join(d.supported_formats) or '-'}\n"
            f"Blockers: {'; '.join(d.blockers) or 'None'}\n"
            f"Warnings: {'; '.join(d.warnings) or 'None'}\n"
            f"Recommendations: {'; '.join(stats.get('recommendations', [])) or 'None'}")

    def handle_audit_core_ai2_dataset(self) -> None:
        version = self._selected_core_ai2_dataset()
        if version is None:
            show_error(self, "Re-check Integrity", "Select a dataset first.")
            return
        conn = get_connection()
        try:
            report = ds_admin.audit_dataset(conn, self._user, version)
        except BackendError as exc:
            show_error(self, "Re-check Integrity", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(
            self, f"Integrity re-check - {version}",
            f"Result: {'OK' if report.ok else 'Problems found'}\nChecked at: {report.checked_at}\n"
            f"Findings: {'; '.join(report.findings) or 'None'}\n"
            f"Recommendations: {'; '.join(report.recommendations) or 'None'}")

    def handle_compare_core_ai2_datasets(self) -> None:
        versions = getattr(self, "_core_ai2_dataset_versions", [])
        if len(versions) < 2:
            show_error(self, "Compare Datasets", "At least two datasets are needed to compare.")
            return
        left = self._selected_core_ai2_dataset() or versions[0]
        others = [(v, v) for v in versions if v != left]
        right = prompt_select(self, "Compare Datasets", f"Compare {left} against:", others)
        if right is CANCELLED:
            return
        conn = get_connection()
        try:
            cmp = ds_admin.compare_datasets(conn, self._user, left, right)
        except BackendError as exc:
            show_error(self, "Compare Datasets", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(self, f"{left} vs {right}",
                    "Differences:\n" + ("\n".join(cmp.differences) if cmp.differences else "None"))

    def handle_freeze_core_ai2_dataset(self) -> None:
        version = self._selected_core_ai2_dataset()
        if version is None:
            show_error(self, "Freeze Dataset", "Select a dataset first.")
            return
        # Explicit, permanent-action confirmation is REQUIRED before freezing.
        if not prompt_confirm(
            self, "Freeze Dataset (permanent)",
            f"Freeze '{version}'? Freezing is PERMANENT - there is no unfreeze. Only freeze a dataset "
            "whose labels you have reviewed. A frozen dataset is still not training-ready unless the "
            "backend reports it as such.", confirm_text="Freeze permanently"):
            return
        conn = get_connection()
        try:
            ds_admin.freeze_dataset(conn, self._user, version)
        except BackendError as exc:
            show_error(self, "Freeze Dataset", exc.safe_message)
            return
        finally:
            conn.close()
        self.handle_refresh_core_ai2_datasets()
        show_success(self, "Freeze Dataset", f"Dataset '{version}' is now frozen (permanent).")

    def handle_convert_core_ai2_dataset(self, output_format: str) -> None:
        version = self._selected_core_ai2_dataset()
        if version is None:
            show_error(self, "Convert Dataset", "Select a frozen dataset first.")
            return
        conversion_version = prompt_input(
            self, f"Convert to {output_format.upper()}",
            "Conversion version label (an existing conversion is never overwritten):")
        if not conversion_version or not str(conversion_version).strip():
            return
        conn = get_connection()
        try:
            result = ds_admin.convert_dataset(conn, self._user, version, output_format,
                                              str(conversion_version).strip())
        except BackendError as exc:
            show_error(self, "Convert Dataset", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(self, "Convert Dataset",
                    f"{output_format.upper()} conversion '{result.conversion_version}' created.\n"
                    f"Output: {result.output_path}\nChecksum: {result.checksum or '-'}")

    # --- Core AI 2 training / evaluation / activation (Subsystem 3) ---------
    #
    # Training and evaluation run in a background worker (never the UI thread).
    # Progress is a factual message plus a percentage ONLY when the backend
    # supplies one. Activation requires a passing evaluation; failed/cancelled
    # jobs never publish or activate a model. Model+dataset lineage stays
    # visible. Interrupted jobs are recovered (never silently resumed).

    CORE_AI2_MODEL_COLUMNS = ["Version", "Evaluation", "Activation", "Source dataset", "Runtime", "Job"]
    CORE_AI2_JOB_COLUMNS = ["Job", "Status", "Progress", "Dataset", "Result model"]

    def _build_core_ai2_training_section(self) -> QWidget:
        section = CollapsibleSection("Core AI 2 training, evaluation & activation", expanded=False)

        self.core_ai2_training_status = QLabel(
            "Training/evaluation run in the background. A model can be activated only after a passing "
            "evaluation; failed or cancelled jobs never publish a model. There is no auto-activation.")
        self.core_ai2_training_status.setObjectName("StatusLabel")
        self.core_ai2_training_status.setWordWrap(True)
        section.add_widget(self.core_ai2_training_status)

        self.core_ai2_models_table = QTableWidget(0, len(self.CORE_AI2_MODEL_COLUMNS))
        self.core_ai2_models_table.setHorizontalHeaderLabels(self.CORE_AI2_MODEL_COLUMNS)
        self.core_ai2_models_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.core_ai2_models_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.core_ai2_models_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.core_ai2_models_table.verticalHeader().setVisible(False)
        self.core_ai2_models_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.core_ai2_models_table.setMaximumHeight(160)
        self.core_ai2_models_table.itemSelectionChanged.connect(self._on_core_ai2_model_selected)
        section.add_widget(self.core_ai2_models_table)
        self._core_ai2_model_versions = []

        self.core_ai2_jobs_table = QTableWidget(0, len(self.CORE_AI2_JOB_COLUMNS))
        self.core_ai2_jobs_table.setHorizontalHeaderLabels(self.CORE_AI2_JOB_COLUMNS)
        self.core_ai2_jobs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.core_ai2_jobs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.core_ai2_jobs_table.verticalHeader().setVisible(False)
        self.core_ai2_jobs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.core_ai2_jobs_table.setMaximumHeight(140)
        self.core_ai2_jobs_table.itemSelectionChanged.connect(self._on_core_ai2_model_selected)
        section.add_widget(self.core_ai2_jobs_table)
        self._core_ai2_job_ids = []

        buttons = QHBoxLayout()
        for text, slot, attr in (
            ("Start training", self.handle_start_core_ai2_training, "core_ai2_start_training_button"),
            ("Cancel job", self.handle_cancel_core_ai2_job, "core_ai2_cancel_job_button"),
            ("Evaluate", self.handle_evaluate_core_ai2_model, "core_ai2_evaluate_button"),
            ("Compare models", self.handle_compare_core_ai2_models, "core_ai2_compare_models_button"),
            ("Activate", self.handle_activate_core_ai2_model, "core_ai2_activate_button"),
            ("Roll back", self.handle_rollback_core_ai2_model, "core_ai2_rollback_button"),
            ("Runtime check", self.handle_core_ai2_runtime_check, "core_ai2_runtime_button"),
        ):
            button = QPushButton(text)
            button.setObjectName("RowActionButton")
            button.clicked.connect(slot)
            setattr(self, attr, button)
            buttons.addWidget(button)
        buttons.addStretch()
        buttons_wrap = QWidget()
        buttons_wrap.setLayout(buttons)
        section.add_widget(buttons_wrap)

        self.core_ai2_training_section = section
        return section

    def _selected_core_ai2_model(self):
        row = self.core_ai2_models_table.currentRow()
        versions = getattr(self, "_core_ai2_model_versions", [])
        return versions[row] if 0 <= row < len(versions) else None

    def _selected_core_ai2_job(self):
        row = self.core_ai2_jobs_table.currentRow()
        ids = getattr(self, "_core_ai2_job_ids", [])
        return ids[row] if 0 <= row < len(ids) else None

    def _recover_interrupted_ai_jobs_once(self, conn) -> None:
        """Once per page lifetime, recover jobs abandoned by a previous run
        (they become 'interrupted' - never silently resumed)."""
        if getattr(self, "_ai_jobs_recovered", False):
            return
        self._ai_jobs_recovered = True
        try:
            jobs_admin.recover_interrupted_jobs(conn, getattr(self, "_user", None))
        except (ai_access.AIPermissionError, BackendError):
            pass

    def _refresh_core_ai2_training(self, conn) -> None:
        if not hasattr(self, "core_ai2_models_table"):
            return
        user = getattr(self, "_user", None)
        try:
            models = jobs_admin.list_models(conn, user)
            jobs = jobs_admin.list_training_jobs(conn, user)
        except ai_access.AIPermissionError:
            return
        except BackendError as exc:
            self.core_ai2_training_status.setText(f"Backend unavailable: {exc.safe_message}")
            return
        self._core_ai2_model_versions = [m.version for m in models]
        self.core_ai2_models_table.setRowCount(len(models))
        for r, m in enumerate(models):
            cells = [m.version, m.evaluation_status, m.activation_status, m.source_dataset_version,
                     m.runtime_compatibility, m.training_job_id]
            for c, value in enumerate(cells):
                self.core_ai2_models_table.setItem(r, c, QTableWidgetItem(str(value)))

        self._core_ai2_job_ids = [j.job_id for j in jobs]
        self._core_ai2_job_status = {j.job_id: j.status for j in jobs}
        self.core_ai2_jobs_table.setRowCount(len(jobs))
        for r, j in enumerate(jobs):
            progress = j.progress_message + (f" ({j.progress_value:.0f}%)" if j.progress_value is not None else "")
            cells = [j.job_id, j.status, progress, j.dataset_version, j.result_model_version or "-"]
            for c, value in enumerate(cells):
                self.core_ai2_jobs_table.setItem(r, c, QTableWidgetItem(str(value)))
        self._on_core_ai2_model_selected()
        if not self._ai_job_worker_running():
            self._clear_ai_status(MODEL_FAMILY_CORE_AI2)

    def _on_core_ai2_model_selected(self) -> None:
        if not hasattr(self, "core_ai2_activate_button"):
            return
        version = self._selected_core_ai2_model()
        descriptor = None
        if version is not None:
            conn = get_connection()
            try:
                descriptor = jobs_admin.inspect_model(conn, getattr(self, "_user", None), version)
            except (ai_access.AIPermissionError, BackendError):
                descriptor = None
            finally:
                conn.close()
        # Activation requires a passing evaluation; rollback needs an evaluated
        # (activatable) target too.
        can_activate = bool(descriptor and descriptor.evaluation_status == "passed"
                            and descriptor.activation_status != "active")
        self.core_ai2_activate_button.setEnabled(can_activate)
        self.core_ai2_rollback_button.setEnabled(bool(descriptor and descriptor.evaluation_status == "passed"))
        self.core_ai2_evaluate_button.setEnabled(descriptor is not None
                                                 and not self._ai_job_worker_running())
        self._refresh_cancel_button("core_ai2_cancel_job_button", self._selected_core_ai2_job(),
                                    getattr(self, "_core_ai2_job_status", {}))

    def _ai_job_worker_running(self) -> bool:
        worker = getattr(self, "_ai_job_worker", None)
        return worker is not None and worker.isRunning()

    def _ai_status_label(self, family: str):
        attr = ("core_ai1_status" if family == MODEL_FAMILY_CORE_AI1
                else "core_ai2_training_status")
        return getattr(self, attr, None)

    # The neutral resting text for each family's status line. Any refusal or
    # completion message is transient: it is cleared as soon as the state it
    # described no longer applies, so a successful screen never keeps showing
    # an unrelated earlier refusal.
    CORE_AI1_IDLE_STATUS = (
        "Datasets are exported from FINALISED teacher-reviewed Kertas 2 answers only. Freezing is "
        "permanent. Training needs a training-ready dataset; activation needs a passing "
        "evaluation. Export, training and evaluation run in the background.")
    CORE_AI2_IDLE_STATUS = (
        "Training/evaluation run in the background. A model can be activated only after a passing "
        "evaluation; failed or cancelled jobs never publish a model. There is no auto-activation.")

    def _set_ai_status(self, family: str, message: str) -> None:
        label = self._ai_status_label(family)
        if label is not None:
            label.setText(message)

    def _idle_status_text(self, family: str) -> str:
        return (self.CORE_AI1_IDLE_STATUS if family == MODEL_FAMILY_CORE_AI1
                else self.CORE_AI2_IDLE_STATUS)

    def _clear_ai_status(self, family: str, message: Optional[str] = None) -> None:
        """Drop a stale action message. Called whenever the registry or dataset
        state changes, and after a request starts or an action succeeds.

        A message describing the action that JUST completed is held as pending
        and re-applied, so a refresh clears an obsolete refusal without also
        discarding the confirmation the teacher needs to read.
        """
        pending = getattr(self, "_pending_ai_status", None)
        if message is None and pending is not None and pending[0] == family:
            self._pending_ai_status = None
            self._set_ai_status(family, pending[1])
            return
        self._set_ai_status(family, message or self._idle_status_text(family))

    def _run_ai_backend_op(self, op: Callable, on_success, busy_message: str,
                           family: str = MODEL_FAMILY_CORE_AI2) -> None:
        """Run a potentially-long backend op off the UI thread. One AI job at a
        time across both families - the shared worker guard prevents overlap."""
        if self._ai_job_worker_running():
            show_error(self, "AI Job Busy", "Another AI job is already running.")
            return
        self._ai_op_family = family
        self._set_ai_status(family, busy_message)
        worker = _AIBackendWorker(op)
        worker.succeeded.connect(lambda result: self._on_ai_backend_op_done(result, on_success))
        worker.failed.connect(self._on_ai_backend_op_failed)
        self._ai_job_worker = worker
        self._refresh_ai_job_buttons()
        worker.start()

    def _refresh_ai_job_buttons(self) -> None:
        busy = self._ai_job_worker_running()
        for attr in ("core_ai2_start_training_button", "core_ai2_evaluate_button",
                     "core_ai1_start_training_button", "core_ai1_evaluate_button",
                     "core_ai1_export_button"):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(not busy)

    # Kept as the historical name used by Subsystem 3 callers/tests.
    _refresh_core_ai2_training_buttons = _refresh_ai_job_buttons

    def _on_ai_backend_op_done(self, result, on_success) -> None:
        family = getattr(self, "_ai_op_family", MODEL_FAMILY_CORE_AI2)
        self._ai_job_worker = None
        try:
            if on_success is not None:
                on_success(result)
        finally:
            conn = get_connection()
            try:
                if family == MODEL_FAMILY_CORE_AI1:
                    self._refresh_core_ai1(conn)
                else:
                    self._refresh_core_ai2_training(conn)
            finally:
                conn.close()
            self._set_ai_status(family, "Ready.")
            self._refresh_ai_job_buttons()

    def _on_ai_backend_op_failed(self, message: str) -> None:
        # Stage 12G-9: shown through the shared safe-message layer so a backend
        # path, prompt or stack trace can never reach the screen.
        from app.services import ai_resilience_service as resilience
        self._ai_job_worker = None
        self._set_ai_status(getattr(self, "_ai_op_family", MODEL_FAMILY_CORE_AI2), "Ready.")
        self._refresh_ai_job_buttons()
        show_error(self, "AI Job Failed",
                   resilience.describe_failure(message, include_manual_note=False))

    def handle_start_core_ai2_training(self) -> None:
        conn = get_connection()
        try:
            datasets = ds_admin.list_datasets(conn, self._user)
        except BackendError as exc:
            show_error(self, "Start Training", exc.safe_message)
            return
        finally:
            conn.close()
        ready = [d.version for d in datasets if d.frozen and d.training_ready]
        if not ready:
            show_error(self, "Start Training",
                       "No dataset is ready for training. A dataset must be frozen AND "
                       "training-ready with a leakage-safe split. Inspect a dataset to see its "
                       "readiness blockers.")
            return
        dataset_version = prompt_select(self, "Start Training", "Training-ready dataset:",
                                        [(v, v) for v in ready])
        if dataset_version is CANCELLED:
            return
        conversions = self._list_yolo_conversions(dataset_version)
        if not conversions:
            show_error(self, "Start Training",
                       "This dataset has no YOLO conversion yet. Use 'Convert to YOLO' on the "
                       "frozen dataset first, then start training.")
            return
        conversion_version = prompt_select(
            self, "Start Training", "YOLO conversion to train from:",
            [(c, c) for c in conversions])
        if conversion_version is CANCELLED:
            return
        target = prompt_input(self, "Start Training", "New model version label:")
        if not target or not str(target).strip():
            return
        checkpoint = QFileDialog.getOpenFileName(
            self, "Choose the local base detector checkpoint (e.g. yolo11n.pt)",
            self._default_base_checkpoint_dir(), "PyTorch checkpoints (*.pt)")[0]
        if not checkpoint:
            return
        config = {
            "target_version": str(target).strip(),
            "conversion_version": conversion_version,
            "local_base_checkpoint": checkpoint,
        }
        conn = get_connection()
        try:
            blockers = jobs_admin.validate_training_request(conn, self._user, dataset_version, config)
        finally:
            conn.close()
        if blockers:
            show_error(self, "Start Training", "Cannot start:\n" + "\n".join(blockers))
            return

        def _op():
            c = get_connection()
            try:
                job = jobs_admin.create_training_job(c, self._user, dataset_version, config)
                # run_training_job may block - this whole op is off the UI thread.
                return jobs_admin.run_training_job(c, self._user, job.job_id, config)
            finally:
                c.close()

        def _on_ok(job):
            if job.status == "completed":
                show_success(self, "Training Completed",
                             f"Model '{job.result_model_version}' trained. Evaluate it before activation.")
            else:
                show_detail(self, "Training Finished", f"Job {job.job_id} ended as: {job.status}")

        self._run_ai_backend_op(_op, _on_ok, "Training in progress (background)...")

    def _request_worker_cancel(self) -> None:
        """Ask any running AI worker to stop at its next checkpoint."""
        worker = getattr(self, "_ai_job_worker", None)
        if worker is not None and worker.isRunning():
            worker.request_cancel()

    def _refresh_cancel_button(self, attr: str, job_id, statuses: dict) -> None:
        """Cancel applies only to a job that is still running. A terminal job -
        cancelled, completed, failed or interrupted - and a job already
        cancelling cannot be cancelled again."""
        button = getattr(self, attr, None)
        if button is None:
            return
        status = statuses.get(job_id)
        button.setEnabled(bool(job_id) and status in NONTERMINAL_JOB_STATES
                          and status != JOB_CANCELLING)

    def _cancel_job_to_terminal(self, job_id: str, family: str) -> None:
        """Cancel a job and follow it through to its TERMINAL state.

        The worker is asked to stop, the backend records 'cancelling', and once
        the worker has actually finished the cancellation is finalised so the
        job reaches 'cancelled'. A cancelled job publishes no model or
        evaluation, and models from earlier jobs are untouched.
        """
        self._request_worker_cancel()
        worker = getattr(self, "_ai_job_worker", None)
        if worker is not None and worker.isRunning():
            # Give the worker a bounded moment to observe the token and stop
            # cleanly, so the thread terminates before we finalise.
            worker.wait(5000)
        conn = get_connection()
        try:
            jobs_admin.cancel_training_job(conn, self._user, job_id, family=family)
        except BackendError as exc:
            show_error(self, "Cancel Job", exc.safe_message)
            return
        finally:
            conn.close()
        self._finalize_cancelled_job(job_id, family)

    def _finalize_cancelled_job(self, job_id: str, family: str) -> None:
        """Poll the cancelling job through to 'cancelled'."""
        conn = get_connection()
        try:
            job = jobs_admin.finalize_cancelled_job(conn, self._user, job_id, family=family)
            self._pending_ai_status = (
                family,
                f"Job {job_id} was cancelled ({job.status}). No model or evaluation was "
                "published; previously trained models are unchanged.")
        except BackendError:
            pass  # a job that never reached 'cancelling' needs no finalisation
        finally:
            conn.close()

    def handle_cancel_core_ai2_job(self) -> None:
        job_id = self._selected_core_ai2_job()
        if job_id is None:
            show_error(self, "Cancel Job", "Select a job first.")
            return
        if not prompt_confirm(self, "Cancel Training Job", f"Request cancellation of {job_id}?",
                              confirm_text="Cancel job"):
            return
        self._cancel_job_to_terminal(job_id, MODEL_FAMILY_CORE_AI2)
        self.handle_refresh_core_ai2_training()

    def handle_evaluate_core_ai2_model(self) -> None:
        version = self._selected_core_ai2_model()
        if version is None:
            show_error(self, "Evaluate", "Select a model first.")
            return
        conn = get_connection()
        try:
            datasets = ds_admin.list_datasets(conn, self._user)
        finally:
            conn.close()
        options = [(d.version, d.version) for d in datasets]
        dataset_version = prompt_select(self, "Evaluate Model", "Evaluate against dataset:", options)
        if dataset_version is CANCELLED:
            return

        def _op():
            c = get_connection()
            try:
                return jobs_admin.evaluate_model(c, self._user, version, dataset_version)
            finally:
                c.close()

        def _on_ok(result):
            show_detail(self, "Evaluation Complete",
                        f"Model: {result.model_version}\nPassed: {result.passed}\n"
                        f"Metrics: {result.metrics}\nDecision criteria: {result.decision_criteria}")

        self._run_ai_backend_op(_op, _on_ok, "Evaluating (background)...")

    def handle_compare_core_ai2_models(self) -> None:
        versions = getattr(self, "_core_ai2_model_versions", [])
        if len(versions) < 2:
            show_error(self, "Compare Models", "At least two models are needed.")
            return
        left = self._selected_core_ai2_model() or versions[0]
        right = prompt_select(self, "Compare Models", f"Compare {left} against:",
                              [(v, v) for v in versions if v != left])
        if right is CANCELLED:
            return
        conn = get_connection()
        try:
            cmp = jobs_admin.compare_models(conn, self._user, left, right)
        except BackendError as exc:
            show_error(self, "Compare Models", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(self, f"{left} vs {right}",
                    "Differences:\n" + ("\n".join(cmp.differences) if cmp.differences else "None"))

    def handle_activate_core_ai2_model(self) -> None:
        version = self._selected_core_ai2_model()
        if version is None:
            show_error(self, "Activate Model", "Select a model first.")
            return
        reason = prompt_input(self, "Activate Model",
                              "Reason for activation (recorded in activation history):")
        if not reason or not str(reason).strip():
            return
        if not prompt_confirm(self, "Activate Model",
                              f"Activate '{version}' as the live model? Only an evaluated (passing) "
                              "model can be activated.", confirm_text="Activate"):
            return
        conn = get_connection()
        try:
            jobs_admin.activate_model(conn, self._user, version, reason=str(reason).strip())
        except BackendError as exc:
            show_error(self, "Activate Model", exc.safe_message)
            return
        finally:
            conn.close()
        self.handle_refresh_core_ai2_training()
        self._clear_ai_status(MODEL_FAMILY_CORE_AI2,
                              f"'{version}' is now the active Core AI 2 model.")
        show_success(self, "Activate Model", f"'{version}' is now the active Core AI 2 model.")

    def handle_rollback_core_ai2_model(self) -> None:
        version = self._selected_core_ai2_model()
        if version is None:
            show_error(self, "Roll Back", "Select the model version to roll back to.")
            return
        reason = prompt_input(self, "Roll Back Model", "Reason for rollback (recorded in history):")
        if not reason or not str(reason).strip():
            return
        if not prompt_confirm(self, "Roll Back Model",
                              f"Roll back to '{version}'? It must be an evaluated (passing) version.",
                              confirm_text="Roll back"):
            return
        conn = get_connection()
        try:
            jobs_admin.rollback_model(conn, self._user, version, reason=str(reason).strip())
        except BackendError as exc:
            show_error(self, "Roll Back", exc.safe_message)
            return
        finally:
            conn.close()
        self.handle_refresh_core_ai2_training()
        show_success(self, "Roll Back", f"Rolled back - '{version}' is now active.")

    def handle_core_ai2_runtime_check(self) -> None:
        version = self._selected_core_ai2_model()
        conn = get_connection()
        try:
            runtime = jobs_admin.inspect_runtime(conn, self._user, model_version=version)
        except BackendError as exc:
            show_error(self, "Runtime Check", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(self, "Runtime Compatibility",
                    f"Memory status: {runtime.memory_status}\n"
                    f"Manual mode available without AI: {runtime.graceful_no_ai_mode}\n"
                    f"Warnings: {'; '.join(runtime.warnings) or 'None'}\n"
                    f"Blockers: {'; '.join(runtime.blockers) or 'None'}")

    def handle_refresh_core_ai2_training(self) -> None:
        conn = get_connection()
        try:
            self._refresh_core_ai2_training(conn)
        finally:
            conn.close()

    def refresh_ai_models_page(self) -> None:
        if self._ai_owner_id is None or not hasattr(self, "_ai_model_cards"):
            return
        conn = get_connection()
        try:
            # Enforce + audit the admin-only boundary (defends a direct call
            # even though only the admin dashboard builds this page).
            try:
                ai_access.require_ai_models_access(conn, getattr(self, "_user", None))
            except ai_access.AIPermissionError:
                return
            self._refresh_ai_model_cards(conn)
            self._refresh_core_ai1(conn)
            self._refresh_core_ai2_datasets(conn)
            self._recover_interrupted_ai_jobs_once(conn)
            self._refresh_core_ai2_training(conn)
            self._refresh_ai_admin_audit(conn)
        finally:
            conn.close()

    def _refresh_ai_admin_audit(self, conn) -> None:
        if not hasattr(self, "ai_admin_audit_table"):
            return
        entries = ai_audit.list_ai_admin_audit(conn, limit=50)
        self.ai_admin_audit_table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            cells = [e.created_at, e.actor_user_id if e.actor_user_id is not None else "-",
                     e.actor_role or "-", e.action, e.outcome, e.target or "-"]
            for c, value in enumerate(cells):
                self.ai_admin_audit_table.setItem(r, c, QTableWidgetItem(str(value)))

    def _backend_active_model(self, conn, model_key):
        """The Core AI backend registry's active model for this card's family,
        or None when there is none / the backend is unavailable. Used only as
        a fallback when the legacy per-admin registry has no active row."""
        family = (MODEL_FAMILY_CORE_AI2 if model_key == MODEL_KEY_ANSWER_REGION_DETECTION
                  else MODEL_FAMILY_CORE_AI1)
        try:
            return jobs_admin.get_active_model(conn, getattr(self, "_user", None),
                                               family=family)
        except (ai_access.AIPermissionError, BackendError):
            return None

    def _refresh_ai_model_cards(self, conn) -> None:
        owner = self._ai_owner_id
        for model_key, widgets in self._ai_model_cards.items():
            active = get_active_ai_model_version(conn, owner, model_key)
            if model_key == MODEL_KEY_K2_SHORT_ANSWER_SCORING:
                jobs = list_k2_training_only_jobs(conn, owner, limit=1)
            else:
                jobs = list_ai_training_jobs(conn, owner, model_key, limit=1)
            latest_job = jobs[0] if jobs else None

            if active is not None:
                training_metrics = None
                if active.metrics_json:
                    try:
                        training_metrics = {k: v for k, v in json.loads(active.metrics_json).items()
                                            if k != "evaluation"}
                    except json.JSONDecodeError:
                        training_metrics = None
                widgets["status_label"].setText(f"Status: Active version in use ({active.version_label})")
                widgets["active_version_label"].setText(f"Active version: {active.version_label}")
                widgets["metrics_label"].setText(
                    f"Latest training: {_format_training_metrics_summary(training_metrics)}")
                widgets["storage_label"].setText(f"Storage path: {_shorten_path_for_display(active.model_path)}")
                widgets["storage_label"].setToolTip(active.model_path or "")
            else:
                # No legacy in-app training row - the model may still have been
                # registered/activated through the Core AI backend registry
                # (e.g. trained outside this panel and imported).
                backend_active = self._backend_active_model(conn, model_key)
                if backend_active is not None:
                    widgets["status_label"].setText(
                        f"Status: Active version in use ({backend_active.version})")
                    widgets["active_version_label"].setText(
                        f"Active version: {backend_active.version}")
                    widgets["metrics_label"].setText(
                        "Latest training: see the Core AI registry section below")
                    widgets["storage_label"].setText(
                        f"Storage path: {_shorten_path_for_display(backend_active.path)}")
                    widgets["storage_label"].setToolTip(backend_active.path or "")
                else:
                    widgets["status_label"].setText("Status: Not trained yet")
                    widgets["active_version_label"].setText("Active version: None")
                    widgets["metrics_label"].setText("Latest training: Not available")
                    widgets["storage_label"].setText("Storage path: Not available")
                    widgets["storage_label"].setToolTip("")

            if latest_job is not None:
                widgets["last_job_label"].setText(
                    f"Last training job: {latest_job.status} ({latest_job.progress_percent:.0f}%)")
            else:
                widgets["last_job_label"].setText("Last training job: None yet")

            if widgets.get("recent_datasets_label") is not None:
                if model_key == MODEL_KEY_ANSWER_REGION_DETECTION:
                    datasets = list_region_detection_datasets(conn, owner, limit=5)
                else:
                    datasets = list_k2_training_datasets(conn, owner, limit=5)
                if datasets:
                    lines = [f"- {d['dataset_name']} - {d['row_count']} rows" for d in datasets]
                    widgets["recent_datasets_label"].setText("Recent datasets:\n" + "\n".join(lines))
                else:
                    widgets["recent_datasets_label"].setText("Recent datasets: None yet")

            if model_key == MODEL_KEY_K2_SHORT_ANSWER_SCORING:
                training_in_progress = getattr(self, "_k2_training_worker", None) is not None
                dataset_available = has_k2_training_dataset(conn, owner)
                widgets["start_training_button"].setEnabled(dataset_available and not training_in_progress)
                if training_in_progress:
                    widgets["start_training_button"].setText("Training in progress...")
                else:
                    widgets["start_training_button"].setText("Start Training")
                    if not dataset_available:
                        widgets["start_training_button"].setToolTip(
                            "Export a Kertas 2 training dataset first to enable this button.")

                evaluation_in_progress = getattr(self, "_k2_evaluation_worker", None) is not None
                model_available = active is not None
                evaluate_ready = model_available and dataset_available and not evaluation_in_progress
                widgets["evaluate_button"].setEnabled(evaluate_ready)
                if evaluation_in_progress:
                    widgets["evaluate_button"].setText("Evaluating...")
                else:
                    widgets["evaluate_button"].setText("Evaluate")
                    if not model_available:
                        widgets["evaluate_button"].setToolTip("Train a Kertas 2 model first to enable this button.")
                    elif not dataset_available:
                        widgets["evaluate_button"].setToolTip(
                            "Export a Kertas 2 training dataset first to enable this button.")
                    else:
                        widgets["evaluate_button"].setToolTip("")

                if widgets.get("last_evaluation_label") is not None:
                    evaluation_metrics = None
                    if active is not None and active.metrics_json:
                        try:
                            evaluation_metrics = json.loads(active.metrics_json).get("evaluation")
                        except json.JSONDecodeError:
                            evaluation_metrics = None
                    widgets["last_evaluation_label"].setText(
                        f"Last evaluation: {_format_evaluation_metrics_summary(evaluation_metrics)}")

            if model_key == MODEL_KEY_ANSWER_REGION_DETECTION and widgets.get("export_dataset_button") is not None:
                widgets["export_dataset_button"].setEnabled(has_exportable_subject_profiles_global(conn))

    # --- progress dialog ----------------------------------------------------

    def _show_progress_dialog(self, title: str) -> tuple:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setFixedSize(280, 220)
        dialog_layout = QVBoxLayout(dialog)
        widget = CircularProgressWidget()
        dialog_layout.addWidget(widget)
        dialog.show()
        QApplication.processEvents()
        return dialog, widget

    # --- dataset export -----------------------------------------------------

    def handle_export_k2_training_dataset(self) -> None:
        conn = get_connection()
        try:
            try:
                result = export_k2_training_dataset(conn, self._ai_owner_id)
            except ValueError as exc:
                show_error(self, "Export Training Dataset", str(exc))
                return
        finally:
            conn.close()
        self.refresh_ai_models_page()
        show_detail(
            self, "Export Training Dataset",
            f"Dataset '{result['dataset_name']}' exported successfully.\n"
            f"Rows: {result['row_count']}\nCSV: {result['csv_path']}\nJSONL: {result['jsonl_path']}")

    def handle_export_region_detection_dataset(self) -> None:
        conn = get_connection()
        try:
            try:
                result = export_region_detection_dataset_global(conn, self._ai_owner_id)
            except ValueError as exc:
                show_error(self, "Export Training Dataset", str(exc))
                return
        finally:
            conn.close()
        self.refresh_ai_models_page()
        summary = result["summary"]
        demo_note = ("\n\nNote: this is a small/demo dataset - not yet enough images for meaningful training."
                     if summary.get("demo_mode") else "")
        show_detail(
            self, "Export Training Dataset",
            f"Dataset '{result['dataset_name']}' exported successfully.\n"
            f"Images: {result['row_count']} (train: {summary['train_count']}, val: {summary['val_count']})\n"
            f"Regions exported: {summary['region_count']}\n"
            f"Skipped (invalid/zero-area): {summary['skipped_zero_area_count']}\n"
            f"Skipped (no matching image): {summary['skipped_no_image_count']}\n"
            f"Dataset folder: {result['dataset_folder_path']}{demo_note}")

    def handle_view_ai_model_logs(self, model_key: str) -> None:
        conn = get_connection()
        try:
            jobs = list_ai_training_jobs(conn, self._ai_owner_id, model_key, limit=10)
        finally:
            conn.close()
        if not jobs:
            show_detail(self, "Training Logs", "No training jobs yet for this model.")
            return
        latest_job = jobs[0]
        lines = []
        for job in jobs:
            kind_label = "Evaluation" if is_k2_evaluation_job(job) else "Training"
            lines.append(
                f"[{kind_label}] Job {job.job_id}: {job.status} - {job.progress_percent:.0f}% - "
                f"{job.current_step or '-'}\nLog: {job.log_path or '-'}")
        log_file_text = "Log file not available."
        if latest_job.log_path:
            log_path = Path(latest_job.log_path)
            if log_path.exists():
                try:
                    log_file_text = log_path.read_text(encoding="utf-8")
                except OSError as exc:
                    log_file_text = f"Could not read log file: {exc}"
            else:
                log_file_text = f"Log file does not exist yet: {log_path}"
        show_detail(
            self, "Training Logs",
            "\n\n".join(lines) + f"\n\n--- Latest job log ({latest_job.job_id}) ---\n{log_file_text}")

    # --- training -----------------------------------------------------------

    def handle_start_k2_training(self) -> None:
        if getattr(self, "_k2_training_worker", None) is not None:
            show_error(self, "Start Training Failed", "A training job is already running.")
            return
        conn = get_connection()
        try:
            datasets = list_k2_training_datasets(conn, self._ai_owner_id, limit=10)
        finally:
            conn.close()
        if not datasets:
            show_error(self, "Start Training Failed", "Export a Kertas 2 training dataset first.")
            return
        options = [(f"{d['dataset_name']} ({d['row_count']} rows, {d['created_at']})", d["dataset_id"])
                   for d in datasets]
        dataset_id = prompt_select(self, "Start Training", "Choose a Kertas 2 training dataset:", options)
        if dataset_id is CANCELLED:
            return
        widgets = self._ai_model_cards[MODEL_KEY_K2_SHORT_ANSWER_SCORING]
        widgets["start_training_button"].setEnabled(False)
        widgets["start_training_button"].setText("Training in progress...")
        progress_dialog, progress_widget = self._show_progress_dialog("Training Kertas 2 Cross-Encoder")
        self._k2_training_progress_dialog = progress_dialog
        self._k2_training_progress_widget = progress_widget
        worker = K2TrainingWorker(self._ai_owner_id, dataset_id, parent=self)
        worker.progress.connect(self.handle_k2_training_progress)
        worker.succeeded.connect(self.handle_k2_training_succeeded)
        worker.failed.connect(self.handle_k2_training_failed)
        worker.finished.connect(self.handle_k2_training_finished)
        self._k2_training_worker = worker
        worker.start()

    def handle_k2_training_progress(self, message: str, current: int, total: int) -> None:
        self._k2_training_progress_widget.set_progress(message, current, total)

    def handle_k2_training_succeeded(self, result: dict) -> None:
        demo_note = ("\n\nNote: this was a demo training run (too few usable dataset rows) - "
                     "metrics are NOT meaningful yet. Export more teacher-reviewed Kertas 2 "
                     "examples before relying on this model." if result.get("demo_mode") else "")
        show_success(
            self, "Training Completed",
            f"Model version '{result['version_label']}' trained and activated successfully.\n"
            f"Storage path: {result['model_path']}{demo_note}")

    def handle_k2_training_failed(self, message: str) -> None:
        show_error(self, "Training Failed", message)

    def handle_k2_training_finished(self) -> None:
        dialog = getattr(self, "_k2_training_progress_dialog", None)
        if dialog is not None:
            dialog.close()
        self._k2_training_worker = None
        self.refresh_ai_models_page()

    # --- evaluation ---------------------------------------------------------

    def handle_evaluate_k2_model(self) -> None:
        if getattr(self, "_k2_evaluation_worker", None) is not None:
            show_error(self, "Evaluate Failed", "An evaluation is already running.")
            return
        conn = get_connection()
        try:
            has_model = has_active_k2_model_version(conn, self._ai_owner_id)
            datasets = list_k2_training_datasets(conn, self._ai_owner_id, limit=10)
        finally:
            conn.close()
        if not has_model:
            show_error(self, "Evaluate Failed", "Train a Kertas 2 model first.")
            return
        if not datasets:
            show_error(self, "Evaluate Failed", "Export a Kertas 2 training dataset first.")
            return
        options = [(f"{d['dataset_name']} ({d['row_count']} rows, {d['created_at']})", d["dataset_id"])
                   for d in datasets]
        dataset_id = prompt_select(self, "Evaluate Model", "Choose a Kertas 2 dataset to evaluate against:", options)
        if dataset_id is CANCELLED:
            return
        widgets = self._ai_model_cards[MODEL_KEY_K2_SHORT_ANSWER_SCORING]
        widgets["evaluate_button"].setEnabled(False)
        widgets["evaluate_button"].setText("Evaluating...")
        progress_dialog, progress_widget = self._show_progress_dialog("Evaluating Kertas 2 Cross-Encoder")
        self._k2_evaluation_progress_dialog = progress_dialog
        self._k2_evaluation_progress_widget = progress_widget
        worker = K2EvaluationWorker(self._ai_owner_id, dataset_id, parent=self)
        worker.progress.connect(self.handle_k2_evaluation_progress)
        worker.succeeded.connect(self.handle_k2_evaluation_succeeded)
        worker.failed.connect(self.handle_k2_evaluation_failed)
        worker.finished.connect(self.handle_k2_evaluation_finished)
        self._k2_evaluation_worker = worker
        worker.start()

    def handle_k2_evaluation_progress(self, message: str, current: int, total: int) -> None:
        self._k2_evaluation_progress_widget.set_progress(message, current, total)

    def handle_k2_evaluation_succeeded(self, result: dict) -> None:
        metrics = result["metrics"]
        demo_note = ("\n\nNote: this was a demo evaluation run (too few usable dataset rows) - metrics are NOT "
                     "meaningful yet. Export more teacher-reviewed Kertas 2 examples before relying on this "
                     "model." if result.get("demo_mode") else "")
        show_success(
            self, "Evaluation Completed",
            f"Model version '{result['model_version_label']}' evaluated successfully.\n"
            f"Mean absolute error: {metrics['mean_absolute_error']}\n"
            f"Category accuracy: {metrics['category_accuracy']:.0%}\n"
            f"Rows evaluated: {metrics['usable_row_count']}{demo_note}")

    def handle_k2_evaluation_failed(self, message: str) -> None:
        show_error(self, "Evaluation Failed", message)

    def handle_k2_evaluation_finished(self) -> None:
        dialog = getattr(self, "_k2_evaluation_progress_dialog", None)
        if dialog is not None:
            dialog.close()
        self._k2_evaluation_worker = None
        self.refresh_ai_models_page()

    # --- Core AI 1 datasets / training / activation (Subsystem 5) -----------
    #
    # Core AI 1 (Kertas 2 scoring + feedback category) datasets are EXPORTED
    # from finalised teacher-reviewed records through the Claude-owned
    # finalized-record adapter - there is no folder to import. Everything else
    # mirrors Core AI 2: freeze is permanent, training needs a training-ready
    # dataset, activation needs a passing evaluation, and long operations run in
    # a background worker.

    CORE_AI1_DATASET_COLUMNS = ["Version", "Export valid", "Frozen", "Training ready", "Included",
                                "Excluded", "Parts", "Groups", "Leakage-safe", "Blockers"]

    def _build_core_ai1_section(self) -> QWidget:
        section = CollapsibleSection(
            "Core AI 1 datasets, training & activation (Kertas 2 scoring)", expanded=False)

        self.core_ai1_status = QLabel(
            "Datasets are exported from FINALISED teacher-reviewed Kertas 2 answers only. Freezing is "
            "permanent. Training needs a training-ready dataset; activation needs a passing evaluation. "
            "Export, training and evaluation run in the background.")
        self.core_ai1_status.setObjectName("StatusLabel")
        self.core_ai1_status.setWordWrap(True)
        section.add_widget(self.core_ai1_status)

        self.core_ai1_dataset_table = QTableWidget(0, len(self.CORE_AI1_DATASET_COLUMNS))
        self.core_ai1_dataset_table.setHorizontalHeaderLabels(self.CORE_AI1_DATASET_COLUMNS)
        self.core_ai1_dataset_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.core_ai1_dataset_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.core_ai1_dataset_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.core_ai1_dataset_table.verticalHeader().setVisible(False)
        self.core_ai1_dataset_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.core_ai1_dataset_table.setMaximumHeight(180)
        self.core_ai1_dataset_table.itemSelectionChanged.connect(self._on_core_ai1_dataset_selected)
        section.add_widget(self.core_ai1_dataset_table)
        self._core_ai1_dataset_versions = []

        dataset_buttons = QHBoxLayout()
        for text, slot, attr in (
            ("Export from finalised records", self.handle_export_core_ai1_dataset,
             "core_ai1_export_button"),
            ("Refresh", self.handle_refresh_core_ai1, "core_ai1_refresh_button"),
            ("Inspect", self.handle_inspect_core_ai1_dataset, "core_ai1_inspect_button"),
            ("Re-check integrity", self.handle_audit_core_ai1_dataset, "core_ai1_audit_button"),
            ("Compare two", self.handle_compare_core_ai1_datasets, "core_ai1_compare_button"),
            ("Freeze (permanent)", self.handle_freeze_core_ai1_dataset, "core_ai1_freeze_button"),
        ):
            button = QPushButton(text)
            button.setObjectName("RowActionButton")
            button.clicked.connect(slot)
            setattr(self, attr, button)
            dataset_buttons.addWidget(button)
        dataset_buttons.addStretch()
        dataset_wrap = QWidget()
        dataset_wrap.setLayout(dataset_buttons)
        section.add_widget(dataset_wrap)

        self.core_ai1_models_table = QTableWidget(0, len(self.CORE_AI2_MODEL_COLUMNS))
        self.core_ai1_models_table.setHorizontalHeaderLabels(self.CORE_AI2_MODEL_COLUMNS)
        self.core_ai1_models_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.core_ai1_models_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.core_ai1_models_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.core_ai1_models_table.verticalHeader().setVisible(False)
        self.core_ai1_models_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.core_ai1_models_table.setMaximumHeight(160)
        self.core_ai1_models_table.itemSelectionChanged.connect(self._on_core_ai1_model_selected)
        section.add_widget(self.core_ai1_models_table)
        self._core_ai1_model_versions = []

        self.core_ai1_jobs_table = QTableWidget(0, len(self.CORE_AI2_JOB_COLUMNS))
        self.core_ai1_jobs_table.setHorizontalHeaderLabels(self.CORE_AI2_JOB_COLUMNS)
        self.core_ai1_jobs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.core_ai1_jobs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.core_ai1_jobs_table.verticalHeader().setVisible(False)
        self.core_ai1_jobs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.core_ai1_jobs_table.setMaximumHeight(140)
        self.core_ai1_jobs_table.itemSelectionChanged.connect(self._on_core_ai1_model_selected)
        section.add_widget(self.core_ai1_jobs_table)
        self._core_ai1_job_ids = []

        model_buttons = QHBoxLayout()
        for text, slot, attr in (
            ("Start training", self.handle_start_core_ai1_training, "core_ai1_start_training_button"),
            ("Cancel job", self.handle_cancel_core_ai1_job, "core_ai1_cancel_job_button"),
            ("Evaluate", self.handle_evaluate_core_ai1_model, "core_ai1_evaluate_button"),
            ("Compare models", self.handle_compare_core_ai1_models, "core_ai1_compare_models_button"),
            ("Activate", self.handle_activate_core_ai1_model, "core_ai1_activate_button"),
            ("Roll back", self.handle_rollback_core_ai1_model, "core_ai1_rollback_button"),
            ("Runtime check", self.handle_core_ai1_runtime_check, "core_ai1_runtime_button"),
            ("AI readiness", self.handle_ai_readiness_check, "ai_readiness_button"),
        ):
            button = QPushButton(text)
            button.setObjectName("RowActionButton")
            button.clicked.connect(slot)
            setattr(self, attr, button)
            model_buttons.addWidget(button)
        model_buttons.addStretch()
        model_wrap = QWidget()
        model_wrap.setLayout(model_buttons)
        section.add_widget(model_wrap)

        self.core_ai1_section = section
        return section

    # --- selection helpers ---------------------------------------------------

    def _selected_core_ai1_dataset(self):
        row = self.core_ai1_dataset_table.currentRow()
        versions = getattr(self, "_core_ai1_dataset_versions", [])
        return versions[row] if 0 <= row < len(versions) else None

    def _selected_core_ai1_model(self):
        row = self.core_ai1_models_table.currentRow()
        versions = getattr(self, "_core_ai1_model_versions", [])
        return versions[row] if 0 <= row < len(versions) else None

    def _selected_core_ai1_job(self):
        row = self.core_ai1_jobs_table.currentRow()
        ids = getattr(self, "_core_ai1_job_ids", [])
        return ids[row] if 0 <= row < len(ids) else None

    # --- refresh -------------------------------------------------------------

    def _refresh_core_ai1(self, conn) -> None:
        if not hasattr(self, "core_ai1_dataset_table"):
            return
        user = getattr(self, "_user", None)
        try:
            datasets = core1_admin.list_datasets(conn, user)
        except ai_access.AIPermissionError:
            return
        except BackendError as exc:
            self.core_ai1_status.setText(f"Backend unavailable: {exc.safe_message}")
            self.core_ai1_dataset_table.setRowCount(0)
            self._core_ai1_dataset_versions = []
            return
        self._core_ai1_dataset_versions = [d.version for d in datasets]
        self.core_ai1_dataset_table.setRowCount(len(datasets))
        for r, d in enumerate(datasets):
            stats = d.statistics
            parts = stats.get("part_distribution", {})
            cells = [
                d.version, "Yes" if d.export_valid else "No", "Yes" if d.frozen else "No",
                "Yes" if d.training_ready else "No",
                stats.get("included_count", "-"), stats.get("excluded_count", "-"),
                ", ".join(f"{k}:{v}" for k, v in sorted(parts.items())) or "-",
                stats.get("attempt_group_count", "-"),
                "Yes" if stats.get("leakage_safe_split") else "No",
                "; ".join(d.blockers) if d.blockers else "-",
            ]
            for c, value in enumerate(cells):
                self.core_ai1_dataset_table.setItem(r, c, QTableWidgetItem(str(value)))

        try:
            models = jobs_admin.list_models(conn, user, family=MODEL_FAMILY_CORE_AI1)
            training_jobs = jobs_admin.list_training_jobs(conn, user, family=MODEL_FAMILY_CORE_AI1)
        except (ai_access.AIPermissionError, BackendError):
            models, training_jobs = [], []
        self._core_ai1_model_versions = [m.version for m in models]
        self.core_ai1_models_table.setRowCount(len(models))
        for r, m in enumerate(models):
            cells = [m.version, m.evaluation_status, m.activation_status, m.source_dataset_version,
                     m.runtime_compatibility, m.training_job_id]
            for c, value in enumerate(cells):
                self.core_ai1_models_table.setItem(r, c, QTableWidgetItem(str(value)))

        self._core_ai1_job_ids = [j.job_id for j in training_jobs]
        self._core_ai1_job_status = {j.job_id: j.status for j in training_jobs}
        self.core_ai1_jobs_table.setRowCount(len(training_jobs))
        for r, j in enumerate(training_jobs):
            progress = j.progress_message + (f" ({j.progress_value:.0f}%)"
                                             if j.progress_value is not None else "")
            cells = [j.job_id, j.status, progress, j.dataset_version, j.result_model_version or "-"]
            for c, value in enumerate(cells):
                self.core_ai1_jobs_table.setItem(r, c, QTableWidgetItem(str(value)))
        self._on_core_ai1_dataset_selected()
        self._on_core_ai1_model_selected()
        # The registry state just changed - any earlier refusal no longer applies.
        if not self._ai_job_worker_running():
            self._clear_ai_status(MODEL_FAMILY_CORE_AI1)

    def _on_core_ai1_dataset_selected(self) -> None:
        if not hasattr(self, "core_ai1_freeze_button"):
            return
        version = self._selected_core_ai1_dataset()
        descriptor = None
        if version is not None:
            conn = get_connection()
            try:
                descriptor = core1_admin.inspect_dataset(conn, getattr(self, "_user", None), version)
            except (ai_access.AIPermissionError, BackendError):
                descriptor = None
            finally:
                conn.close()
        # Freeze only an export-valid, not-yet-frozen dataset - the button state
        # never contradicts the backend rule.
        self.core_ai1_freeze_button.setEnabled(
            bool(descriptor and descriptor.export_valid and not descriptor.frozen))
        if descriptor is not None and not self._ai_job_worker_running():
            self._clear_ai_status(MODEL_FAMILY_CORE_AI1)
        for attr in ("core_ai1_inspect_button", "core_ai1_audit_button"):
            getattr(self, attr).setEnabled(descriptor is not None)

    def _on_core_ai1_model_selected(self) -> None:
        if not hasattr(self, "core_ai1_activate_button"):
            return
        version = self._selected_core_ai1_model()
        descriptor = None
        if version is not None:
            conn = get_connection()
            try:
                descriptor = jobs_admin.inspect_model(conn, getattr(self, "_user", None), version,
                                                      family=MODEL_FAMILY_CORE_AI1)
            except (ai_access.AIPermissionError, BackendError):
                descriptor = None
            finally:
                conn.close()
        self.core_ai1_activate_button.setEnabled(
            bool(descriptor and descriptor.evaluation_status == "passed"
                 and descriptor.activation_status != "active"))
        self.core_ai1_rollback_button.setEnabled(
            bool(descriptor and descriptor.evaluation_status == "passed"))
        self.core_ai1_evaluate_button.setEnabled(descriptor is not None
                                                 and not self._ai_job_worker_running())
        self._refresh_cancel_button("core_ai1_cancel_job_button", self._selected_core_ai1_job(),
                                    getattr(self, "_core_ai1_job_status", {}))

    def handle_refresh_core_ai1(self) -> None:
        conn = get_connection()
        try:
            self._refresh_core_ai1(conn)
        finally:
            conn.close()

    # --- dataset actions -----------------------------------------------------

    def handle_export_core_ai1_dataset(self) -> None:
        version = prompt_input(
            self, "Export Core AI 1 Dataset",
            "New dataset version label (an existing version is never overwritten):")
        if not version or not str(version).strip():
            return
        version = str(version).strip()
        user = self._user

        def _op():
            c = get_connection()
            try:
                # Reads every finalised reviewed record - always off the UI thread.
                return core1_admin.export_dataset(c, user, version)
            finally:
                c.close()

        def _on_ok(descriptor):
            stats = descriptor.statistics
            show_detail(
                self, f"Core AI 1 dataset {descriptor.version}",
                f"Included: {stats.get('included_count')} | Excluded: {stats.get('excluded_count')}\n"
                f"Excluded reasons: {self._format_counts(stats.get('excluded_reasons'))}\n"
                f"Training ready: {descriptor.training_ready}\n"
                f"Blockers: {'; '.join(descriptor.blockers) or 'None'}")

        self._run_ai_backend_op(_op, _on_ok, "Exporting from finalised records (background)...",
                                family=MODEL_FAMILY_CORE_AI1)

    @staticmethod
    def _format_counts(counts) -> str:
        if not counts:
            return "None"
        return ", ".join(f"{k}: {v}" for k, v in sorted(counts.items(), key=lambda kv: str(kv[0])))

    def handle_inspect_core_ai1_dataset(self) -> None:
        version = self._selected_core_ai1_dataset()
        if version is None:
            show_error(self, "Inspect Dataset", "Select a dataset first.")
            return
        conn = get_connection()
        try:
            d = core1_admin.inspect_dataset(conn, self._user, version)
        except BackendError as exc:
            show_error(self, "Inspect Dataset", exc.safe_message)
            return
        finally:
            conn.close()
        stats = d.statistics
        show_detail(
            self, f"Core AI 1 dataset {d.version}",
            f"Export valid: {d.export_valid}\nFrozen: {d.frozen}\nTraining ready: {d.training_ready}\n"
            f"Schema: {d.schema_version or '-'} | Category mapping: {d.mapping_version or '-'}\n"
            f"Split mode: {d.split_mode or '-'} | Leakage-safe split: {stats.get('leakage_safe_split')} | "
            f"Ratios: {stats.get('split_ratios')}\n"
            f"Included samples: {stats.get('included_count')} | Excluded: {stats.get('excluded_count')}\n"
            f"Excluded reasons: {self._format_counts(stats.get('excluded_reasons'))}\n"
            f"Parts (1/2/3): {self._format_counts(stats.get('part_distribution'))}\n"
            f"Scores: {self._format_counts(stats.get('score_distribution'))}\n"
            f"Feedback categories: {self._format_counts(stats.get('category_distribution'))}\n"
            f"Standard vs separate-paper: {self._format_counts(stats.get('mode_distribution'))}\n"
            f"Attempt groups: {stats.get('attempt_group_count')}\n"
            f"Blockers: {'; '.join(d.blockers) or 'None'}\n"
            f"Warnings: {'; '.join(d.warnings) or 'None'}\n"
            f"Recommendations: {'; '.join(stats.get('recommendations', [])) or 'None'}")

    def handle_audit_core_ai1_dataset(self) -> None:
        version = self._selected_core_ai1_dataset()
        if version is None:
            show_error(self, "Re-check Integrity", "Select a dataset first.")
            return
        conn = get_connection()
        try:
            report = core1_admin.audit_dataset(conn, self._user, version)
        except BackendError as exc:
            show_error(self, "Re-check Integrity", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(
            self, f"Integrity re-check - {version}",
            f"Result: {'OK' if report.ok else 'Problems found'}\nChecked at: {report.checked_at}\n"
            f"Findings: {'; '.join(report.findings) or 'None'}\n"
            f"Recommendations: {'; '.join(report.recommendations) or 'None'}")

    def handle_compare_core_ai1_datasets(self) -> None:
        versions = getattr(self, "_core_ai1_dataset_versions", [])
        if len(versions) < 2:
            show_error(self, "Compare Datasets", "At least two datasets are needed to compare.")
            return
        left = self._selected_core_ai1_dataset() or versions[0]
        right = prompt_select(self, "Compare Datasets", f"Compare {left} against:",
                              [(v, v) for v in versions if v != left])
        if right is CANCELLED:
            return
        conn = get_connection()
        try:
            cmp = core1_admin.compare_datasets(conn, self._user, left, right)
        except BackendError as exc:
            show_error(self, "Compare Datasets", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(self, f"{left} vs {right}",
                    "Differences:\n" + ("\n".join(cmp.differences) if cmp.differences else "None"))

    def handle_freeze_core_ai1_dataset(self) -> None:
        version = self._selected_core_ai1_dataset()
        if version is None:
            show_error(self, "Freeze Dataset", "Select a dataset first.")
            return
        if not prompt_confirm(
            self, "Freeze Dataset (permanent)",
            f"Freeze '{version}'? Freezing is PERMANENT - there is no unfreeze. Later finalised "
            "records will not be added to a frozen dataset; export a new version instead.",
                confirm_text="Freeze permanently"):
            return
        conn = get_connection()
        try:
            core1_admin.freeze_dataset(conn, self._user, version)
        except BackendError as exc:
            show_error(self, "Freeze Dataset", exc.safe_message)
            return
        finally:
            conn.close()
        self.handle_refresh_core_ai1()
        show_success(self, "Freeze Dataset", f"Dataset '{version}' is now frozen (permanent).")

    # --- training / evaluation / activation ----------------------------------

    def _default_base_model_dir(self) -> str:
        """A sensible starting folder for the base-transformer picker: the
        emergency-training base_models folder when it exists, else the app root."""
        from pathlib import Path
        candidate = (Path.cwd().parent / "FYP-Data" / "core_ai1_emergency_training"
                     / "base_models" / "all-MiniLM-L6-v2")
        return str(candidate) if candidate.exists() else str(Path.cwd())

    def _default_base_checkpoint_dir(self) -> str:
        from pathlib import Path
        candidate = (Path.cwd().parent / "FYP-Data" / "core_ai2_emergency_training")
        return str(candidate) if candidate.exists() else str(Path.cwd())

    def _list_yolo_conversions(self, dataset_version: str) -> list:
        """The YOLO conversion versions already produced for a Core AI 2
        dataset (each is a subfolder of <dataset>/formats/yolo)."""
        from app.services.ai_backend_integration import core_ai2_dataset_root
        from app.services.core_ai2_dataset_registry_service import get_dataset_entry
        root = core_ai2_dataset_root()
        try:
            folder_name = get_dataset_entry(root, dataset_version)["folder_name"]
        except Exception:
            return []
        yolo_dir = root / folder_name / "formats" / "yolo"
        if not yolo_dir.is_dir():
            return []
        return sorted(p.name for p in yolo_dir.iterdir() if p.is_dir())

    def handle_start_core_ai1_training(self) -> None:
        conn = get_connection()
        try:
            datasets = core1_admin.list_datasets(conn, self._user)
        except BackendError as exc:
            show_error(self, "Start Training", exc.safe_message)
            return
        finally:
            conn.close()
        ready = [d.version for d in datasets if d.frozen and d.training_ready]
        if not ready:
            show_error(self, "Start Training",
                       "No Core AI 1 dataset is ready for training. A dataset must be frozen AND "
                       "training-ready with a leakage-safe split. Export more finalised records "
                       "and resolve the listed readiness blockers first.")
            return
        dataset_version = prompt_select(self, "Start Training", "Training-ready dataset:",
                                        [(v, v) for v in ready])
        if dataset_version is CANCELLED:
            return
        target = prompt_input(self, "Start Training", "New model version label:")
        if not target or not str(target).strip():
            return
        base_model_path = QFileDialog.getExistingDirectory(
            self, "Choose the local base Transformer folder (e.g. all-MiniLM-L6-v2)",
            self._default_base_model_dir())
        if not base_model_path:
            return
        config = {
            "target_version": str(target).strip(),
            "local_base_model_path": base_model_path,
        }
        conn = get_connection()
        try:
            blockers = jobs_admin.validate_training_request(conn, self._user, dataset_version, config,
                                                            family=MODEL_FAMILY_CORE_AI1)
        finally:
            conn.close()
        if blockers:
            show_error(self, "Start Training", "Cannot start:\n" + "\n".join(blockers))
            return
        user = self._user

        def _op():
            c = get_connection()
            try:
                job = jobs_admin.create_training_job(c, user, dataset_version, config,
                                                     family=MODEL_FAMILY_CORE_AI1)
                return jobs_admin.run_training_job(c, user, job.job_id, config,
                                                   family=MODEL_FAMILY_CORE_AI1)
            finally:
                c.close()

        def _on_ok(job):
            if job.status == JOB_COMPLETED:
                show_success(self, "Training Completed",
                             f"Model '{job.result_model_version}' trained. Evaluate it before activation.")
            else:
                show_detail(self, "Training Finished", f"Job {job.job_id} ended as: {job.status}")

        self._run_ai_backend_op(_op, _on_ok, "Training Core AI 1 (background)...",
                                family=MODEL_FAMILY_CORE_AI1)

    def handle_cancel_core_ai1_job(self) -> None:
        job_id = self._selected_core_ai1_job()
        if job_id is None:
            show_error(self, "Cancel Job", "Select a job first.")
            return
        if not prompt_confirm(self, "Cancel Training Job", f"Request cancellation of {job_id}?",
                              confirm_text="Cancel job"):
            return
        self._cancel_job_to_terminal(job_id, MODEL_FAMILY_CORE_AI1)
        self.handle_refresh_core_ai1()

    def handle_evaluate_core_ai1_model(self) -> None:
        version = self._selected_core_ai1_model()
        if version is None:
            show_error(self, "Evaluate", "Select a model first.")
            return
        conn = get_connection()
        try:
            datasets = core1_admin.list_datasets(conn, self._user)
        finally:
            conn.close()
        if not datasets:
            show_error(self, "Evaluate", "Export a dataset to evaluate against first.")
            return
        dataset_version = prompt_select(self, "Evaluate Model", "Evaluate against dataset:",
                                        [(d.version, d.version) for d in datasets])
        if dataset_version is CANCELLED:
            return
        user = self._user

        def _op():
            c = get_connection()
            try:
                return jobs_admin.evaluate_model(c, user, version, dataset_version,
                                                 family=MODEL_FAMILY_CORE_AI1)
            finally:
                c.close()

        def _on_ok(result):
            show_detail(self, "Evaluation Complete",
                        f"Model: {result.model_version}\nPassed: {result.passed}\n"
                        f"Metrics: {result.metrics}\nDecision criteria: {result.decision_criteria}")

        self._run_ai_backend_op(_op, _on_ok, "Evaluating Core AI 1 (background)...",
                                family=MODEL_FAMILY_CORE_AI1)

    def handle_compare_core_ai1_models(self) -> None:
        versions = getattr(self, "_core_ai1_model_versions", [])
        if len(versions) < 2:
            show_error(self, "Compare Models", "At least two models are needed.")
            return
        left = self._selected_core_ai1_model() or versions[0]
        right = prompt_select(self, "Compare Models", f"Compare {left} against:",
                              [(v, v) for v in versions if v != left])
        if right is CANCELLED:
            return
        conn = get_connection()
        try:
            cmp = jobs_admin.compare_models(conn, self._user, left, right,
                                            family=MODEL_FAMILY_CORE_AI1)
        except BackendError as exc:
            show_error(self, "Compare Models", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(self, f"{left} vs {right}",
                    "Differences:\n" + ("\n".join(cmp.differences) if cmp.differences else "None"))

    def handle_activate_core_ai1_model(self) -> None:
        version = self._selected_core_ai1_model()
        if version is None:
            show_error(self, "Activate Model", "Select a model first.")
            return
        reason = prompt_input(self, "Activate Model",
                              "Reason for activation (recorded in activation history):")
        if not reason or not str(reason).strip():
            return
        if not prompt_confirm(self, "Activate Model",
                              f"Activate '{version}' as the live Core AI 1 model? Teacher drafts "
                              "produced by an older model stay marked as stale until regenerated.",
                              confirm_text="Activate"):
            return
        conn = get_connection()
        try:
            jobs_admin.activate_model(conn, self._user, version, reason=str(reason).strip(),
                                      family=MODEL_FAMILY_CORE_AI1)
        except BackendError as exc:
            show_error(self, "Activate Model", exc.safe_message)
            return
        finally:
            conn.close()
        self.handle_refresh_core_ai1()
        self._clear_ai_status(MODEL_FAMILY_CORE_AI1,
                              f"'{version}' is now the active Core AI 1 model.")
        show_success(self, "Activate Model", f"'{version}' is now the active Core AI 1 model.")

    def handle_rollback_core_ai1_model(self) -> None:
        version = self._selected_core_ai1_model()
        if version is None:
            show_error(self, "Roll Back", "Select the model version to roll back to.")
            return
        reason = prompt_input(self, "Roll Back Model", "Reason for rollback (recorded in history):")
        if not reason or not str(reason).strip():
            return
        if not prompt_confirm(self, "Roll Back Model",
                              f"Roll back to '{version}'? It must be an evaluated (passing) version.",
                              confirm_text="Roll back"):
            return
        conn = get_connection()
        try:
            jobs_admin.rollback_model(conn, self._user, version, reason=str(reason).strip(),
                                      family=MODEL_FAMILY_CORE_AI1)
        except BackendError as exc:
            show_error(self, "Roll Back", exc.safe_message)
            return
        finally:
            conn.close()
        self.handle_refresh_core_ai1()
        self._clear_ai_status(MODEL_FAMILY_CORE_AI1,
                              f"Rolled back - '{version}' is now the active Core AI 1 model.")
        show_success(self, "Roll Back", f"Rolled back - '{version}' is now active.")

    def handle_ai_readiness_check(self) -> None:
        """Stage 12G-9: what AI assistance is available right now, and the
        explicit confirmation that the manual workflow does not depend on it."""
        from app.services import ai_resilience_service as resilience
        conn = get_connection()
        try:
            readiness = resilience.describe_ai_readiness(conn)
        finally:
            conn.close()
        lines = []
        for key, label in (("draft_scoring", "Core AI 1 draft scoring"),
                           ("feedback", "Feedback wording"),
                           ("region_proposals", "Core AI 2 region proposals"),
                           ("manual_operation", "Manual operation")):
            entry = readiness[key]
            lines.append(f"{label}: {'Available' if entry['available'] else 'Unavailable'} - "
                         f"{entry['detail']}")
        show_detail(self, "AI Readiness", "\n".join(lines))

    def handle_core_ai1_runtime_check(self) -> None:
        version = self._selected_core_ai1_model()
        conn = get_connection()
        try:
            runtime = jobs_admin.inspect_runtime(conn, self._user, family=MODEL_FAMILY_CORE_AI1,
                                                 model_version=version)
        except BackendError as exc:
            show_error(self, "Runtime Check", exc.safe_message)
            return
        finally:
            conn.close()
        show_detail(self, "Runtime Compatibility (Core AI 1)",
                    f"Memory status: {runtime.memory_status}\n"
                    f"Manual marking available without AI: {runtime.graceful_no_ai_mode}\n"
                    f"Warnings: {'; '.join(runtime.warnings) or 'None'}\n"
                    f"Blockers: {'; '.join(runtime.blockers) or 'None'}")
