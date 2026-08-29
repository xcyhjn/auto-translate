from __future__ import annotations

from autosub_zh.project_paths import WEB_DIR

def test_reference_mode_selector_exposes_full_split() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert '<option value="full_split">full_split</option>' in html


def test_frontend_exposes_entity_review_and_bootstrap_mode() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="bootstrap_entity_decisions"' in html
    assert '<option value="high_confidence_only">high_confidence_only</option>' in html
    assert '<option value="always">always</option>' in html
    assert '<option value="off">off</option>' in html
    assert 'id="entityReviewPanel"' in html
    assert "07i_entity_metrics.json" in app_js
    assert "06f_entity_review.tsv" in app_js
    assert "07h_entity_qa.tsv" in app_js
    assert "reference_text" in app_js


def test_project_outputs_entity_review_labels_are_localized() -> None:
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "实体审阅" in app_js
    assert "选中项目" in app_js
    assert "实体审阅 TSV" in app_js
    assert "实体 QA TSV" in app_js
    assert "参考文本对照" in app_js
    assert "暂无分类决策" in app_js
    assert "06f_entity_review.tsv 中未找到实体审阅行" in app_js
    assert "06g_entity_normalized_segments.json 中未找到 reference_text 行" in app_js
    assert "Entity Review TSV" not in app_js
    assert "Reference Text Comparison" not in app_js


def test_frontend_exposes_workflow_pause_and_collapse_controls() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "工作流预设" in html
    assert "有效工作流摘要" in html
    assert "字段说明与使用范例" in html
    assert "俄文范例" in html
    assert 'id="pauseFlowBtn"' in html
    assert 'id="resumeFlowBtn"' in html
    assert 'id="toggleInputListBtn"' in html
    assert 'id="workspaceDetails"' in html
    assert 'fetch("/api/pause"' in app_js
    assert 'fetch("/api/resume"' in app_js
    assert "inputListCollapsed: true" in app_js
    assert "expandedProjectPath" in app_js
    assert "state.expandedProjectPath === project.path" in app_js
    assert "scrollToWorkspaceDetails()" in app_js
