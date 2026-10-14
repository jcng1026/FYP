"""Synchronous worker-facing orchestration with cooperative cancellation."""

import threading

from app.models.core_ai_backend_contracts import BackendError, JobStatus, TERMINAL_JOB_STATES
from app.services.core_ai_backend_job_service import CancellationToken


class AIBackendOrchestrator:
    def __init__(self, job_store):
        self.job_store = job_store
        self._tokens = {}
        self._processes = {}
        self._lock = threading.RLock()

    def create_training_job(self, request, job_id=None):
        return self.job_store.create(request, job_id)

    def get_job(self, job_id):
        return self.job_store.get(job_id)

    def list_jobs(self, model_family=None):
        return self.job_store.list(model_family)

    def register_subprocess(self, job_id, process):
        with self._lock:
            if JobStatus(self.job_store.get(job_id).status) in TERMINAL_JOB_STATES:
                raise BackendError("job_terminal", "Cannot register a process for a terminal job.")
            self._processes[job_id] = process

    def unregister_subprocess(self, job_id):
        with self._lock:
            self._processes.pop(job_id, None)

    def _terminate_process(self, job_id, timeout=5):
        with self._lock:
            process = self._processes.get(job_id)
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=timeout)
        finally:
            self.unregister_subprocess(job_id)

    def cancel_job(self, job_id):
        record = self.job_store.request_cancellation(job_id)
        with self._lock:
            token = self._tokens.get(job_id)
        if token:
            token.cancel()
        self._terminate_process(job_id)
        if record.status == JobStatus.CANCELLING.value and token is None:
            return self.job_store.transition(job_id, JobStatus.CANCELLED, "Cancelled before worker execution.")
        return self.job_store.get(job_id)

    def run_job(self, job_id, operation):
        """Run in a worker; operation receives (token, progress_callback)."""
        token = CancellationToken()
        with self._lock:
            if job_id in self._tokens:
                raise BackendError("job_already_running", "This job already has a worker.")
            self._tokens[job_id] = token
        progress = lambda message, **values: self.job_store.append_progress(job_id, message, **values)
        try:
            self.job_store.transition(job_id, JobStatus.VALIDATING, "Validating job request.")
            token.raise_if_cancelled()
            self.job_store.transition(job_id, JobStatus.RUNNING, "Job execution started.")
            result = operation(token, progress)
            token.raise_if_cancelled()
            self.job_store.transition(job_id, JobStatus.PUBLISHING, "Publishing immutable artifacts.")
            return self.job_store.transition(job_id, JobStatus.COMPLETED, "Job completed.", result_model_version=result)
        except BackendError as exc:
            current = self.job_store.get(job_id)
            if exc.code == "cancelled" or current.cancellation_requested:
                if current.status != JobStatus.CANCELLING.value:
                    current = self.job_store.request_cancellation(job_id)
                return self.job_store.transition(job_id, JobStatus.CANCELLED, "Job cancelled cooperatively.")
            if JobStatus(current.status) not in TERMINAL_JOB_STATES:
                return self.job_store.transition(job_id, JobStatus.FAILED, "Job failed.", failure_code=exc.code, failure_message=exc.safe_message)
            return current
        except Exception:
            current = self.job_store.get(job_id)
            if JobStatus(current.status) not in TERMINAL_JOB_STATES:
                return self.job_store.transition(job_id, JobStatus.FAILED, "Job failed.", failure_code="unhandled_job_failure", failure_message="The worker failed without publishing artifacts.")
            return current
        finally:
            self._terminate_process(job_id)
            with self._lock:
                self._tokens.pop(job_id, None)

    def recover_after_restart(self):
        return self.job_store.recover_interrupted()

    @staticmethod
    def validate_resume_request(explicitly_requested, checkpoint_compatible):
        if not explicitly_requested:
            raise BackendError("resume_not_explicit", "Training resume must be explicitly requested.")
        if not checkpoint_compatible:
            raise BackendError("resume_incompatible", "Training checkpoint is not compatible with this request.")
        return True
