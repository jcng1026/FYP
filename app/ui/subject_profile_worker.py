"""Stage 11W: background QThread worker for student answer PDF processing.

Fixes the "upload jumps to 100% and the app becomes Not Responding" bug:
Stage 11V ran mark_student_answer_pdfs_for_profile synchronously on the UI
thread (relying on QApplication.processEvents() calls inside the progress
callback to keep the window painting) - fine for the short QP/AS processing
step, but student PDF batches with real OCR can take long enough that the
window stops responding to the OS between processEvents() calls, and
Windows marks it "Not Responding".

This is the first QThread/background-worker pattern in the codebase (no
prior precedent to follow) - kept intentionally small: the worker opens its
own sqlite3 connection (safe - app.database.db.get_connection() returns a
fresh connection per call, never a shared one across threads) and calls the
existing, unmodified mark_student_answer_pdfs_for_profile, forwarding its
progress_callback through a Qt signal (thread-safe/auto-queued by Qt) so the
UI thread's CircularProgressWidget updates without ever blocking.
"""

import json
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QProcess, QThread, Signal

from app.database.db import get_connection
from app.services.subject_profile_service import StudentPdfResult, mark_student_answer_pdfs_for_profile
from app.utils.ocr_engine import OCREngine


class StudentPdfProcessingWorker(QThread):
    """Runs mark_student_answer_pdfs_for_profile for one Subject Profile's
    uploaded student answer PDFs on a background thread.

    Signals:
        progress(message, current, total) - emitted for every page/stage
            tick, exactly mirroring the service layer's own progress_
            callback(message, current, total) contract.
        succeeded(results) - emitted once with the full List[StudentPdfResult]
            when the whole batch finishes without a top-level error (a PDF
            reporting succeeded=False inside the list is still a normal,
            already-handled outcome - see StudentPdfResult).
        failed(message) - emitted instead of succeeded if the batch could
            not even start (e.g. the profile isn't ready yet).
    """

    progress = Signal(str, int, int)
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(
        self, teacher_id: int, profile_id: int, student_pdf_paths: List[str],
        engine: Optional[OCREngine] = None, parent=None,
    ) -> None:
        super().__init__(parent)
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._student_pdf_paths = student_pdf_paths
        # Marking Fix: constructed by the caller on the main/GUI thread
        # BEFORE this worker starts - see teacher_dashboard.py's
        # handle_upload_student_answer_pdfs docstring for why (PaddleOCR's
        # first-time construction hangs indefinitely when done inside this
        # background thread instead).
        self._engine = engine

    def run(self) -> None:
        conn = get_connection()
        try:
            def _on_progress(message: str, current: int, total: int) -> None:
                self.progress.emit(message, current, total)

            results: List[StudentPdfResult] = mark_student_answer_pdfs_for_profile(
                conn, self._teacher_id, self._profile_id, self._student_pdf_paths,
                progress_callback=_on_progress, engine=self._engine,
            )
            self.succeeded.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            conn.close()


_WORKER_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "workers" / "subject_profile_marking_worker_process.py"


def _worker_launch(worker_name: str, script_path: Path, worker_args: list) -> tuple:
    """(program, args) for launching a hang-safe worker process.

    In development ``sys.executable`` is python.exe, so we run the worker .py
    directly. In a frozen build (PyInstaller) there is no python.exe and no
    loose .py to run, so we relaunch the SAME executable with a --run-worker
    sentinel that main.py dispatches to the worker's entry point before any
    GUI starts."""
    if getattr(sys, "frozen", False):
        return sys.executable, ["--run-worker", worker_name, *worker_args]
    return sys.executable, [str(script_path), *worker_args]


