"""Data Management Follow-up (feature 3): subprocess entry point for
running one student's "Mark Answers" (extraction + marking + overlay
creation) outside the main app process.

Mirrors app/workers/subject_profile_marking_worker_process.py exactly -
see that file's docstring for why a genuinely separate OS process (via
QProcess), not a QThread, is used for real-OCR work in this codebase:
constructing/running real PaddleOCR inside a QThread was found to crash
the whole app with no Python traceback. The Marking Editor's "Mark
Answers" button runs extraction (real OCR) for one student, which can take
long enough to freeze the UI on the old synchronous-on-the-main-thread
path - this script lets app.ui.subject_profile_worker.
MarkAnswerFileSubprocessWorker run it in the background instead, with a
circular progress indicator updating from its PROGRESS lines.

Line protocol (stdout, UTF-8, one event per line):
  PROGRESS|<message>|<current>|<total>
  RESULT|ok
  ERROR|<message>
Exit code 0 after a RESULT line, non-zero after an ERROR line.

SUBJECT_PROFILE_WORKER_FAKE_OCR=1 (test-only): use a trivial built-in fake
OCR engine instead of real PaddleOCR, so tests can exercise this whole
script (launch, protocol, exit code) fast/deterministically without the
real dependency - never set in production.
"""
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.database.db import get_connection
from app.services.subject_profile_service import run_mark_answers_for_answer_file


def _fake_engine_for_tests():
    from app.utils.ocr_engine import PageOCRResult

    class _FakeEngine:
        def run_page(self, image_path: str) -> PageOCRResult:
            return PageOCRResult(text="B", average_confidence=0.9, blocks=[])

    return _FakeEngine()


def main() -> None:
    if len(sys.argv) != 4:
        print("ERROR|Usage: mark_answer_file_worker_process.py <teacher_id> <profile_id> <answer_file_id>", flush=True)
        sys.exit(1)

    teacher_id = int(sys.argv[1])
    profile_id = int(sys.argv[2])
    answer_file_id = int(sys.argv[3])

    def _on_progress(message: str, current: int, total: int) -> None:
        safe_message = message.replace("|", "/").replace("\n", " ").replace("\r", " ")
        print(f"PROGRESS|{safe_message}|{current}|{total}", flush=True)

    engine = _fake_engine_for_tests() if os.environ.get("SUBJECT_PROFILE_WORKER_FAKE_OCR") == "1" else None

    conn = get_connection()
    try:
        run_mark_answers_for_answer_file(
            conn, teacher_id, profile_id, answer_file_id, progress_callback=_on_progress, engine=engine,
        )
        print("RESULT|ok", flush=True)
    except Exception as exc:
        print(f"ERROR|{exc}", flush=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
