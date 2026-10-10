"""Real browser core workflow; isolated contexts and native controls only.

The websocket listener reads the table actually sent to the browser to locate a
real city row. It never sends a websocket message, changes state, or supplies a
result. Selection is a pointer click in that rendered table.
"""
from __future__ import annotations
import argparse
import io
import json
import re
from pathlib import Path
import time
import urllib.request

import pyarrow as pa
from playwright.sync_api import sync_playwright
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from check_workbench_browser import BrowserProbe, wait_new_exploration


class CoreProbe(BrowserProbe):
    def session(self, url):
        context = self.browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        self.contexts.append(context); self.page = context.new_page(); self.finished = 0; self.tables = {}
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        def frame(raw):
            if not isinstance(raw, bytes): return
            message = ForwardMsg()
            try: message.ParseFromString(raw)
            except Exception: return
            if message.WhichOneof("type") == "script_finished" and message.script_finished in (0, 3):
                self.finished += 1
            if message.WhichOneof("type") == "delta" and message.delta.WhichOneof("type") == "new_element":
                element = message.delta.new_element
                if element.WhichOneof("type") == "dataframe":
                    df = element.dataframe
                    if "drilldown_select_" in df.id:
                        rows = pa.ipc.open_stream(df.arrow_data.data).read_all().to_pylist()
                        self.tables[df.id] = {"rows": rows, "row_height": df.row_height or 35}
        self.page.on("websocket", lambda ws: ws.on("framereceived", frame))
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.get_by_role("button", name="开始分析", exact=False).wait_for(timeout=90000)
        self.idle()

    def focus(self, anchor):
        anchor.scroll_into_view_if_needed()
        box = anchor.bounding_box()
        if box and abs(box["y"] - 120) > 3:
            self.page.mouse.move(box["x"] + min(box["width"] / 2, 100), self.page.viewport_size["height"] / 2)
            self.page.mouse.wheel(0, box["y"] - 120)
            self.idle()

    def viewport_checks(self, prefix, anchor=None):
        for width, height in [(1366, 768), (1440, 900), (1024, 768)]:
            self.page.set_viewport_size({"width": width, "height": height})
            if anchor is not None: self.focus(anchor)
            self.capture(f"{prefix}-{width}x{height}")
            if anchor is not None:
                box=anchor.bounding_box()
                self.check(f"{prefix}-{width}x{height}_target_visible", bool(box) and box["y"] >= 60 and box["y"] + box["height"] <= height)

        self.page.set_viewport_size({"width": 1440, "height": 900})

    def manifest(self, prefix):
        self.navigate("报告")
        self.click("生成 运行清单 JSON")
        with self.page.expect_download() as download:
            self.page.get_by_role("button", name="下载 运行清单 JSON", exact=False).click()
        target = self.output / (prefix + ".json"); download.value.save_as(target)
        result = json.loads(target.read_text(encoding="utf8"))
        self.record.setdefault("manifests", {})[prefix] = result
        return result

    def select_west_city(self):
        self.navigate("结论")
        self.page.get_by_text("按城市继续探索", exact=True).scroll_into_view_if_needed()
        table = self.page.locator('[class*="st-key-drilldown_select_"]').locator('[data-testid="stDataFrame"]').first
        table.scroll_into_view_if_needed()
        canvas = table.locator("canvas").first; box = canvas.bounding_box()
        self.check("city_table_rendered", bool(box) and bool(self.tables))
        displayed = list(self.tables.values())[-1]
        self.record["displayed_city_rows"] = displayed["rows"]
        index = next(i for i, row in enumerate(displayed["rows"]) if row["城市"] in {"西城", "West City"} and row["指标"] in {"orders", "订单量"})
        row_height = displayed["row_height"]
        self.action("选择西城订单真实表格行（仅草稿）", lambda: self.page.mouse.click(box["x"] + 16, box["y"] + 36 + row_height * (index + .5)))
        self.check("city_draft_only", "尚未执行" in self.body() and ("West City" in self.body() or "西城" in self.body()))
        self.capture("03-city-selection")
        label = self.page.locator('.st-key-workbench_drilldown_submit button').inner_text().strip()
        self.click(label)
        wait_new_exploration(self)


