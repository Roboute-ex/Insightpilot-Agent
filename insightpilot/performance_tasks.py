"""Bounded, process-local background tasks with owner isolation and cooperative cancel.

Workers must not call Streamlit or access session state. Cancellation interrupts only
Python checkpoints; an in-flight native operation must return before it can stop.
"""
from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
import math
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from insightpilot.performance import PerformanceConfig, MemoryBudgetExceeded, estimate_size_bytes


class TaskBusyError(RuntimeError):
    pass


class TaskNotReadyError(RuntimeError):
    pass


class StaleTaskResultError(RuntimeError):
    pass


class TaskExecutionError(RuntimeError):
    """A bounded, sanitized failure message without a worker traceback or input."""


class TaskCancelledError(BaseException):
    """Cooperative cancellation; deliberately passes through except Exception."""


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    key: str
    revision: str
    status: str
    phase: str
    elapsed: float


@dataclass
class _Task:
    owner: str
    task_id: str
    key: str
    revision: str
    work: Callable[[], Any] | None
    size_estimator: Callable[[Any], int] | None
    result_max_bytes: int
    created_at: float
    last_seen: float
    cancel_event: threading.Event
    status: str = "queued"
    phase: str = "等待工作线程"
    finished_at: float | None = None
    result: Any = None
    result_bytes: int = 0
    error_message: str | None = None
    discard_when_done: bool = False


@dataclass(frozen=True)
class _TaskContext:
    manager: "TaskManager"
    task: _Task


_context: ContextVar[_TaskContext | None] = ContextVar("insightpilot_task", default=None)
_ACTIVE = frozenset({"queued", "running", "cancel_requested"})


def cancellation_checkpoint() -> None:
    """No-op outside a managed worker; cancel at this real execution boundary."""
    context = _context.get()
    if context is not None and context.task.cancel_event.is_set():
        raise TaskCancelledError("任务已在安全检查点停止。")


def report_stage(name: str) -> None:
    """Record an actual stage name; no invented percentage or remaining time."""
    context = _context.get()
    if context is None:
        return
    phase = str(name).replace("\n", " ").replace("\r", " ")[:256]
    with context.manager._lock:
        context.task.phase = phase
    cancellation_checkpoint()


