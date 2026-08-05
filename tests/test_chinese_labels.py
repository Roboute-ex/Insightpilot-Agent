from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "ui_streamlit.py"


def test_default_app_controls_use_chinese_labels() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    labels = {item.label for item in app.selectbox}
    labels.update(item.label for item in app.segmented_control)
    labels.update(item.label for item in app.button)
    assert {"界面模式", "数据来源", "分析目标模式", "工作流后端", "演示场景", "预览数据表", "分析剧本", "开始分析", "预览分析方案"}.issubset(labels)
    assert {"Data Source", "Analysis Goal Mode", "Workflow Backend", "Caveats", "Analysis Plan"}.isdisjoint(labels)
