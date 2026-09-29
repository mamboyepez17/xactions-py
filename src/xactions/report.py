"""
XActions-PY — Shareable reports (Markdown / HTML).

No extra deps: stdlib only.
"""

from __future__ import annotations

import html
import math
from datetime import datetime, timezone
from typing import Any

from .analyzer import analyze_tweets, compare_accounts


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(n: Any) -> str:
    if n is None:
        return "—"
    try:
        return f"{float(n):.4f}%"
    except (TypeError, ValueError):
        return str(n)


def _tweet_rows_md(tweets: list[dict[str, Any]], limit: int = 10) -> str:
    rows = []
    for t in tweets[:limit]:
        text = (t.get("text") or "").replace("\n", " ")[:100]
        rows.append(
            f"| {t.get('id', '')} | {text} | {_fmt_int(t.get('likes'))} | "
            f"{_fmt_int(t.get('retweets'))} | {_fmt_int(t.get('views'))} |"
        )
    header = "| ID | Text | Likes | RTs | Views |\n|---|---|---:|---:|---:|"
    if not rows:
        return "_No tweets._"
    return header + "\n" + "\n".join(rows)


def render_account_report_md(
    profile: dict[str, Any],
    tweets: list[dict[str, Any]],
    *,
    title: str | None = None,
) -> str:
    """Markdown report for one account."""
    report = analyze_tweets(tweets, profile=profile)
    username = profile.get("username") or "unknown"
    title = title or f"X report — @{username}"
    avg = report.get("averages") or {}
    content = report.get("content") or {}
    lines = [
        f"# {title}",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "## Profile",
        "",
        f"- **@{username}** — {profile.get('name') or ''}",
        f"- Followers: **{_fmt_int(profile.get('followers'))}** · Following: {_fmt_int(profile.get('following'))}",
        f"- Tweets (account): {_fmt_int(profile.get('tweets_count'))}",
        f"- Verified: {'yes' if profile.get('verified') else 'no'}",
        f"- Bio: {(profile.get('bio') or '—').replace(chr(10), ' ')[:200]}",
        "",
        "## Engagement (sample)",
        "",
        f"- Tweets analyzed: **{report.get('total_tweets', 0)}**",
        f"- Avg likes: {_fmt_int(avg.get('likes'))} · RTs: {_fmt_int(avg.get('retweets'))} · "
        f"replies: {_fmt_int(avg.get('replies'))} · views: {_fmt_int(avg.get('views'))}",
        f"- Engagement rate (followers): **{_fmt_pct(report.get('engagement_rate_followers'))}**",
        f"- Engagement rate (views): {_fmt_pct(report.get('engagement_rate_views'))}",
        f"- With media: {content.get('with_media_pct', 0)}% · replies: {content.get('replies_pct', 0)}%",
        "",
    ]
    if report.get("best_hours"):
        hours = ", ".join(f"{h['hour']:02d}:00" for h in report["best_hours"])
        lines += [f"- Best hours (UTC): {hours}", ""]
    if report.get("top_tweets"):
        lines += ["## Top tweets", "", _tweet_rows_md(report["top_tweets"], 5), ""]
    if tweets:
        lines += ["## Recent sample", "", _tweet_rows_md(tweets, 10), ""]
    return "\n".join(lines)


def render_compare_report_md(
    profile_a: dict[str, Any],
    tweets_a: list[dict[str, Any]],
    profile_b: dict[str, Any],
    tweets_b: list[dict[str, Any]],
) -> str:
    cmp = compare_accounts(profile_a, tweets_a, profile_b, tweets_b)
    a, b = cmp["a"], cmp["b"]
    w = cmp.get("winner") or {}
    lines = [
        f"# Comparison @{a.get('username')} vs @{b.get('username')}",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"| Metric | @{a.get('username')} | @{b.get('username')} |",
        "|---|---:|---:|",
        f"| Followers | {_fmt_int(a.get('followers'))} | {_fmt_int(b.get('followers'))} |",
        f"| Avg likes | {_fmt_int((a.get('averages') or {}).get('likes'))} | {_fmt_int((b.get('averages') or {}).get('likes'))} |",
        f"| ER followers | {_fmt_pct(a.get('engagement_rate_followers'))} | {_fmt_pct(b.get('engagement_rate_followers'))} |",
        "",
        f"**Winners:** followers=`{w.get('followers')}` · ER=`{w.get('engagement_rate_followers')}` · likes=`{w.get('avg_likes')}`",
        "",
    ]
    return "\n".join(lines)


