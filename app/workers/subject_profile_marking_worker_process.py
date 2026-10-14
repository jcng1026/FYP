"""Marking Fix Follow-up: subprocess entry point for running student PDF
extraction/marking outside the main app process.

Background: StudentPdfProcessingWorker (a QThread, see app.ui.
subject_profile_worker) was found to crash the WHOLE app process with no
Python traceback (a bare process exit) when constructing/running real
PaddleOCR inside it - reproduced repeatedly during manual verification,
succeeding only about 1 time in 5. A plain standalone script (no Qt/
QThread involved at all) running the IDENTICAL extraction+marking against
the same real profile completed reliably every single time. Since a
QProcess-launched script IS, architecturally, exactly that same "plain
standalone script" scenario, running this here sidesteps whatever
in-process Qt+PaddleOCR interaction was causing the instability, without
requiring a full root-cause of the native-level conflict (see
app.ui.subject_profile_worker.StudentPdfProcessingSubprocessWorker, which
launches this script and is the new default for the real upload workflow).

Line protocol (stdout, UTF-8, one event per line - see
StudentPdfProcessingSubprocessWorker._handle_line for the parser):
  PROGRESS|<message>|<current>|<total>
  RESULT|<json array of StudentPdfResult fields>
  ERROR|<message>
Exit code 0 after a RESULT line, non-zero after an ERROR line.

SUBJECT_PROFILE_WORKER_FAKE_OCR=1 (test-only): use a trivial built-in fake
OCR engine instead of real PaddleOCR, so tests can exercise this whole
script (launch, protocol, exit code) fast/deterministically without the
real dependency - never set in production.
"""
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.database.db import get_connection
from app.services.subject_profile_service import mark_student_answer_pdfs_for_profile


def _fake_engine_for_tests():
    from app.utils.ocr_engine import PageOCRResult

    class _FakeEngine:
        def run_page(self, image_path: str) -> PageOCRResult:
            return PageOCRResult(text="B", average_confidence=0.9, blocks=[])

    return _FakeEngine()


def main() -> None:
    if len(sys.argv) != 4:
        print("ERROR|Usage: subject_profile_marking_worker_process.py <teacher_id> <profile_id> <json_paths>", flush=True)
        sys.exit(1)

    teacher_id = int(sys.argv[1])
    profile_id = int(sys.argv[2])
    student_pdf_paths = json.loads(sys.argv[3])

    def _on_progress(message: str, current: int, total: int) -> None:
        safe_message = message.replace("|", "/").replace("\n", " ").replace("\r", " ")
        print(f"PROGRESS|{safe_message}|{current}|{total}", flush=True)

    engine = _fake_engine_for_tests() if os.environ.get("SUBJECT_PROFILE_WORKER_FAKE_OCR") == "1" else None

    conn = get_connection()
    try:
        results = mark_student_answer_pdfs_for_profile(
            conn, teacher_id, profile_id, student_pdf_paths,
            progress_callback=_on_progress, engine=engine,
        )
        payload = [
            {
                "file_path": r.file_path, "display_name": r.display_name,
                "answer_file_id": r.answer_file_id, "session_id": r.session_id,
                "succeeded": r.succeeded, "error": r.error,
            }
            for r in results
        ]
        print(f"RESULT|{json.dumps(payload)}", flush=True)
    except Exception as exc:
        print(f"ERROR|{exc}", flush=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
