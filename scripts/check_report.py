#!/usr/bin/env python3
"""检查一份汇报（周报/月报/项目汇报）是否像"决策请求"而不是流水账。

用法：
    python scripts/check_report.py report.md
    python scripts/check_report.py report.md --strict
    python scripts/check_report.py report.md --json

检查项：结论是否在前 3 行、成果条是否有数字、句首弱动词、
风险是否带方案与请求、是否超一屏、下周计划是否带日期。

退出码：0 正常；--strict 下存在严重问题时为 1；文件错误 2。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WEAK_LEAD = ["负责", "参与", "配合", "跟进", "推进", "对接", "沟通", "协助", "支持", "了解", "学习"]
CONCLUSION_WORDS = ["进度", "达成", "风险", "需要", "建议", "结论", "完成", "%", "延", "上线"]
NUMBER_RE = re.compile(r"\d")
DATE_RE = re.compile(r"\d{1,2}\s*[/月.-]\s*\d{1,2}|周[一二三四五六日天]|下周|本周|月底|季度|Q[1-4]|\d+\s*天")
RISK_SOLUTION = ["方案", "建议", "需要", "备选", "我倾向", "改成", "否则", "决", "请确认", "最晚"]

ONE_SCREEN_LINES = 40


def lines_of(text: str) -> list[str]:
    return [l.rstrip() for l in text.splitlines()]


def is_item(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r"^(?:[-*•·]|\d+[.、)]|[（(]\d+[)）])\s*\S", s))


def item_body(line: str) -> str:
    return re.sub(r"^(?:[-*•·]|\d+[.、)]|[（(]\d+[）)])\s*", "", line.strip())


def analyze(text: str) -> dict:
    lines = lines_of(text)
    nonempty = [l for l in lines if l.strip()]

    # 1. 结论是否在前 3 行：必须同时有「结论词」和「数字」，否则「跟进了开发进度」会被误判成结论
    head = " ".join(nonempty[:3])
    conclusion_ok = any(w in head for w in CONCLUSION_WORDS) and bool(NUMBER_RE.search(head))

    # 2. 成果条
    items = [l for l in lines if is_item(l)]
    no_number = [item_body(i) for i in items if not NUMBER_RE.search(item_body(i))]

    # 3. 句首弱动词
    weak = []
    for l in items:
        body = item_body(l)
        for w in WEAK_LEAD:
            if body.startswith(w):
                weak.append(body[:60])
                break

    # 4. 风险是否带方案
    risk_lines = [l for l in lines if "风险" in l and l.strip() and not l.strip().startswith("#")]
    risk_no_solution = [l.strip()[:70] for l in risk_lines
                        if not any(w in l for w in RISK_SOLUTION)]

    # 5. 长度
    too_long = len(nonempty) > ONE_SCREEN_LINES

    # 6. 下周计划是否有日期
    plan_idx = [i for i, l in enumerate(lines) if re.search(r"下周|下月|计划|规划", l)]
    plan_without_date = False
    if plan_idx:
        tail = " ".join(lines[plan_idx[0]:])
        plan_without_date = not bool(DATE_RE.search(tail))

    critical = []
    if not conclusion_ok:
        critical.append("前 3 行没有结论句（要写清：进度 / 指标 / 风险 / 需要什么决定）")
    if no_number:
        critical.append(f"{len(no_number)} 条成果没有数字")
    if risk_no_solution:
        critical.append(f"{len(risk_no_solution)} 条风险只报了问题、没给方案与请求")

    score = 100
    score -= 0 if conclusion_ok else 25
    score -= min(25, len(no_number) * 8)
    score -= min(20, len(weak) * 6)
    score -= min(20, len(risk_no_solution) * 10)
    score -= 5 if too_long else 0
    score -= 5 if plan_without_date else 0
    score = max(0, score)

    return {
        "conclusion_in_first_3_lines": conclusion_ok,
        "item_count": len(items),
        "items_without_number": no_number[:8],
        "weak_lead_items": weak[:8],
        "risk_lines": len(risk_lines),
        "risk_without_solution": risk_no_solution[:5],
        "nonempty_lines": len(nonempty),
        "too_long": too_long,
        "plan_without_date": plan_without_date,
        "critical": critical,
        "score": score,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="检查汇报质量")
    ap.add_argument("file", help="汇报文本/Markdown 文件")
    ap.add_argument("--strict", action="store_true", help="存在严重问题时退出码 1")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    p = Path(args.file)
    if not p.is_file():
        print(f"找不到文件：{p}", file=sys.stderr)
        return 2

    r = analyze(p.read_text(encoding="utf-8-sig"))

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"结论在前 3 行：{'是' if r['conclusion_in_first_3_lines'] else '否'}")
        print(f"条目数        ：{r['item_count']}（无数字 {len(r['items_without_number'])} 条）")
        print(f"弱动词开头    ：{len(r['weak_lead_items'])} 条")
        print(f"风险条        ：{r['risk_lines']}（缺方案与请求 {len(r['risk_without_solution'])} 条）")
        print(f"篇幅          ：{r['nonempty_lines']} 行{'（超过一屏）' if r['too_long'] else ''}")
        print(f"评分          ：{r['score']}/100")

        if r["critical"]:
            print("\n必须改：")
            for c in r["critical"]:
                print(f"  - {c}")
        if r["items_without_number"]:
            print("\n无数字的条目（补规模/比例/时长/金额/频次）：")
            for s in r["items_without_number"]:
                print(f"  - {s}")
        if r["weak_lead_items"]:
            print("\n弱动词开头（换成产物型动词）：")
            for s in r["weak_lead_items"]:
                print(f"  - {s}")
        if r["risk_without_solution"]:
            print("\n风险缺方案（补：影响 + 方案与代价 + 需要谁决定 + 最晚何时）：")
            for s in r["risk_without_solution"]:
                print(f"  - {s}")
        if r["plan_without_date"]:
            print("\n提示：计划里没有日期。每条带「{日期} 前交付 {产物}」。")

    if args.strict and r["critical"]:
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))
