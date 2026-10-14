"""Stage 12C: background QThread worker for Kertas 2 Cross-Encoder training.

Mirrors app/ui/subject_profile_worker.py's established pattern (Stage 11W) -
training can take real time even for a small demo dataset (and much longer
once torch/transformers are installed and real models are trained), so it
must never run on the UI thread. The worker opens its own sqlite3
connection and calls the existing, unmodified
run_k2_cross_encoder_training, forwarding its progress_callback through a
Qt signal (auto-queued by Qt across threads) so the UI's progress widget
updates without ever blocking.
"""

from typing import Optional

from PySide6.QtCore import QThread, Signal

from app.database.db import get_connection
from app.services.k2_cross_encoder_training_service import run_k2_cross_encoder_training


class K2TrainingWorker(QThread):
    """Runs run_k2_cross_encoder_training for one teacher's chosen Kertas 2
    dataset on a background thread.

    Signals:
        progress(message, current, total) - mirrors the service layer's
            own progress_callback(message, current, total) contract.
        succeeded(result) - emitted once with the training result dict
            (job_id, model_id, version_label, metrics, model_path,
            demo_mode) when training completes successfully.
        failed(message) - emitted instead of succeeded if training could
            not complete (missing dependency, no usable rows, a real
            training error) - the underlying training job is already
            marked 'failed' with the same message before this fires.
    """

    progress = Signal(str, int, int)
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, teacher_id: int, dataset_id: int, base_model_name: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self._teacher_id = teacher_id
        self._dataset_id = dataset_id
        self._base_model_name = base_model_name

    def run(self) -> None:
        conn = get_connection()
        try:
            def _on_progress(message: str, current: int, total: int) -> None:
                self.progress.emit(message, current, total)

            result = run_k2_cross_encoder_training(
                conn, self._teacher_id, self._dataset_id, base_model_name=self._base_model_name,
                progress_callback=_on_progress,
            )
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()
