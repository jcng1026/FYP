"""Post-build verification of the packaged MarkAssist.exe.

Runs from any cwd. Steps:
  1. Copy the live data/ tree next to the exe (so the frozen build finds its
     writable data root there) if not already present.
  2. `MarkAssist.exe --selfcheck` -> data root, DB, Core AI 1/2 active models,
     Ollama config, and torch/transformers/ultralytics import - all from
     inside the frozen process.
  3. Launch the GUI: splash -> login -> real login -> teacher dashboard.
  4. `MarkAssist.exe --run-worker mark_answer_file <bad args>` -> confirms the
     frozen worker-relaunch dispatch reaches the worker (usage error, not a
     GUI launch).
"""
import os
import shutil
import subprocess
import sys
import time

APP_DIR = r"C:\Users\User\Documents\AutoMarkingSystem\english_grading_system"
DIST = os.path.join(APP_DIR, "dist", "MarkAssist")
EXE = os.path.join(DIST, "MarkAssist.exe")
SRC_DATA = os.path.join(APP_DIR, "data")
DST_DATA = os.path.join(DIST, "data")


def step(msg):
    print(f"\n=== {msg} ===", flush=True)


def ensure_data():
    step("1. data/ next to exe")
    if not os.path.isdir(DST_DATA):
        # Junction/copy the live data so the frozen exe has DB + models.
        print("copying data/ into dist (this can take a moment for the models)...", flush=True)
        shutil.copytree(SRC_DATA, DST_DATA)
    print("data present:", os.path.isdir(os.path.join(DST_DATA, "ai", "active")), flush=True)


def selfcheck():
    step("2. --selfcheck (whole stack from inside the frozen exe)")
    proc = subprocess.run([EXE, "--selfcheck"], capture_output=True, text=True, timeout=600)
    for line in proc.stdout.splitlines():
        if line.startswith("SELFCHECK|"):
            print("  " + line, flush=True)
    print("  selfcheck exit code:", proc.returncode, flush=True)
    if proc.returncode != 0:
        print("  STDERR tail:", proc.stderr[-800:], flush=True)
    return proc.returncode == 0


def worker_dispatch():
    step("4. --run-worker dispatch reaches the worker (not the GUI)")
    # Deliberately wrong arg count -> worker main() prints its ERROR|Usage line.
    proc = subprocess.run([EXE, "--run-worker", "mark_answer_file", "not_enough_args"],
                          capture_output=True, text=True, timeout=120)
    out = (proc.stdout + proc.stderr)
    reached = "Usage: mark_answer_file_worker_process" in out
    print("  worker dispatch reached worker entry:", reached, flush=True)
    if not reached:
        print("  output:", out[:600], flush=True)
    return reached


def gui_launch():
    step("3. GUI launch: splash -> login -> teacher dashboard")
    try:
        from pywinauto import Desktop
        from pywinauto.timings import wait_until_passes
    except Exception as exc:
        print("  pywinauto unavailable, skipping GUI drive:", exc, flush=True)
        return None
    proc = subprocess.Popen([EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("  exe pid:", proc.pid, flush=True)
    desk = Desktop(backend="uia")

    def _login():
        w = desk.window(title_re="MarkAssist . Sign in")
        if w.exists():
            return w
        raise RuntimeError("no login yet")

    try:
        login = wait_until_passes(180, 2.0, _login)
    except Exception:
        print("  LOGIN WINDOW DID NOT APPEAR within 180s", flush=True)
        proc.terminate()
        return False
    print("  login window appeared", flush=True)
    login.set_focus(); time.sleep(1.0)
    edits = login.descendants(control_type="Edit")
    edits[0].set_edit_text("Dr Zailan"); edits[1].set_edit_text("123")
    for b in login.descendants(control_type="Button"):
        if b.window_text() == "Sign In":
            try: b.invoke()
            except Exception: b.click_input()
            break

    def _teacher():
        w = desk.window(title_re="MarkAssist . Teacher")
        if w.exists():
            return w
        raise RuntimeError("no teacher yet")
    try:
        teacher = wait_until_passes(60, 2.0, _teacher)
        teacher.set_focus(); time.sleep(1.5)
        teacher.capture_as_image().save(os.path.join(APP_DIR, "exe_teacher_dashboard.png"))
        nav = [c.window_text() for c in teacher.descendants(control_type="CheckBox")]
        print("  teacher dashboard opened; nav items:", nav, flush=True)
        ok = "Marking" in nav
    except Exception:
        print("  TEACHER DASHBOARD DID NOT OPEN (login may have failed)", flush=True)
        ok = False
    proc.terminate()
    return ok


if __name__ == "__main__":
    if not os.path.isfile(EXE):
        print("EXE NOT FOUND:", EXE)
        sys.exit(2)
    ensure_data()
    results = {
        "selfcheck": selfcheck(),
        "worker_dispatch": worker_dispatch(),
        "gui": gui_launch(),
    }
    print("\n=== SUMMARY ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
