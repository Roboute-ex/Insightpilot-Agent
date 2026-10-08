"""Independent task contracts, report binding and non-probabilistic quality UI."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from insightpilot.analysis.quality import QUALITY_NOTICE, derive_quality_status
from insightpilot.evaluation.harness import EvaluationHarness
from insightpilot.evaluation.models import EvaluationCase
from insightpilot.evaluation.task_suite import build_task_cases, run_task_evaluation, _run_period
from insightpilot.reports.manifest import RunManifest


@pytest.fixture(scope="module")
def small_result():
    return _run_period()


def test_task_suite_covers_twelve_families_with_independent_expected():
    cases=build_task_cases()
    assert 20<=len(cases)<=30
    assert len({c.family for c in cases})==12
    assert all(c.expected and c.question and c.input_fixture and c.required_evidence and c.forbidden_behaviors for c in cases)
    assert len({c.case_id for c in cases})==len(cases)
    # Fixed fixtures disclose their independent arithmetic rather than self-oracles.
    weighted=next(c for c in cases if c.case_id=='weighted_ratio_not_mean')
    assert weighted.expected['weighted']==81/110
    result=run_task_evaluation().to_dict()
    assert result['passed'],json.dumps([r for r in result['results'] if r['status']!='PASS'],ensure_ascii=False)
    from insightpilot.evaluation.guided_suite import GUIDED_FAMILIES
    expected_families = {c.family for c in cases} | set(GUIDED_FAMILIES.values())
    assert result['failed_cases']==0 and set(result['task_families'])==expected_families
    assert all(r['actual_summary']['checks'] for r in result['results'])


def test_failed_task_and_exception_are_retained_not_relabelled_as_success():
    def fails(): return {'scores':{'contract':0},'failures':['数字不符'],'observed':{'value':2}}
    def throws(): raise ValueError('预期执行通路不可用')
    result=EvaluationHarness().run([EvaluationCase('bad','task','bad',fails,family='test'),EvaluationCase('throw','task','throw',throws,family='test')])
    assert not result.passed and len(result.results)==2
    assert all(r.status=='FAIL' for r in result.results)
    assert result.results[0].errors==['数字不符']
    assert result.results[1].errors==['预期执行通路不可用']


def test_reviewer_hundred_does_not_verify_definition_or_inference():
    result={'execution_status':'COMPLETED','goal_mode':'experiment_analysis','reviewer':{'score':100,'status':'PASS'},'analysis_result_package':{'experiment_results':[{'p_value':1e-12}]}}
    quality=derive_quality_status(result)
    assert quality['execution_status']['status']=='completed'
    assert quality['definition_status']['status']=='unverified'
    assert quality['inference_status']['status']=='unverified'
    assert quality['data_quality_status']['status']=='unverified'
    assert quality['evidence_status']['status']=='unverified'


def test_quality_reads_existing_checks_and_never_mutates_result(small_result):
    before=deepcopy(small_result['metric_definitions'])
    with patch('insightpilot.reports.manifest.fingerprint_dataframe',side_effect=AssertionError('quality hashed')),patch('insightpilot.agents.workflow.run_agent_analysis',side_effect=AssertionError('quality analyzed')):
        quality=derive_quality_status(small_result)
    assert quality['definition_status']['status']=='confirmed'
    assert quality['data_quality_status']['status']=='checked'
    assert quality['inference_status']['status']=='not_applicable'
    assert quality['evidence_status']['status']=='linked'
    assert small_result['metric_definitions']==before
    failed={**small_result,'contract_results':[{'status':'FAIL'}]}
    assert derive_quality_status(failed)['data_quality_status']['status']=='failed'


def test_missing_evidence_link_is_not_complete(small_result):
    changed={**small_result,'analysis_result_package':{**small_result['analysis_result_package'],'recommendations':[{'supporting_evidence_ids':['missing-id']}]}}
    assert derive_quality_status(changed)['evidence_status']['status']=='unverified'
    assert derive_quality_status({**small_result,'execution_status':'PREVIEW'})['execution_status']['status']=='not_completed'


def test_metric_cards_and_manifest_are_same_run_and_backwards_compatible(small_result):
    from insightpilot.reports.definitions import bind_report_metadata,definition_cards
    manifest=RunManifest.from_dict(small_result['run_manifest'])
    assert manifest.manifest_version=='1.1'
    assert manifest.metric_definitions==small_result['metric_definitions']
    assert manifest.semantic_fingerprint==small_result['semantic_fingerprint']
    cards=definition_cards(bind_report_metadata(small_result,manifest))
    assert cards[0]['指标标识']=='revenue' and cards[0]['单位']=='元'
    old=manifest.to_dict()
    for key in ('metric_definitions','semantic_fingerprint','presentation_fingerprint','planning_status','clarification'):old.pop(key)
    old['manifest_version']='1.0'
    restored=RunManifest.from_dict(old)
    assert restored.metric_definitions==[] and restored.planning_status=='ready'
    with pytest.raises(ValueError,match='每项必须'):
        RunManifest.from_dict({**manifest.to_dict(),'metric_definitions':['not-a-card']})
    with pytest.raises(ValueError,match='planning_status'):
        RunManifest.from_dict({**manifest.to_dict(),'planning_status':'authorized-by-import'})


def test_html_excel_pdf_reject_mismatched_run(small_result):
    from insightpilot.reports.pdf import generate_pdf_report
    from insightpilot.reports.excel import generate_excel_report
    from insightpilot.reports.html import generate_html_report
    manifest=replace(RunManifest.from_dict(small_result['run_manifest']),run_id='wrong')
    for call in (lambda:generate_pdf_report(small_result,manifest),lambda:generate_excel_report(small_result,manifest),lambda:generate_html_report(small_result,[],manifest)):
        with pytest.raises(ValueError,match='运行编号'):call()


def test_report_definition_html_escaping_and_spreadsheet_neutralization(small_result):
    from insightpilot.reports.excel import generate_excel_report
    from insightpilot.reports.html import generate_html_report
    from openpyxl import load_workbook
    changed=deepcopy(small_result['metric_definitions']);changed[0]['display_name']='=1+1<script>bad-card</script>'
    manifest=replace(RunManifest.from_dict(small_result['run_manifest']),metric_definitions=changed)
    html=generate_html_report(small_result,[],manifest)
    assert '<script>bad-card</script>' not in html and '&lt;script&gt;bad-card&lt;/script&gt;' in html
    workbook=load_workbook(BytesIO(generate_excel_report(small_result,manifest)),read_only=True)
    assert not any(cell.data_type=='f' for row in workbook['指标口径'] for cell in row)
    workbook.close()


def test_quality_panel_three_modes_no_analysis_and_keeps_compact_cards():
    code='''
import streamlit as st
from app.components.reviewer_panel import render_quality_dimensions
mode=st.selectbox('模式',['demo','professional','developer'])
render_quality_dimensions({'execution_status':'COMPLETED','goal_mode':'experiment_analysis','reviewer':{'score':100,'status':'PASS'}},mode)
'''
    with patch('insightpilot.agents.workflow.run_agent_analysis',side_effect=AssertionError('display ran analysis')):
        app=AppTest.from_string(code).run()
        for mode in ['demo','professional','developer']:
            app.selectbox[0].set_value(mode).run()
            assert not app.exception
            assert any(QUALITY_NOTICE in item.value for item in app.caption)
            rendered=' '.join(item.value for item in app.markdown)
            assert rendered.count('ip-summary-card')==5
            assert '统计前提尚未验证' in rendered
            assert not app.json


def test_report_rejects_changed_computation_even_with_reused_fingerprint(small_result):
    from insightpilot.reports.definitions import bind_report_metadata
    manifest=RunManifest.from_dict(small_result['run_manifest'])
    cards=deepcopy(manifest.metric_definitions);cards[0]['expression']='sum(revenue)-sum(refund_amount)'
    with pytest.raises(ValueError,match='实际计算定义'):
        bind_report_metadata(small_result,replace(manifest,metric_definitions=cards))
    cards=deepcopy(manifest.metric_definitions);cards[0]['display_name']='新的展示标题'
    refreshed=bind_report_metadata(small_result,replace(manifest,metric_definitions=cards,presentation_fingerprint='new-display'))
    assert refreshed['metric_definitions'][0]['display_name']=='新的展示标题'
    assert small_result['metric_definitions'][0]['display_name']!='新的展示标题'
    assert refreshed['result_tables'] is small_result['result_tables']


def test_pdf_literal_definition_cells_keep_identifier_and_existing_text_budget():
    from insightpilot.reports.pdf import _literal_cell, _styles, MAX_PDF_CELL_CHARS
    cell=_literal_cell("sum(revenue)",_styles())
    assert cell.getPlainText()=="sum(revenue)"
    long=_literal_cell("口径"*1000,_styles()).getPlainText()
    assert "已截断" in long and len(long)<MAX_PDF_CELL_CHARS+30
