# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config import GAMES, GAME_MAP, PROBABILITY_NOTES
from models import Draw, GameRecommendation

CN_TZ = timezone(timedelta(hours=8))


def fmt_nums(nums: list[int], width: int = 2) -> str:
    return " ".join(f"{n:0{width}d}" for n in nums)


def fmt_draw(game_key: str, d: Draw | None) -> str:
    if d is None:
        return "-"
    g = GAME_MAP[game_key]
    if g.kind == "digit":
        text = fmt_nums(d.numbers, 1)
        if d.extra:
            text += " + " + fmt_nums(d.extra, 2)
        return text
    text = fmt_nums(d.numbers)
    if d.extra:
        text += " + " + fmt_nums(d.extra)
    return text


def group_reference(rec: GameRecommendation) -> str:
    """仅对 3 位数玩法给出组选参考（按升序展示，实际包含所有排列）。"""
    if rec.game not in ("fc3d", "pl3"):
        return ""
    out, seen = [], set()
    for s in rec.sets:
        key = tuple(sorted(s.numbers))
        if key in seen:
            continue
        seen.add(key)
        kind = "豹子" if len(set(key)) == 1 else ("组三" if len(set(key)) == 2 else "组六")
        out.append(f"{''.join(str(x) for x in key)}（{kind}）")
    return "、".join(out)


def fmt_money(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:,.0f}"