def workflow(p, baseline):
    p.check("four_main_pages", all(p.page.get_by_text(x, exact=True).count() for x in ["分析工作台", "数据探索", "分析方法", "历史比较"]))
    p.viewport_checks("01-home", p.page.get_by_role("button", name="开始分析", exact=False))
    p.question("昨日订单量为什么下降？")
    p.navigate("分析方法")
    labels = p.page.get_by_role("button", name="配置：").all_text_contents()
    p.record["method_labels"] = labels; p.check("all_ten_methods", len(labels) == 10)
    p.click("配置：轻量因果探索")
    p.check("causal_configuration_reachable", p.page.get_by_role("combobox", name="处理字段", exact=True).count() == 1)
    p.check("invalid_causal_blocked", not p.page.get_by_role("button", name="开始分析", exact=False).is_enabled())
    p.click("改用推荐方法")
    p.click("开始分析")
    result_heading = "执行摘要" if baseline else "发生了什么"
    p.page.get_by_text(result_heading, exact=True).wait_for(timeout=90000); p.idle()
    p.check("order_completed", all(text in p.body() for text in ["订单量", "772", "54.9%", result_heading]))
    p.viewport_checks("02-order", p.page.get_by_text(result_heading, exact=True))
    if not baseline:
        parent_scope = p.page.locator(".st-key-core_analysis_context").inner_text()
        p.record["parent_context_text"] = parent_scope
        p.check("parent_scope_actual_date", "2026-06-30" in parent_scope and "未记录，不能按电脑日期推定" not in parent_scope)
    parent = p.manifest("parent-manifest")
    p.select_west_city()
    p.page.get_by_text("已生成探索结果", exact=True).scroll_into_view_if_needed()
    p.viewport_checks("04-child", p.page.get_by_text("已生成探索结果", exact=True))
    child_text = p.body()
    p.record["child_result_text"] = child_text
    p.check("west_city_orders_208", bool(re.search(r"全范围 订单量\s+208(?:\s|$)", child_text)))
    p.check("west_city_observation_rows_38", bool(re.search(r"当前范围观测行数\s+38(?:\s|$)", child_text)))
    child = p.manifest("child-manifest")
    p.check("child_has_new_identity", child["run_id"] != parent["run_id"])
    p.record["parent_run_id"] = parent["run_id"]; p.record["child_run_id"] = child["run_id"]
    p.navigate("结论")
    if baseline:
        p.check("baseline_missing_result_parent_return", p.page.get_by_role("button", name="返回上一级分析", exact=True).count() == 0)
        p.navigate("历史比较"); p.click("返回上一步")
        p.check("baseline_old_history_returns_released_parent", parent["run_id"] in p.body() and "已释放" in p.body())
        p.capture("05-baseline-history-only-return")
        return
    context = p.page.locator(".st-key-core_analysis_context")
    scope = context.inner_text()
    p.record["child_context_text"] = scope
    p.check("child_scope_actual", all(text in scope for text in ["整体订单诊断", "西城当日探索", "2026-06-30", "描述性", "daily_metrics", "订单量"]))
    back = p.page.get_by_role("button", name="返回上一级分析", exact=True)
    p.check("result_parent_return_discoverable", back.count() == 1)
    p.viewport_checks("05-return-entry", context)
    unit = p.page.get_by_role("textbox", name="指标单位", exact=True)
    unsubmitted_unit = "未提交单位草稿-20261008"
    unit.fill(unsubmitted_unit); unit.press("Tab")
    p.check("unsubmitted_exploration_draft_entered", unit.input_value() == unsubmitted_unit)
    p.focus(unit); p.capture("05b-unsubmitted-exploration-draft")
    p.click("返回上一级分析")
    unit = p.page.get_by_role("textbox", name="指标单位", exact=True)
    p.check("return_keeps_exploration_form_draft", unit.count() == 1 and unit.input_value() == unsubmitted_unit)
    p.check("released_summary_visible", "完整结果已释放" in p.body() and "尚未重新计算" in p.body())
    p.check("child_results_not_under_parent", not p.page.get_by_text("已生成探索结果", exact=True).count())
    p.check("no_parent_pdf_from_child", p.page.get_by_role("button", name="生成 PDF 报告", exact=True).count() == 0)
    p.viewport_checks("06-parent-summary", p.page.get_by_role("button", name="恢复该分析配置", exact=True))
    p.click("恢复该分析配置")
    p.check("exploration_restore_describes_overwrite", "恢复将覆盖当前问题、方法、字段映射和参数草稿" in p.body())
    p.click("保留当前草稿")
    p.check("restore_cancel_keeps_unsubmitted_exploration_draft", p.page.get_by_role("textbox", name="指标单位", exact=True).input_value() == unsubmitted_unit)
    p.click("恢复该分析配置")
    p.click("确认恢复配置")
    p.check("explicit_restore_opens_parent_workbench", p.page.get_by_role("textbox", name="你想分析什么？", exact=True).input_value() == "昨日订单量为什么下降？")
    draft_text = "保留这份尚未执行的订单分析草稿"
    p.question(draft_text)
    p.click("恢复该分析配置")
    p.check("restore_describes_overwrite", "恢复将覆盖当前问题、方法、字段映射和参数草稿" in p.body())
    p.click("保留当前草稿")
    p.check("cancel_preserves_draft", p.page.get_by_role("textbox", name="你想分析什么？", exact=True).input_value() == draft_text)
    p.click("恢复该分析配置")
    p.click("确认恢复配置")
    p.check("restores_parent_question", p.page.get_by_role("textbox", name="你想分析什么？", exact=True).input_value() == "昨日订单量为什么下降？")
    p.check("restore_does_not_show_new_result", "完整结果已释放" in p.body())
    rerun = p.page.locator(".st-key-guided_run button")
    p.check("explicit_rerun_ready", rerun.count() == 1 and "重新运行该分析" in rerun.inner_text() and rerun.is_enabled())
    p.viewport_checks("07-explicit-rerun", rerun)
    p.click("重新运行该分析")
    p.page.get_by_text("发生了什么", exact=True).wait_for(timeout=90000); p.idle()
    p.check("rerun_order_result", all(text in p.body() for text in ["订单量", "772", "54.9%"]))
    refreshed = p.manifest("restored-manifest")
    p.check("rerun_new_identity", refreshed["run_id"] not in {parent["run_id"], child["run_id"]})
    p.check("six_export_formats_remain", all(p.page.get_by_role("button", name=x, exact=True).count() for x in ["生成 PDF 报告", "生成 Markdown 报告", "生成 HTML 报告", "生成 Excel 报告", "生成 运行清单 JSON", "生成 ZIP 报告包"]))
    p.check("pdf_not_pregenerated", p.page.get_by_role("button", name="下载 PDF 报告", exact=False).count() == 0)
    p.click("生成 PDF 报告")
    with p.page.expect_download() as download:
        p.page.get_by_role("button", name="下载 PDF 报告", exact=False).click()
    path = p.output / "restored-parent.pdf"; download.value.save_as(path)
    from pypdf import PdfReader
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    p.check("pdf_matches_selected_new_run", refreshed["run_id"] in pdf_text and child["run_id"] not in pdf_text)
    p.record["final_pdf_text"] = pdf_text
    p.record["final_run_id"] = refreshed["run_id"]
    p.capture("08-report")


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--url",required=True); parser.add_argument("--output",type=Path,required=True); parser.add_argument("--baseline",action="store_true")
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    record={"url":args.url,"baseline":args.baseline,"checks":{},"operations":[],"health_status":urllib.request.urlopen(args.url+"/_stcore/health").status,"method":"Actual headless installed Chrome, separate Playwright context, native controls and rendered city table pointer; read-only websocket observation; no session_state or result injection."}
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",headless=True,chromium_sandbox=True)
        record["chrome"]=browser.version; probe=CoreProbe(browser,args.output,record)
        try:
            probe.session(args.url); workflow(probe,args.baseline)
            record["page_errors"]=probe.errors; probe.check("no_browser_page_errors",not probe.errors)
            record["complete_chain_passed"]=True
        except Exception as exc:
            record["error"]=str(exc); record["complete_chain_passed"]=False
            if probe.page is not None:
                record["failure_body"]=probe.body()
                probe.page.screenshot(path=str(args.output/"failure.png"),full_page=True)
            raise
        finally:
            (args.output/"checks.json").write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf8")
            probe.close(); browser.close()
    print(json.dumps(record["checks"],ensure_ascii=False)); return 0

if __name__=="__main__": raise SystemExit(main())