class StudentPdfProcessingSubprocessWorker(QObject):
    """Marking Fix Follow-up: runs mark_student_answer_pdfs_for_profile in a
    genuinely SEPARATE OS process (via QProcess) instead of a QThread inside
    this same process - see subject_profile_marking_worker_process.py's
    docstring for why: real PaddleOCR construction/inference inside
    StudentPdfProcessingWorker's QThread was found to crash the whole app
    with no Python traceback, reproduced repeatedly (about 1 success in 5
    attempts), while the identical work in a plain separate process
    completed reliably every time. Exposes the exact same signal/method
    surface as StudentPdfProcessingWorker (progress/succeeded/failed/
    finished, .start()/.isRunning()/.wait()) so it's a drop-in replacement
    in teacher_dashboard.py - no caller-side changes needed beyond which
    class gets instantiated.

    Signals: identical contract to StudentPdfProcessingWorker - see there.
    """

    progress = Signal(str, int, int)
    succeeded = Signal(list)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, teacher_id: int, profile_id: int, student_pdf_paths: List[str], parent=None) -> None:
        super().__init__(parent)
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._student_pdf_paths = student_pdf_paths
        self._results: Optional[List[StudentPdfResult]] = None
        self._error_message: Optional[str] = None
        self._stdout_buffer = ""

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._handle_stdout_ready)
        self._process.readyReadStandardError.connect(self._handle_stderr_ready)
        self._process.finished.connect(self._handle_process_finished)

    def start(self) -> None:
        program, args = _worker_launch(
            "subject_profile_marking", _WORKER_SCRIPT_PATH,
            [str(self._teacher_id), str(self._profile_id), json.dumps(self._student_pdf_paths)])
        self._process.start(program, args)

    def isRunning(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def wait(self, timeout_ms: int = 30000) -> bool:
        return self._process.waitForFinished(timeout_ms)

    def _handle_stdout_ready(self) -> None:
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._stdout_buffer += chunk
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            self._handle_line(line.rstrip("\r"))

    def _handle_stderr_ready(self) -> None:
        # PaddleOCR/paddlex log a lot of noise (model-loading messages,
        # warnings) to stderr - not part of the line protocol, just drained
        # here so the child process is never blocked on a full pipe buffer.
        self._process.readAllStandardError()

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("PROGRESS|"):
            try:
                _, message, current, total = line.split("|", 3)
                self.progress.emit(message, int(current), int(total))
            except ValueError:
                pass
        elif line.startswith("RESULT|"):
            payload = line[len("RESULT|"):]
            try:
                items = json.loads(payload)
                self._results = [StudentPdfResult(**item) for item in items]
            except (json.JSONDecodeError, TypeError) as exc:
                self._error_message = f"Failed to parse marking worker result: {exc}"
        elif line.startswith("ERROR|"):
            self._error_message = line[len("ERROR|"):]

    def _handle_process_finished(self, exit_code: int, exit_status) -> None:
        if self._stdout_buffer.strip():
            self._handle_line(self._stdout_buffer.strip())
            self._stdout_buffer = ""

        if self._results is not None:
            self.succeeded.emit(self._results)
        elif self._error_message is not None:
            self.failed.emit(self._error_message)
        else:
            self.failed.emit(f"Marking worker process exited unexpectedly (code {exit_code}) with no result.")
        self.finished.emit()


_MARK_ANSWER_FILE_WORKER_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "workers" / "mark_answer_file_worker_process.py"
)


class MarkAnswerFileSubprocessWorker(QObject):
    """Data Management Follow-up (feature 3): runs run_mark_answers_for_
    answer_file (extraction + marking + overlay creation for ONE student)
    in a separate OS process via QProcess - mirrors
    StudentPdfProcessingSubprocessWorker exactly (same rationale: real
    PaddleOCR inside a QThread in this process was found to crash the app,
    see that class's docstring), just for a single answer_file_id instead
    of a whole upload batch.

    Signals:
        progress(message, current, total) - forwarded from the worker
            script's PROGRESS lines, for a CircularProgressWidget.
        succeeded() - the RESULT|ok line arrived; marking finished cleanly.
        failed(message) - an ERROR|... line arrived, or the process exited
            without ever producing a RESULT/ERROR line.
        finished() - always emitted last, success or failure, so the
            caller can always re-enable its "Mark Answers" button and hide
            the progress dialog in one place.
    """

    progress = Signal(str, int, int)
    succeeded = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, teacher_id: int, profile_id: int, answer_file_id: int, parent=None) -> None:
        super().__init__(parent)
        self._teacher_id = teacher_id
        self._profile_id = profile_id
        self._answer_file_id = answer_file_id
        self._succeeded = False
        self._error_message: Optional[str] = None
        self._stdout_buffer = ""

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._handle_stdout_ready)
        self._process.readyReadStandardError.connect(self._handle_stderr_ready)
        self._process.finished.connect(self._handle_process_finished)

    def start(self) -> None:
        program, args = _worker_launch(
            "mark_answer_file", _MARK_ANSWER_FILE_WORKER_SCRIPT_PATH,
            [str(self._teacher_id), str(self._profile_id), str(self._answer_file_id)])
        self._process.start(program, args)

    def isRunning(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def wait(self, timeout_ms: int = 30000) -> bool:
        return self._process.waitForFinished(timeout_ms)

    def _handle_stdout_ready(self) -> None:
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._stdout_buffer += chunk
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            self._handle_line(line.rstrip("\r"))

    def _handle_stderr_ready(self) -> None:
        self._process.readAllStandardError()

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("PROGRESS|"):
            try:
                _, message, current, total = line.split("|", 3)
                self.progress.emit(message, int(current), int(total))
            except ValueError:
                pass
        elif line.startswith("RESULT|"):
            self._succeeded = True
        elif line.startswith("ERROR|"):
            self._error_message = line[len("ERROR|"):]

    def _handle_process_finished(self, exit_code: int, exit_status) -> None:
        if self._stdout_buffer.strip():
            self._handle_line(self._stdout_buffer.strip())
            self._stdout_buffer = ""

        if self._succeeded:
            self.succeeded.emit()
        elif self._error_message is not None:
            self.failed.emit(self._error_message)
        else:
            self.failed.emit(f"Mark Answers worker process exited unexpectedly (code {exit_code}) with no result.")
        self.finished.emit()