class TaskManager:
    """One task per owner; no pending queue beyond the two reserved worker slots.

    Completed objects are bounded by per-task bytes, a global byte limit, record
    count and TTL. Access touches owner TTL; a daemon sweeps even without a browser.
    TTL/close/release request cooperative cancellation and discard late results.
    """
    def __init__(self, max_workers: int = 2, ttl_seconds: float = 1800.0,
                 clock: Callable[[], float] = time.monotonic, cleanup_interval_seconds: float = 30.0,
                 max_tasks: int = 8, retained_max_bytes: int = 2 * 1024**3,
                 default_result_max_bytes: int | None = None):
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or not 1 <= max_workers <= 2:
            raise ValueError("本地任务工作线程数量必须为1或2。")
        if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < max_workers:
            raise ValueError("任务记录上限不得小于线程数量。")
        for value in (ttl_seconds, cleanup_interval_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("任务TTL和清理周期必须为有限正数。")
        default_result_max_bytes = (PerformanceConfig.from_environment().result_max_bytes
                                    if default_result_max_bytes is None else default_result_max_bytes)
        for value in (retained_max_bytes, default_result_max_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("任务结果预算必须为正整数字节数。")
        self.max_workers = max_workers
        self.ttl_seconds = float(ttl_seconds)
        self.max_tasks = max_tasks
        self.retained_max_bytes = retained_max_bytes
        self.default_result_max_bytes = default_result_max_bytes
        self._clock = clock
        self._lock = threading.RLock()
        self._tasks: dict[str, _Task] = {}
        self._running = 0
        self._retained_bytes = 0
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="insightpilot-task")
        self._stop = threading.Event()
        self._cleanup_interval = min(float(cleanup_interval_seconds), 30.0)
        self._sweeper = threading.Thread(target=self._cleanup_loop, name="insightpilot-task-cleanup", daemon=True)
        self._sweeper.start()

    @staticmethod
    def _identity(owner: str, key: str, revision: str | int) -> tuple[str, str, str]:
        if not isinstance(owner, str) or not owner or len(owner) > 128:
            raise ValueError("owner必须是非空的会话随机标识。")
        if not isinstance(key, str) or not key or len(key) > 4096:
            raise ValueError("任务key必须是有界的配置标识字符串。")
        if isinstance(revision, bool) or not isinstance(revision, (str, int)):
            raise ValueError("revision必须是字符串或整数。")
        normalized = str(revision)
        if not normalized or len(normalized) > 256:
            raise ValueError("revision必须是有界的非空标识。")
        return owner, key, normalized

    def _view(self, task: _Task) -> TaskSnapshot:
        return TaskSnapshot(task.task_id, task.key, task.revision, task.status, task.phase,
                            max(0.0, (task.finished_at if task.finished_at is not None else self._clock()) - task.created_at))

    def _remove(self, task: _Task) -> None:
        if self._tasks.get(task.owner) is task:
            del self._tasks[task.owner]
        self._retained_bytes -= task.result_bytes
        task.result = None
        task.result_bytes = 0
        task.error_message = None
        task.work = None
        task.size_estimator = None

    def _request_cancel(self, task: _Task, *, discard: bool = False) -> None:
        task.cancel_event.set()
        task.discard_when_done = task.discard_when_done or discard
        if task.status in _ACTIVE:
            task.status = "cancel_requested"

    def submit(self, owner: str, key: str, revision: str | int, work: Callable[[], Any], *,
               result_max_bytes: int | None = None, size_estimator: Callable[[Any], int] | None = None) -> TaskSnapshot:
        owner, key, revision = self._identity(owner, key, revision)
        if not callable(work) or (size_estimator is not None and not callable(size_estimator)):
            raise TypeError("任务和结果估计器必须可调用。")
        budget = self.default_result_max_bytes if result_max_bytes is None else result_max_bytes
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
            raise ValueError("任务结果预算必须为正整数字节数。")
        with self._lock:
            self._sweep_locked()
            if self._closed:
                raise TaskBusyError("任务管理器已关闭，不能提交新任务。")
            previous = self._tasks.get(owner)
            if previous is not None:
                if previous.key == key and previous.revision == revision and previous.status in _ACTIVE | {"completed"}:
                    previous.last_seen = self._clock()
                    return self._view(previous)
                if previous.status in _ACTIVE:
                    raise TaskBusyError("本会话已有任务执行中。请先取消并等待当前步骤结束。")
                self._remove(previous)
            if self._running >= self.max_workers:
                raise TaskBusyError("本地两个执行槽已占用；未进入等待队列，请稍后重试。")
            if len(self._tasks) >= self.max_tasks:
                raise TaskBusyError("本地任务记录已达保留上限，请先接收或释放已完成结果。")
            now = self._clock()
            task = _Task(owner, str(uuid4()), key, revision, work, size_estimator or estimate_size_bytes,
                         budget, now, now, threading.Event())
            self._tasks[owner] = task
            self._running += 1
            try:
                self._executor.submit(self._execute, task)
            except BaseException:
                self._running -= 1
                self._remove(task)
                raise
            return self._view(task)

    def _execute(self, task: _Task) -> None:
        token = _context.set(_TaskContext(self, task))
        value = None
        work = estimator = None
        status, message, size = "failed", None, 0
        try:
            with self._lock:
                if not task.cancel_event.is_set():
                    task.status = "running"
                    task.phase = "开始执行"
                work, estimator = task.work, task.size_estimator
                task.work = task.size_estimator = None
            cancellation_checkpoint()
            value = work()
            cancellation_checkpoint()
            report_stage("检查任务结果保留预算")
            estimate = estimator(value)
            if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
                raise ValueError("结果估计器须返回非负整数字节数。")
            size = estimate
            if size > task.result_max_bytes:
                message = f"任务结果估计{size}字节，超过本任务{task.result_max_bytes}字节保留预算；未截断结果，请调整明确预算。"
                status = "failed"
            else:
                status = "completed"
            cancellation_checkpoint()
        except TaskCancelledError:
            status = "cancelled"
        except MemoryBudgetExceeded as exc:
            from insightpilot.reports.manifest import _safe_string
            status = "failed"
            # This controlled exception carries numeric budgets and recovery instructions.
            message = _safe_string(str(exc))[:500]
        except BaseException as exc:
            from insightpilot.reports.manifest import _safe_string
            status = "failed"
            # No native stack, repr(exc), SQL, cells or credentials cross into UI state.
            phase = _safe_string(task.phase)[:200]
            message = f"后台任务失败（{type(exc).__name__[:80]}；阶段：{phase}）。请检查输入和明确配置后重试。"
        finally:
            work = estimator = None
            _context.reset(token)
            with self._lock:
                self._running -= 1
                task.work = task.size_estimator = None
                task.finished_at = self._clock()
                if task.cancel_event.is_set():
                    status, message = "cancelled", None
                if status == "completed" and self._retained_bytes + size > self.retained_max_bytes:
                    status = "failed"
                    message = "本地已完成任务结果总量超过保留预算；未保留或截断本次结果。请释放已完成任务后重试。"
                task.status = status
                task.phase = {"completed": "已完成，等待接收结果", "failed": "执行失败", "cancelled": "已取消，当前任务已停止执行"}[status]
                task.error_message = message
                if status == "completed" and not task.discard_when_done:
                    task.result, task.result_bytes = value, size
                    self._retained_bytes += size
                if task.discard_when_done:
                    self._remove(task)
            value = None

    def snapshot(self, owner: str, *, touch: bool = True) -> TaskSnapshot | None:
        with self._lock:
            self._sweep_locked()
            task = self._tasks.get(owner)
            if task is None:
                return None
            if touch:
                task.last_seen = self._clock()
            return self._view(task)

    def take_result(self, owner: str, task_id: str, key: str, revision: str | int) -> Any:
        owner, key, revision = self._identity(owner, key, revision)
        with self._lock:
            self._sweep_locked()
            task = self._tasks.get(owner)
            if task is None or (task.task_id, task.key, task.revision) != (task_id, key, revision):
                raise StaleTaskResultError("任务与当前会话、配置或数据修订不匹配，未接收任何结果。")
            if task.status in _ACTIVE:
                raise TaskNotReadyError("工作线程尚未退出，结果暂不可接收。")
            status, message, value = task.status, task.error_message, task.result
            self._remove(task)
        if status == "cancelled":
            raise TaskCancelledError("任务已在安全检查点停止。")
        if status == "failed":
            raise TaskExecutionError(message or "后台任务失败，未生成可接收结果。")
        return value

    def cancel(self, owner: str) -> TaskSnapshot | None:
        with self._lock:
            self._sweep_locked()
            task = self._tasks.get(owner)
            if task is None:
                return None
            if task.status in _ACTIVE:
                self._request_cancel(task)
            task.last_seen = self._clock()
            return self._view(task)

    def release(self, owner: str) -> None:
        """Release only this owner; running input references live until worker exits."""
        with self._lock:
            task = self._tasks.get(owner)
            if task is not None:
                if task.status in _ACTIVE:
                    self._request_cancel(task, discard=True)
                else:
                    self._remove(task)

    discard = release

    def _sweep_locked(self) -> int:
        now = self._clock()
        expired = [task for task in self._tasks.values() if now - task.last_seen >= self.ttl_seconds]
        for task in expired:
            if task.status in _ACTIVE:
                self._request_cancel(task, discard=True)
            else:
                self._remove(task)
        return len(expired)

    def sweep(self) -> int:
        with self._lock:
            return self._sweep_locked()

    def _cleanup_loop(self) -> None:
        while not self._stop.wait(self._cleanup_interval):
            self.sweep()

    def stats(self) -> dict[str, int | bool]:
        with self._lock:
            self._sweep_locked()
            return {"tasks": len(self._tasks), "running": self._running, "retained_bytes": self._retained_bytes,
                    "max_tasks": self.max_tasks, "max_workers": self.max_workers,
                    "retained_max_bytes": self.retained_max_bytes, "closed": self._closed}

    def close(self, wait: bool = True) -> None:
        """Request cancellation and clear retained values. Native work is not killed.

        wait=False returns before an active native operation stops; CPython can
        still wait for executor threads at process exit. Prefer checkpoints/finally.
        """
        with self._lock:
            self._closed = True
            for task in list(self._tasks.values()):
                if task.status in _ACTIVE:
                    self._request_cancel(task, discard=True)
                else:
                    self._remove(task)
        self._stop.set()
        if threading.current_thread() is not self._sweeper:
            self._sweeper.join(timeout=1.0)
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def __enter__(self) -> "TaskManager":
        return self

    def __exit__(self, *args) -> None:
        self.close()


_default_lock = threading.Lock()
_default_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    """Single bounded manager for this process; owner IDs isolate user sessions."""
    global _default_manager
    with _default_lock:
        if _default_manager is None:
            config = PerformanceConfig.from_environment()
            _default_manager = TaskManager(ttl_seconds=config.session_ttl_seconds)
        return _default_manager


def _close_default_manager() -> None:
    if _default_manager is not None:
        _default_manager.close(wait=False)


atexit.register(_close_default_manager)
