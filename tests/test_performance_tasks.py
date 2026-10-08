"""Real-thread lifecycle tests on tiny objects; no analytics benchmarks."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import gc
import threading
import time
import weakref

import pytest

from insightpilot.performance_tasks import (
    TaskManager, TaskSnapshot, TaskBusyError, TaskNotReadyError, StaleTaskResultError,
    TaskExecutionError, TaskCancelledError, report_stage, cancellation_checkpoint,
)


def eventually(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("Small background task did not reach its expected state")


def finished(manager, owner):
    def terminal():
        value = manager.snapshot(owner)
        return value if value is not None and value.status in {"completed", "failed", "cancelled"} else None
    return eventually(terminal)


class Payload:
    def __init__(self, data=b"value"):
        self.data = data


def test_context_helpers_are_noops_outside_worker_and_snapshot_has_no_result():
    cancellation_checkpoint()
    report_stage("同步CLI阶段")
    assert {item.name for item in fields(TaskSnapshot)} == {"task_id", "key", "revision", "status", "phase", "elapsed"}
    with TaskManager() as manager:
        submitted = manager.submit("owner", "config", 1, lambda: {"secret": "local-only"})
        result = finished(manager, "owner")
        assert result.revision == "1" and result.elapsed >= 0
        assert "local-only" not in repr(result)
        with pytest.raises(FrozenInstanceError):
            result.status = "changed"
        assert manager.take_result("owner", submitted.task_id, "config", 1) == {"secret": "local-only"}
        assert manager.snapshot("owner") is None


def test_two_workers_owner_dedup_and_busy_requests_never_queue():
    gate = threading.Event()
    started = [threading.Event(), threading.Event()]
    called = []
    def work(index):
        def execute():
            called.append(index)
            report_stage(f"计算{index}")
            started[index].set()
            assert gate.wait(3)
            cancellation_checkpoint()
            return index
        return execute
    with TaskManager() as manager:
        try:
            first = manager.submit("a", "key-a", "r1", work(0))
            second = manager.submit("b", "key-b", "r1", work(1))
            assert all(event.wait(2) for event in started)
            duplicate = manager.submit("a", "key-a", "r1", lambda: called.append("duplicate"))
            assert duplicate.task_id == first.task_id
            assert manager.snapshot("a").phase == "计算0"
            with pytest.raises(TaskBusyError):
                manager.submit("a", "new-key", "r1", lambda: called.append("wrong-owner"))
            with pytest.raises(TaskBusyError):
                manager.submit("c", "key-c", "r1", lambda: called.append("queued"))
            with pytest.raises(TaskNotReadyError):
                manager.take_result("a", first.task_id, first.key, first.revision)
            assert manager.stats()["running"] == 2
            assert called == [0, 1] or called == [1, 0]
        finally:
            gate.set()
        finished(manager, "a"); finished(manager, "b")
        assert manager.take_result("a", first.task_id, first.key, first.revision) == 0
        assert manager.take_result("b", second.task_id, second.key, second.revision) == 1
        assert manager.stats()["tasks"] == 0


def test_owner_and_full_admission_identity_are_required_for_transfer():
    payload = {"user-specific": b"local-data"}
    with TaskManager() as manager:
        task = manager.submit("private-owner", "correct-key", "7", lambda: payload)
        finished(manager, "private-owner")
        assert manager.snapshot("another-owner") is None
        for owner, task_id, key, revision in (
            ("another-owner", task.task_id, task.key, task.revision),
            ("private-owner", "guessed-task", task.key, task.revision),
            ("private-owner", task.task_id, "changed-config", task.revision),
            ("private-owner", task.task_id, task.key, "8"),
        ):
            with pytest.raises(StaleTaskResultError):
                manager.take_result(owner, task_id, key, revision)
        assert manager.stats()["tasks"] == 1
        assert manager.take_result("private-owner", task.task_id, task.key, task.revision) is payload
        with pytest.raises(StaleTaskResultError):
            manager.take_result("private-owner", task.task_id, task.key, task.revision)


def test_cancel_is_only_a_request_until_native_like_step_returns_and_finally_runs():
    gate, entered, cleaned = threading.Event(), threading.Event(), threading.Event()
    def work():
        try:
            report_stage("等待原生步骤返回")
            entered.set()
            assert gate.wait(3)
            # Old broad business handlers must not consume cancellation.
            try:
                cancellation_checkpoint()
            except Exception:
                return "incorrectly swallowed"
        finally:
            cleaned.set()
    with TaskManager(max_workers=1) as manager:
        task = manager.submit("owner", "key", "1", work)
        try:
            assert entered.wait(2)
            assert manager.cancel("owner").status == "cancel_requested"
            assert manager.snapshot("owner").status == "cancel_requested"
            assert manager.stats()["running"] == 1
            assert not cleaned.is_set()
            with pytest.raises(TaskNotReadyError):
                manager.take_result("owner", task.task_id, task.key, task.revision)
            with pytest.raises(TaskBusyError):
                manager.submit("other", "key", "1", lambda: None)
        finally:
            gate.set()
        assert finished(manager, "owner").status == "cancelled"
        assert cleaned.is_set() and manager.stats()["running"] == 0
        with pytest.raises(TaskCancelledError):
            manager.take_result("owner", task.task_id, task.key, task.revision)
        assert manager.stats()["tasks"] == 0


def test_release_running_owner_discards_late_result_and_input_closure():
    gate, started = threading.Event(), threading.Event()
    payload = Payload()
    reference = weakref.ref(payload)
    def make_work(value):
        def work():
            started.set()
            assert gate.wait(3)
            return value
        return work
    work = make_work(payload)
    with TaskManager() as manager:
        manager.submit("a", "old-source", "1", work)
        del payload, work
        try:
            assert started.wait(2)
            manager.release("a")
            assert manager.snapshot("a").status == "cancel_requested"
            gc.collect()
            assert reference() is not None
        finally:
            gate.set()
        eventually(lambda: manager.stats()["running"] == 0)
        assert manager.snapshot("a") is None
        eventually(lambda: (gc.collect(), reference() is None)[1])


def test_failure_has_no_native_input_message_and_frees_work_closure():
    payload = Payload()
    reference = weakref.ref(payload)
    def make_work(value):
        def work():
            assert value.data
            raise RuntimeError("password=do-not-copy-or-display")
        return work
    work = make_work(payload)
    with TaskManager() as manager:
        task = manager.submit("a", "key", "1", work)
        del payload, work
        assert finished(manager, "a").status == "failed"
        eventually(lambda: (gc.collect(), reference() is None)[1])
        with pytest.raises(TaskExecutionError) as error:
            manager.take_result("a", task.task_id, task.key, task.revision)
        assert "RuntimeError" in str(error.value) and "do-not-copy" not in str(error.value)
        assert manager.stats()["tasks"] == 0
        retried = manager.submit("a", "key", "1", lambda: b"retry")
        finished(manager, "a")
        assert manager.take_result("a", retried.task_id, retried.key, retried.revision) == b"retry"


def test_task_and_global_result_byte_budgets_reject_without_retaining_fallback():
    with TaskManager(default_result_max_bytes=6, retained_max_bytes=10) as manager:
        too_big = manager.submit("over-task", "key", "1", lambda: b"1234567")
        assert finished(manager, "over-task").status == "failed"
        with pytest.raises(TaskExecutionError, match="超过本任务"):
            manager.take_result("over-task", too_big.task_id, too_big.key, too_big.revision)
        assert manager.stats()["retained_bytes"] == 0
        a = manager.submit("a", "key", "1", lambda: b"123456")
        finished(manager, "a")
        b = manager.submit("b", "key", "1", lambda: b"123456")
        assert finished(manager, "b").status == "failed"
        assert manager.stats()["retained_bytes"] == 6
        with pytest.raises(TaskExecutionError, match="总量超过保留预算"):
            manager.take_result("b", b.task_id, b.key, b.revision)
        assert manager.take_result("a", a.task_id, a.key, a.revision) == b"123456"
        assert manager.stats()["retained_bytes"] == 0
        class Source:
            estimated_bytes = 9
        source = manager.submit("source", "key", "2", Source, result_max_bytes=10,
                                size_estimator=lambda value: value.estimated_bytes)
        assert finished(manager, "source").status == "completed"
        assert manager.stats()["retained_bytes"] == 9
        assert isinstance(manager.take_result("source", source.task_id, source.key, source.revision), Source)


def test_record_limit_bounds_small_completed_tasks_and_discard_is_owner_local():
    with TaskManager(max_workers=1, max_tasks=2) as manager:
        a = manager.submit("a", "key", "1", lambda: b"a")
        finished(manager, "a")
        manager.submit("b", "key", "1", lambda: b"b")
        finished(manager, "b")
        with pytest.raises(TaskBusyError, match="任务记录"):
            manager.submit("c", "key", "1", lambda: b"c")
        manager.discard("b")
        assert manager.snapshot("a").task_id == a.task_id
        manager.submit("c", "key", "1", lambda: b"c")
        finished(manager, "c")
        assert manager.stats()["tasks"] == 2


def test_fake_clock_touch_and_ttl_release_completed_payload():
    clock = [0.0]
    payload = Payload()
    reference = weakref.ref(payload)
    work = (lambda value: lambda: value)(payload)
    with TaskManager(ttl_seconds=10, clock=lambda: clock[0]) as manager:
        manager.submit("a", "key", "1", work)
        del payload, work
        finished(manager, "a")
        clock[0] = 6
        assert manager.snapshot("a") is not None
        clock[0] = 15
        assert manager.sweep() == 0
        clock[0] = 17
        assert manager.sweep() == 1
        assert manager.snapshot("a") is None
        eventually(lambda: (gc.collect(), reference() is None)[1])
        assert manager.stats()["retained_bytes"] == 0


def test_daemon_ttl_requests_running_cancel_without_any_browser_touch():
    gate, started = threading.Event(), threading.Event()
    def work():
        started.set()
        assert gate.wait(3)
        cancellation_checkpoint()
    with TaskManager(ttl_seconds=0.05, cleanup_interval_seconds=0.01) as manager:
        manager.submit("idle-owner", "key", "1", work)
        try:
            assert started.wait(2)
            # No snapshot()/sweep() calls: inspect state only to prove daemon action.
            eventually(lambda: manager._tasks["idle-owner"].cancel_event.is_set())
            assert manager._tasks["idle-owner"].status == "cancel_requested"
            assert manager._running == 1
        finally:
            gate.set()
        eventually(lambda: "idle-owner" not in manager._tasks)
        assert manager.stats()["running"] == 0


def test_close_cancels_releases_and_does_not_claim_native_step_was_killed():
    gate, entered = threading.Event(), threading.Event()
    manager = TaskManager()
    def work():
        entered.set()
        assert gate.wait(3)
        cancellation_checkpoint()
    try:
        manager.submit("a", "key", "1", work)
        assert entered.wait(2)
        manager.close(wait=False)
        assert manager.stats()["closed"] is True
        assert manager.stats()["running"] == 1
        assert manager.snapshot("a").status == "cancel_requested"
        assert not manager._sweeper.is_alive()
        with pytest.raises(TaskBusyError, match="已关闭"):
            manager.submit("b", "key", "1", lambda: None)
    finally:
        gate.set()
        manager.close(wait=True)
    assert manager.stats()["tasks"] == manager.stats()["running"] == manager.stats()["retained_bytes"] == 0


def test_replacement_and_completion_release_estimator_closure():
    captured = Payload()
    reference = weakref.ref(captured)
    estimator = (lambda value: lambda result: len(result) if value.data else 0)(captured)
    with TaskManager() as manager:
        first = manager.submit("a", "first", "1", lambda: b"value", size_estimator=estimator)
        del captured, estimator
        finished(manager, "a")
        eventually(lambda: (gc.collect(), reference() is None)[1])
        second = manager.submit("a", "second", "2", lambda: b"new")
        assert second.task_id != first.task_id
        finished(manager, "a")
        assert manager.stats()["retained_bytes"] == 3
        with pytest.raises(StaleTaskResultError):
            manager.take_result("a", first.task_id, first.key, first.revision)
        assert manager.take_result("a", second.task_id, second.key, second.revision) == b"new"


def test_daemon_releases_completed_object_without_snapshot_or_manual_sweep():
    complete = threading.Event()
    payload = Payload()
    reference = weakref.ref(payload)
    def make_work(value):
        def work():
            complete.set()
            return value
        return work
    work = make_work(payload)
    with TaskManager(ttl_seconds=0.15, cleanup_interval_seconds=0.01) as manager:
        manager.submit("idle-completed", "key", "1", work)
        del payload, work
        assert complete.wait(2)
        # Direct inspection prevents this test from touching TTL or doing cleanup itself.
        eventually(lambda: manager._tasks.get("idle-completed") is not None and manager._tasks["idle-completed"].status == "completed")
        assert reference() is not None
        eventually(lambda: "idle-completed" not in manager._tasks)
        eventually(lambda: (gc.collect(), reference() is None)[1])
        assert manager._retained_bytes == 0


def test_controlled_memory_error_preserves_redacted_budget_instructions():
    from insightpilot.performance import MemoryBudgetExceeded
    def work():
        report_stage("数据快照预算")
        raise MemoryBudgetExceeded("输入估计4096字节超过dataset预算1024字节；未复制或截断输入，请调整明确预算。")
    with TaskManager() as manager:
        task = manager.submit("owner", "key", "1", work)
        assert finished(manager, "owner").status == "failed"
        with pytest.raises(TaskExecutionError) as error:
            manager.take_result("owner", task.task_id, task.key, task.revision)
        assert "4096" in str(error.value) and "1024" in str(error.value)
        assert "未复制或截断输入" in str(error.value)
        assert len(str(error.value)) <= 500