def build_stats(draws_by_game: dict[str, list[Draw]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for g in GAMES:
        draws = draws_by_game.get(g.key, [])
        if not draws:
            continue
        hs = [sum(d.numbers) for d in draws[-300:]]
        spans = [max(d.numbers) - min(d.numbers) for d in draws[-300:] if d.numbers]
        freq: dict[int, int] = {}
        for d in draws[-100:]:
            for n in d.numbers:
                freq[n] = freq.get(n, 0) + 1
        top = sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:10]
        out[g.key] = {
            "sample": len(draws),
            "avg_sum": mean(hs) if hs else 0,
            "std_sum": pstdev(hs) if len(hs) > 1 else 0,
            "avg_span": mean(spans) if spans else 0,
            "top": top,
        }
    return out


def build_markdown(run_date: str, recs: list[GameRecommendation],
                   stats: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"# 彩票数据日报（{run_date}）")
    lines.append("")
    lines.append("> 本报告由历史数据统计生成，仅用于概率学习与娱乐参考，**不提高任何一注的中奖概率**。")
    lines.append("")
    lines.append("## 一、最新开奖")
    lines.append("")
    lines.append("| 玩法 | 期号 | 开奖日期 | 开奖号码 | 销售额(元) | 奖池(元) |")
    lines.append("|---|---|---|---|---:|---:|")
    for rec in recs:
        d = rec.latest
        g = GAME_MAP[rec.game]
        lines.append(
            f"| {g.name} | {d.issue if d else '-'} | {d.draw_date if d else '-'} | "
            f"{fmt_draw(g.key, d)} | {fmt_money(d.sales if d else None)} | {fmt_money(d.pool if d else None)} |"
        )
    lines.append("")

    lines.append("## 二、下一期号码参考")
    lines.append("")
    lines.append("> 每期 5 组，按组合规则筛选排序；不改变任何一注的理论中奖概率。")
    lines.append("")
    for rec in recs:
        g = GAME_MAP[rec.game]
        date_part = f" / 下一期开奖日期 {rec.target_date}" if rec.target_date else ""
        lines.append(f"### {g.name}（第 {rec.target_issue} 期{date_part}）")
        lines.append("")
        lines.append("| # | 推荐号码 | 简要依据 |")
        lines.append("|---:|---|---|")
        for i, s in enumerate(rec.sets, 1):
            nums = fmt_draw(g.key, Draw(rec.game, rec.target_issue, "", s.numbers, s.extra))
            lines.append(f"| {i} | {nums} | {s.rationale} |")
        lines.append("")
        grp = group_reference(rec)
        if grp:
            lines.append(f"**组选参考**：{grp}。组选按升序展示，实际投注包含该组合的所有排列。")
            lines.append("")

    lines.append("## 三、概率速查")
    lines.append("")
    lines.append("| 玩法 | 头奖概率 | 其他奖级 | 理论返奖率 |")
    lines.append("|---|---|---|---|")
    for g in GAMES:
        p = PROBABILITY_NOTES[g.key]
        lines.append(f"| {g.name} | {p['top']} | {p['second']} | {p['return']} |")
    lines.append("")

    lines.append("## 四、历史样本统计")
    lines.append("")
    lines.append("| 玩法 | 样本期数 | 近300期平均和值 | 和值标准差 | 平均跨度 | 近100期热号Top10 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for g in GAMES:
        st = stats.get(g.key)
        if not st:
            continue
        top = "、".join(f"{n:02d}({c})" for n, c in st["top"])
        lines.append(f"| {g.name} | {st['sample']} | {st['avg_sum']:.1f} | {st['std_sum']:.1f} | "
                     f"{st['avg_span']:.1f} | {top} |")
    lines.append("")
    lines.append("## 五、模型逻辑")
    lines.append("")
    lines.append("- 乐透型：近30/100/300期频率、当前遗漏/历史平均间隔、奇偶、大小、三区分布、和值区间、连号与上期重号约束；双色球、大乐透前区强制至少一个>31的号，避开生日型组合。")
    lines.append("- 数字型：按百/十/个位分别统计近30/100期频率与遗漏，约束和值、跨度、奇偶，并要求推荐组合之间至少两位不同。")
    lines.append("- 快乐8：按8个区（每区10个号）约束覆盖与密度，兼顾频率、遗漏、奇偶和组合和值。")
    lines.append("- 所有评分只描述历史结构与组合形态，不构成对下一期开奖的预测。")
    lines.append("")
    return "\n".join(lines)


HTML_CSS = """
body { margin: 0; background: #f3f6fa; color: #1d2b3a;
       font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 28px 20px 60px; }
.hero { background: linear-gradient(135deg, #17324d, #2b5b84); color: #fff;
        border-radius: 16px; padding: 26px 30px; box-shadow: 0 10px 26px rgba(23,50,77,.18); }
.hero h1 { margin: 0 0 8px; font-size: 26px; letter-spacing: 1px; }
.hero p { margin: 4px 0; color: #dbe8f5; font-size: 13px; }
.badge { display: inline-block; background: #ffd166; color: #5a3d00; font-size: 12px;
         font-weight: 700; padding: 4px 10px; border-radius: 999px; margin-bottom: 10px; }
.card { background: #fff; border-radius: 14px; padding: 20px 22px; margin-top: 18px;
        box-shadow: 0 4px 16px rgba(31,58,95,.06); }
h2 { font-size: 19px; margin: 0 0 14px; color: #17324d; border-left: 4px solid #2b5b84;
     padding-left: 10px; }
h3 { font-size: 16px; margin: 18px 0 8px; color: #1f4a73; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { background: #eaf1f8; color: #17324d; text-align: left; padding: 9px 10px;
     border-bottom: 1px solid #d6e2ef; white-space: nowrap; }
td { padding: 8px 10px; border-bottom: 1px solid #eef3f8; vertical-align: top; }
tr:nth-child(even) td { background: #fbfdff; }
.num { font-family: Consolas, "Courier New", monospace; font-weight: 700; color: #0f4c81;
       white-space: nowrap; }
.note { background: #fff8e6; border: 1px solid #f3dfae; color: #6b4c00;
        border-radius: 10px; padding: 12px 14px; font-size: 13px; line-height: 1.7; }
.small { color: #6b7c90; font-size: 12px; }
.tag { display: inline-block; background: #eef5fb; color: #24557f; border-radius: 6px;
       padding: 2px 7px; font-size: 12px; margin-right: 4px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 16px; }
.foot { text-align: center; color: #8a99aa; font-size: 12px; margin-top: 26px; }
"""


def _esc(v: Any) -> str:
    return html.escape(str(v))


def build_html(run_date: str, recs: list[GameRecommendation],
               stats: dict[str, dict[str, Any]]) -> str:
    parts: list[str] = []
    parts.append("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    parts.append(f"<title>彩票数据日报 {run_date}</title><style>{HTML_CSS}</style></head><body>")
    parts.append("<div class='wrap'>")
    parts.append("<div class='hero'>")
    parts.append("<span class='badge'>仅供娱乐 · 不提高中奖概率</span>")
    parts.append(f"<h1>彩票数据日报 · {run_date}</h1>")
    parts.append("<p>数据源：中国福利彩票网、中国体彩网官方开奖接口</p>")
    parts.append("<p>推荐 = 历史频率 + 遗漏回补 + 结构平衡 + 减少撞号，不是预测。</p>")
    parts.append("</div>")

    parts.append("<div class='card'><h2>一、最新开奖</h2><table>")
    parts.append("<tr><th>玩法</th><th>期号</th><th>开奖日期</th><th>开奖号码</th>"
                 "<th>销售额(元)</th><th>奖池(元)</th></tr>")
    for rec in recs:
        d = rec.latest
        g = GAME_MAP[rec.game]
        parts.append(
            f"<tr><td>{_esc(g.name)}</td><td>{_esc(d.issue if d else '-')}</td>"
            f"<td>{_esc(d.draw_date if d else '-')}</td>"
            f"<td class='num'>{_esc(fmt_draw(g.key, d))}</td>"
            f"<td>{_esc(fmt_money(d.sales if d else None))}</td>"
            f"<td>{_esc(fmt_money(d.pool if d else None))}</td></tr>"
        )
    parts.append("</table></div>")

    parts.append("<div class='card'><h2>二、下一期号码参考</h2>")
    parts.append("<div class='note'>每期 5 组，按组合规则筛选排序；任何号码组合的理论中奖概率相同。 </div>")
    for rec in recs:
        g = GAME_MAP[rec.game]
        date_part = f" · 下一期开奖日期 {rec.target_date}" if rec.target_date else ""
        parts.append(f"<h3>{_esc(g.name)} <span class='small'>第 {_esc(rec.target_issue)} 期{_esc(date_part)} · "
                     f"样本 {rec.sample_size} 期</span></h3><table>")
        parts.append("<tr><th>#</th><th>推荐号码</th><th>简要依据</th></tr>")
        for i, s in enumerate(rec.sets, 1):
            nums = fmt_draw(g.key, Draw(rec.game, rec.target_issue, "", s.numbers, s.extra))
            parts.append(f"<tr><td>{i}</td><td class='num'>{_esc(nums)}</td>"
                         f"<td>{_esc(s.rationale)}</td></tr>")
        parts.append("</table>")
        grp = group_reference(rec)
        if grp:
            parts.append(f"<div class='small' style='margin-top:8px'>组选参考：{_esc(grp)}"
                         "（按升序展示，实际投注包含所有排列）</div>")
    parts.append("</div>")

    parts.append("<div class='card'><h2>三、概率速查</h2><table>")
    parts.append("<tr><th>玩法</th><th>头奖概率</th><th>其他奖级</th><th>理论返奖率</th></tr>")
    for g in GAMES:
        p = PROBABILITY_NOTES[g.key]
        parts.append(f"<tr><td>{_esc(g.name)}</td><td class='num'>{_esc(p['top'])}</td>"
                     f"<td>{_esc(p['second'])}</td><td>{_esc(p['return'])}</td></tr>")
    parts.append("</table></div>")

    parts.append("<div class='card'><h2>四、历史样本统计</h2><table>")
    parts.append("<tr><th>玩法</th><th>样本期数</th><th>近300期平均和值</th><th>和值标准差</th>"
                 "<th>平均跨度</th><th>近100期热号Top10</th></tr>")
    for g in GAMES:
        st = stats.get(g.key)
        if not st:
            continue
        top = "、".join(f"{n:02d}({c})" for n, c in st["top"])
        parts.append(f"<tr><td>{_esc(g.name)}</td><td>{st['sample']}</td>"
                     f"<td>{st['avg_sum']:.1f}</td><td>{st['std_sum']:.1f}</td>"
                     f"<td>{st['avg_span']:.1f}</td><td>{_esc(top)}</td></tr>")
    parts.append("</table></div>")

    parts.append("<div class='card'><h2>五、模型逻辑与边界</h2><div class='note'>"
                 "<b>乐透型：</b>近30/100/300期频率、当前遗漏/历史平均间隔、奇偶、大小、三区分布、"
                 "和值区间、连号与上期重号约束；双色球、大乐透前区强制至少一个>31的号，避开生日型组合。<br>"
                 "<b>数字型：</b>按百/十/个位分别统计近30/100期频率与遗漏，约束和值、跨度、奇偶，"
                 "并要求推荐组合之间至少两位不同。<br>"
                 "<b>快乐8：</b>按8个区（每区10个号）约束覆盖与密度，兼顾频率、遗漏、奇偶和组合和值。<br>"
                 "<b>边界：</b>以上全部是描述性统计。彩票每期独立开奖，历史数据不能预测下一期，"
                 "任何“必中”“内部号”“AI 预测”都不成立。请量力而行，未成年人不得购彩。"
                 "</div></div>")
    parts.append(f"<div class='foot'>生成时间：{_esc(datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S'))} · "
                 "数据来自官方公开接口，仅供学习与娱乐</div>")
    parts.append("</div></body></html>")
    return "".join(parts)


def build_excel(path: str | Path, run_date: str, recs: list[GameRecommendation],
                stats: dict[str, dict[str, Any]]) -> None:
    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="17324D")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    thin = Side(style="thin", color="D6E2EF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    def style_sheet(ws, widths: list[int]) -> None:
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center
            cell.border = border
        ws.freeze_panes = "A2"
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.border = border
                cell.alignment = left
        ws.auto_filter.ref = ws.dimensions

    ws = wb.active
    ws.title = "最新开奖"
    ws.append(["玩法", "期号", "开奖日期", "开奖号码", "销售额(元)", "奖池(元)", "下期期号"])
    for rec in recs:
        d = rec.latest
        g = GAME_MAP[rec.game]
        ws.append([g.name, d.issue if d else "", d.draw_date if d else "",
                   fmt_draw(g.key, d), d.sales if d else None, d.pool if d else None,
                   rec.target_issue])
    style_sheet(ws, [14, 12, 13, 30, 16, 16, 12])

    ws = wb.create_sheet("推荐号码")
    ws.append(["玩法", "下一期期号", "下一期开奖日期", "序号", "推荐号码", "简要依据"])
    for rec in recs:
        g = GAME_MAP[rec.game]
        for i, s in enumerate(rec.sets, 1):
            nums = fmt_draw(g.key, Draw(rec.game, rec.target_issue, "", s.numbers, s.extra))
            ws.append([g.name, rec.target_issue, rec.target_date or "-",
                       i, nums, s.rationale])
    style_sheet(ws, [14, 12, 14, 8, 30, 80])

    ws = wb.create_sheet("概率与期望")
    ws.append(["玩法", "头奖概率", "其他奖级", "理论返奖率", "单注价格(元)", "粗略期望(元/注)"])
    for g in GAMES:
        p = PROBABILITY_NOTES[g.key]
        rate = float(p["return"].replace("约", "").replace("%", "").strip()) / 100
        ev = g.price * rate - g.price
        ws.append([g.name, p["top"], p["second"], p["return"], g.price, round(ev, 2)])
    style_sheet(ws, [14, 34, 42, 14, 14, 18])

    ws = wb.create_sheet("历史统计")
    ws.append(["玩法", "样本期数", "近300期平均和值", "和值标准差", "平均跨度", "近100期热号Top10"])
    for g in GAMES:
        st = stats.get(g.key)
        if not st:
            continue
        top = "、".join(f"{n:02d}({c})" for n, c in st["top"])
        ws.append([g.name, st["sample"], round(st["avg_sum"], 2), round(st["std_sum"], 2),
                   round(st["avg_span"], 2), top])
    style_sheet(ws, [14, 12, 16, 12, 12, 50])

    ws = wb.create_sheet("说明")
    ws.append(["项目", "说明"])
    notes = [
        ("用途", "历史数据统计、组合筛选与概率学习，仅供娱乐参考。"),
        ("核心结论", "彩票每期独立开奖，任何历史统计都不能提高单注中奖概率。"),
        ("乐透模型", "近30/100/300期频率、遗漏回补、奇偶、大小、三区、和值、连号、重号约束。"),
        ("数字模型", "按位置统计频率与遗漏，约束和值、跨度、奇偶，组合间保持差异。"),
        ("快乐8模型", "8区覆盖、频率、遗漏、奇偶、和值综合评分。"),
        ("反热门", "双色球、大乐透前区强制至少一个>31的号；一等奖奖池均分时，可略微减少撞号。"),
        ("期望值", "粗略期望按理论返奖率估算：单注价格 × 返奖率 - 单注价格；实际随奖池和浮动奖金变化。"),
        ("下一期日期", "按开奖规律和休市日历计算，节假日以休市安排为准。"),
        ("风险提示", "未成年人不得购彩；请设定预算，不要借贷或追号。"),
        ("数据源", "中国福利彩票网、中国体彩网官方公开接口。"),
    ]
    for k, v in notes:
        ws.append([k, v])
    style_sheet(ws, [14, 100])

    wb.save(path)
