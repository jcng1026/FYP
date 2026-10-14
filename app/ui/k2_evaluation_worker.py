"""Stage 12D: background QThread worker for Kertas 2 Cross-Encoder evaluation.

Mirrors app/ui/k2_training_worker.py's established pattern (Stage 12C) -
evaluation runs a prediction per dataset row, which can take real time
once torch/transformers are installed and a real model is loaded, so it
must never run on the UI thread. The worker opens its own sqlite3
connection and calls the existing, unmodified
run_k2_cross_encoder_evaluation, forwarding its progress_callback through
a Qt signal (auto-queued by Qt across threads) so the UI's progress widget
updates without ever blocking.
"""

from PySide6.QtCore import QThread, Signal

from app.database.db import get_connection
from app.services.k2_cross_encoder_evaluation_service import run_k2_cross_encoder_evaluation


class K2EvaluationWorker(QThread):
    """Runs run_k2_cross_encoder_evaluation for one teacher's chosen
    Kertas 2 dataset against their active model version, on a background
    thread.

    Signals:
        progress(message, current, total) - mirrors the service layer's
            own progress_callback(message, current, total) contract.
        succeeded(result) - emitted once with the evaluation result dict
            (job_id, model_id, model_version_label, dataset_id, metrics,
            demo_mode) when evaluation completes successfully.
        failed(message) - emitted instead of succeeded if evaluation could
            not complete (missing dependency, no usable rows, no active
            model, a real prediction error) - the underlying job is
            already marked 'failed' with the same message before this
            fires.
    """

    progress = Signal(str, int, int)
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, teacher_id: int, dataset_id: int, parent=None) -> None:
        super().__init__(parent)
        self._teacher_id = teacher_id
        self._dataset_id = dataset_id

    def run(self) -> None:
        conn = get_connection()
        try:
            def _on_progress(message: str, current: int, total: int) -> None:
                self.progress.emit(message, current, total)

            result = run_k2_cross_encoder_evaluation(
                conn, self._teacher_id, self._dataset_id, progress_callback=_on_progress,
            )
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()
