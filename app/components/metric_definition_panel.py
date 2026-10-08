"""Compact definition cards and explicit, request-local clarification choices."""
from __future__ import annotations

import hashlib
import json
import streamlit as st

from insightpilot.planning.planner import prepare_analysis_request
from insightpilot.ui.theme import render_compact_summary_card
from insightpilot.ui.view_modes import should_show_professional_details


def _request_id(config) -> str:
    return hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')).hexdigest()


def render_metric_definitions(definitions, *, view_mode: str, required: bool = False) -> None:
    if not definitions:
        return
    if not should_show_professional_details(view_mode) and not required:
        first=definitions[0]
        st.caption(f"当前口径：{first.get('display_name',first.get('metric_id'))}；单位：{first.get('unit','未声明')}；来源与统计前提可在“查看口径与质量”复核。")
        return
    panel=st.expander('指标口径',expanded=required,key='metric_definition_details',on_change='rerun')
    if panel.open:
        with panel:
            options=list(range(len(definitions)))
            selected=st.selectbox('查看指标口径',options,format_func=lambda i: str(definitions[i].get('display_name',definitions[i].get('metric_id'))),key='metric_definition_selector') if len(options)>1 else 0
            card=definitions[selected]
            source={'user_confirmation':'用户明确确认','builtin_definition':'内置显式定义','automatic_suggestion':'自动建议，尚未确认','registered_definition':'已注册定义，需结合适用范围复核'}.get(card.get('source'),'未确认')
            status={'user_confirmed':'用户已确认','builtin_verified':'内置定义已核对','draft':'待复核'}.get(card.get('definition_status'),'待复核')
            expression=card.get('expression')
            if card.get('numerator') and card.get('denominator'):
                expression=f"分子：{card['numerator']}；分母：{card['denominator']}；聚合：{card.get('aggregation')}"
            unit_label={'not_applicable':'不适用','row':'观测行'}.get(card.get('statistical_unit'),card.get('statistical_unit') or '未确认')
            timezone_label={'naive':'未指定时区（按原始日期）'}.get(card.get('timezone'),card.get('timezone') or '未声明')
            details=[f"单位：{card.get('unit','未声明')}；口径版本：{card.get('definition_version','未声明')}",
                     str(expression),f"去重键：{card.get('deduplication_key') or '不适用'}；独立统计单位：{unit_label}",
                     f"日期字段：{card.get('date_column') or '不适用'}；时区：{timezone_label}",
                     f"时间范围：{card.get('time_range') or '当前配置的数据范围'}；基准：{card.get('comparison_baseline') or '见所选分析方法'}",
                     f"有效样本：{card.get('valid_sample','未验证')}",
                     f"来源：{source}；状态：{status}",
                     *[str(x) for x in card.get('data_quality_notes',[])[:5]]]
            render_compact_summary_card(str(card.get('display_name',card.get('metric_id','指标口径'))),details,
                help_text='口径确认不代表统计前提、显著性或因果关系已经验证。')


def prepare_and_render_clarification(snapshot, config, view_mode, *, render_ui=True):
    request_id=_request_id({'dataset_id':getattr(snapshot,'dataset_id',None),'revision':getattr(snapshot,'revision',None),**config})
    state=st.session_state.get('performance_clarification_state')
    if not state or state['request_id']!=request_id:
        state={'request_id':request_id,'answers':{}}
        st.session_state['performance_clarification_state']=state
    prepared=prepare_analysis_request(config['question'],table_metadata=snapshot.metadata if snapshot is not None else {},
        goal_mode=config['goal_mode'],playbook_id=config['playbook_id'],column_mapping=config['column_mapping'],
        playbook_parameters=config['parameters'],clarification_answers=state['answers'],
        dataset_revision=str(getattr(snapshot, 'revision', '')),
        selection_source=config.get('selection_source'), analysis_scope=config.get('analysis_scope'))
    if not render_ui:
        return prepared, dict(state["answers"])
    status=prepared['planning_status']; clarification=prepared['clarification']
    questions = [item for item in clarification.get('items', []) if not item.get('code')]
    if status=='needs_clarification' and questions:
        st.warning('开始计算前，需要确认会改变答案的口径。选择后点击确认，再点击“开始分析”。')
        items=questions[:3]
        selected={}
        for item in items:
            role=item['role']; options=item.get('candidates') or []
            key='clarification_'+request_id[:16]+'_'+role
            st.caption(item['reason'])
            if options:
                labels={str(x['value']):str(x['label']) for x in options}
                value=st.selectbox(item['question'],list(labels),index=None,format_func=labels.get,
                    placeholder='请选择口径，不自动默认确认',key=key)
            elif role=='date_range':
                dates=st.date_input(item['question'],value=(),key=key)
                value=[str(x) for x in dates] if isinstance(dates,(tuple,list)) and len(dates)==2 else None
            else:
                value=st.text_input(item['question'],value='',key=key) or None
            if value is not None: selected[role]=value
        if clarification.get('unresolved_count',0)>3:
            st.caption('先确认本页必要问题，后续问题将根据选择继续收敛。')
        if st.button('确认口径选择',key='clarification_confirm',disabled=not selected):
            state['answers']={**state['answers'],**selected}
            st.session_state['performance_clarification_state']=state
            st.rerun()
    elif status in {'unsupported','invalid_input'}:
        reasons=clarification.get('errors',[])+clarification.get('unsupported_reasons',[])
        st.error(('当前不支持此分析：' if status=='unsupported' else '分析配置无效：')+'；'.join(reasons))
    elif state['answers']:
        st.caption('口径选择已由本会话明确操作确认；尚未因此自动执行分析。')
    if questions:
        render_metric_definitions(prepared.get('metric_definitions',[]),view_mode=view_mode,required=True)
    return prepared,dict(state['answers'])


def refresh_result_presentation(result, prepared):
    """Refresh labels only for the identical calculation contract; share all large objects."""
    if not result.get('semantic_fingerprint') or result.get('semantic_fingerprint') != prepared.get('semantic_fingerprint'):
        return result
    old = result.get('metric_definitions', [])
    new = prepared.get('metric_definitions', [])
    if ({x.get('metric_id'): x.get('computation_fingerprint') for x in old}
            != {x.get('metric_id'): x.get('computation_fingerprint') for x in new}):
        return result
    if result.get('presentation_fingerprint') == prepared.get('presentation_fingerprint'):
        return result
    return {**result, 'metric_definitions': new, 'presentation_fingerprint': prepared['presentation_fingerprint'],
            'run_manifest': {**result.get('run_manifest', {}), 'metric_definitions': new,
                             'presentation_fingerprint': prepared['presentation_fingerprint']}}