def _nice_ticks(lo: float, hi: float, target: int = 4) -> list[float]:
    """Round axis ticks (1/2/5 × 10^k steps) covering [lo, hi]."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks = []
    t = start
    while t <= hi + step * 0.5:
        ticks.append(t)
        t += step
    return ticks


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def render_follower_chart_svg(history: list[dict[str, Any]], *, width: int = 720, height: int = 240) -> str:
    """
    Inline SVG line chart of followers over time from TrackerDB profile
    snapshots (any order). Returns "" with fewer than two usable points.
    Colors come from the report's CSS custom properties (light/dark aware).
    """
    points = []
    for row in history:
        ts = _parse_ts(str(row.get("captured_at") or ""))
        if ts is not None and row.get("followers") is not None:
            points.append((ts, int(row["followers"])))
    points.sort()
    if len(points) < 2:
        return ""

    left, right, top, bottom = 64, 88, 16, 32
    plot_w, plot_h = width - left - right, height - top - bottom
    t0, t1 = points[0][0].timestamp(), points[-1][0].timestamp()
    values = [v for _, v in points]
    ticks = _nice_ticks(min(values), max(values))
    y_lo, y_hi = ticks[0], ticks[-1]

    def x(ts: datetime) -> float:
        return left + (plot_w * (ts.timestamp() - t0) / (t1 - t0) if t1 > t0 else plot_w / 2)

    def y(v: float) -> float:
        return top + plot_h * (1 - (v - y_lo) / (y_hi - y_lo))

    parts = [
        f'<svg class="viz" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Followers from {points[0][1]:,} to {points[-1][1]:,}">'
    ]
    for t in ticks:  # recessive hairline grid + clean tick labels
        ty = y(t)
        parts.append(f'<line class="grid" x1="{left}" x2="{left + plot_w}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{ty + 4:.1f}" text-anchor="end">{int(t):,}</text>')
    for ts, anchor in ((points[0][0], "start"), (points[-1][0], "end")):
        parts.append(
            f'<text class="tick" x="{x(ts):.1f}" y="{height - 8}" text-anchor="{anchor}">{ts:%Y-%m-%d}</text>'
        )
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(ts):.1f},{y(v):.1f}" for i, (ts, v) in enumerate(points))
    parts.append(f'<path class="line" d="{path}"/>')
    for ts, v in points:  # generous invisible hit targets carry the tooltip
        parts.append(
            f'<circle class="hit" cx="{x(ts):.1f}" cy="{y(v):.1f}" r="10">'
            f"<title>{ts:%Y-%m-%d %H:%M} UTC — {v:,} followers</title></circle>"
        )
    last_ts, last_v = points[-1]
    parts.append(f'<circle class="end" cx="{x(last_ts):.1f}" cy="{y(last_v):.1f}" r="4"/>')
    parts.append(
        f'<text class="label" x="{x(last_ts) + 10:.1f}" y="{y(last_v) + 4:.1f}">{last_v:,}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def render_follower_history_html(history: list[dict[str, Any]]) -> str:
    """Chart + table view of follower snapshots, or "" if there is too little data."""
    svg = render_follower_chart_svg(history)
    if not svg:
        return ""
    rows = sorted(history, key=lambda r: str(r.get("captured_at") or ""), reverse=True)
    body = "".join(
        f"<tr><td>{html.escape(str(r.get('captured_at') or ''))}</td>"
        f"<td class='num'>{_fmt_int(r.get('followers'))}</td>"
        f"<td class='num'>{_fmt_int(r.get('following'))}</td>"
        f"<td class='num'>{_fmt_int(r.get('tweets_count'))}</td></tr>"
        for r in rows
    )
    return (
        "<h2>Follower history</h2>\n"
        f"{svg}\n"
        "<details><summary>Snapshot table</summary><table>"
        "<tr><th>Captured (UTC)</th><th>Followers</th><th>Following</th><th>Tweets</th></tr>"
        f"{body}</table></details>\n"
    )


_PAGE_CSS = (
    ":root{color-scheme:light;--surface:#fcfcfb;--text:#0b0b0b;--muted:#52514e;"
    "--rule:#e4e3df;--head:#f3f2ef;--series-1:#2a78d6}"
    "@media (prefers-color-scheme:dark){:root{color-scheme:dark;--surface:#1a1a19;--text:#fff;"
    "--muted:#c3c2b7;--rule:#34332f;--head:#252523;--series-1:#3987e5}}"
    "body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;line-height:1.5;"
    "background:var(--surface);color:var(--text)}"
    "table{border-collapse:collapse;width:100%}th,td{border:1px solid var(--rule);padding:.4rem .6rem;text-align:left}"
    "th{background:var(--head)}td.num{text-align:right;font-variant-numeric:tabular-nums}"
    "svg.viz{width:100%;height:auto;display:block;margin:.5rem 0}"
    ".viz .grid{stroke:var(--rule);stroke-width:1}"
    ".viz .tick{fill:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}"
    ".viz .label{fill:var(--text);font-size:12px;font-weight:600;font-variant-numeric:tabular-nums}"
    ".viz .line{fill:none;stroke:var(--series-1);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}"
    ".viz .end{fill:var(--series-1);stroke:var(--surface);stroke-width:2}"
    ".viz .hit{fill:transparent}"
    "summary{cursor:pointer;color:var(--muted);margin:.5rem 0}"
)


def _md_to_simple_html(md_text: str, title: str, extra_html: str = "") -> str:
    """Minimal MD→HTML for headings, lists, tables, bold. Good enough for sharing."""
    lines_out: list[str] = []
    in_table = False
    in_list = False

    def close_lists():
        nonlocal in_list, in_table
        if in_list:
            lines_out.append("</ul>")
            in_list = False
        if in_table:
            lines_out.append("</table>")
            in_table = False

    for raw in md_text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_lists()
            lines_out.append("")
            continue
        if line.startswith("# "):
            close_lists()
            lines_out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            close_lists()
            lines_out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("_") and line.endswith("_") and len(line) > 2:
            close_lists()
            lines_out.append(f"<p><em>{html.escape(line.strip('_'))}</em></p>")
        elif line.startswith("- "):
            if not in_list:
                close_lists()
                lines_out.append("<ul>")
                in_list = True
            content = line[2:]
            content = _inline_bold(content)
            lines_out.append(f"<li>{content}</li>")
        elif line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # separator
            if not in_table:
                if in_list:
                    lines_out.append("</ul>")
                    in_list = False
                lines_out.append("<table>")
                in_table = True
                tag = "th"
            else:
                tag = "td"
            tds = "".join(f"<{tag}>{_inline_bold(c)}</{tag}>" for c in cells)
            lines_out.append(f"<tr>{tds}</tr>")
        else:
            close_lists()
            lines_out.append(f"<p>{_inline_bold(line)}</p>")
    close_lists()
    body = "\n".join(lines_out)
    return (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        f"<style>{_PAGE_CSS}</style></head><body>\n"
        f"{body}\n{extra_html}</body></html>\n"
    )


def _inline_bold(text: str) -> str:
    import re

    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def render_account_report_html(
    profile: dict[str, Any],
    tweets: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
) -> str:
    """HTML report; `history` (TrackerDB profile snapshots) adds a follower chart."""
    md = render_account_report_md(profile, tweets)
    username = profile.get("username") or "account"
    return _md_to_simple_html(md, f"X report @{username}", render_follower_history_html(history or []))


def render_compare_report_html(
    profile_a: dict[str, Any],
    tweets_a: list[dict[str, Any]],
    profile_b: dict[str, Any],
    tweets_b: list[dict[str, Any]],
) -> str:
    md = render_compare_report_md(profile_a, tweets_a, profile_b, tweets_b)
    return _md_to_simple_html(
        md,
        f"Compare @{profile_a.get('username')} vs @{profile_b.get('username')}",
    )
