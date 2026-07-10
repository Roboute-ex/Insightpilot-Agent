from __future__ import annotations

from insightpilot.reports.manifest import RunManifest, fingerprint_dataframe


def _manifest(playbook_tables) -> RunManifest:
    return RunManifest("1.0", "0.5.0", "run-1", "2026-01-01T00:00:00+00:00", "database", {"database_url": "sqlite://user:plain-password@localhost/db"}, [], {"analysis_table": fingerprint_dataframe(playbook_tables["analysis_table"])}, "question", "auto", "auto_detected", "rule_based", "data_profile", {}, {}, [], "PASS", 100, [], [])


def test_manifest_round_trip_masks_credentials(playbook_tables) -> None:
    manifest = _manifest(playbook_tables)
    content = manifest.to_json()
    assert "plain-password" not in content
    restored = RunManifest.from_json(content)
    assert restored.run_id == "run-1"


def test_manifest_removes_absolute_source_path(playbook_tables) -> None:
    manifest = _manifest(playbook_tables)
    manifest.table_summaries = [{"table_name": "table", "source_name": "C:\\private\\uploaded.csv"}]
    assert manifest.to_dict()["table_summaries"][0]["source_name"] == "uploaded.csv"


def test_dataframe_fingerprint_is_deterministic_and_changes(playbook_tables) -> None:
    frame = playbook_tables["analysis_table"]
    first = fingerprint_dataframe(frame)
    assert first == fingerprint_dataframe(frame.copy())
    changed = frame.copy()
    changed.loc[0, "metric"] += 1
    assert first != fingerprint_dataframe(changed)
