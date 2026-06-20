import math
from datetime import date, timedelta
from html import escape
from typing import Iterator


# How strongly leverage (days off per day spent) is rewarded relative to raw
# magnitude. 1.0 = balanced; >1 pushes brute-force "spend everything for a long
# block" periods down so clever cheap bridges rise to the top.
LEVERAGE_EXP = 1.5


def score_period(
    spent: int, off: int, holidays: int = 0,
    holiday_weight: float = 0.25, leverage_exp: float = LEVERAGE_EXP,
) -> float:
    """
    Interestingness score for a vacation period.

    score = (off - spent) * (off / spent) ** leverage_exp * (1 + holiday_weight * holidays)

    where free = off - spent. This rewards both the magnitude of free days gained
    and the leverage (days off per day spent), so a clever holiday bridge that turns
    3 spent days into 9 off scores far higher than a plain Friday-plus-weekend even
    though both share a 3x ratio. The leverage exponent ensures a high-ratio cheap
    bridge beats a long low-ratio block of the same free-day count, matching the
    intuition that burning your whole budget for one long vacation is less "clever"
    than a well-placed bridge. Holidays absorbed into the block add a further bonus,
    since bridging public holidays is rarer than merely extending a weekend you'd
    get anyway.
    """
    if spent <= 0:
        return 0.0
    free = off - spent
    if free <= 0:
        return 0.0
    return free * (off / spent) ** leverage_exp * (1 + holiday_weight * holidays)


def _count_holidays(timeline: list[dict], start: int, end: int) -> int:
    """Count public-holiday days (non-working, non-weekend) within a period."""
    return sum(
        1
        for i in range(start, end + 1)
        if not timeline[i]["is_working"] and not timeline[i]["is_weekend"]
    )


def _get_year_timeline(year: int, day_types: dict[str, str]) -> tuple[list[dict], int]:
    """
    Build the extended timeline for the year.
    Returns: (timeline_list, year_end_index)
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)
    start_date = max(tomorrow, date(year, 1, 1))
    end_date = date(year, 12, 31)

    if start_date > end_date:
        return [], 0

    timeline = []
    current = start_date
    extended_end = date(year + 1, 1, 10)

    while current <= extended_end:
        day_type = day_types.get(current.isoformat())
        if day_type is None:
            day_type = "NON_WORKING_DAY" if current.weekday() >= 5 else "WORKING_DAY"

        is_working = day_type == "WORKING_DAY"
        timeline.append({
            "date": current,
            "cost": 1 if is_working else 0,
            "type": day_type,
            "is_working": is_working,
            "is_weekend": current.weekday() >= 5,
        })
        current += timedelta(days=1)

    try:
        year_end_idx = next(i for i, d in enumerate(timeline) if d["date"] > end_date)
    except StopIteration:
        year_end_idx = len(timeline)

    return timeline, year_end_idx


def _iter_vacation_periods(
    timeline: list[dict], year_end_idx: int, max_budget: int
) -> Iterator[tuple[int, int, int, int]]:
    """
    Generator that yields unique vacation periods.
    Yields: (vacation_spent, days_off, ext_start_idx, ext_end_idx)
    """
    seen = set()

    for start_idx in range(year_end_idx):
        vacation_spent = 0

        for end_idx in range(start_idx, year_end_idx):
            vacation_spent += timeline[end_idx]["cost"]

            if vacation_spent > max_budget:
                break

            # Extend backwards
            ext_start = start_idx
            while ext_start > 0 and timeline[ext_start - 1]["cost"] == 0:
                ext_start -= 1

            # Extend forwards
            ext_end = end_idx
            while ext_end < len(timeline) - 1 and timeline[ext_end + 1]["cost"] == 0:
                ext_end += 1

            period_key = (ext_start, ext_end)
            if period_key in seen:
                continue

            seen.add(period_key)
            days_off = ext_end - ext_start + 1

            yield vacation_spent, days_off, ext_start, ext_end


def find_vacation_grid(year: int, max_budget: int, day_types: dict[str, str]) -> dict:
    """
    Build a 2D grid of vacation possibilities.
    X axis: days spent (0 to max_budget)
    Y axis: days off (1 to max possible, including adjacent weekends/holidays)
    """
    timeline, year_end_idx = _get_year_timeline(year, day_types)
    if not timeline:
        return {"grid": [], "max_days_off": 0, "max_budget": 0}

    counts = {}
    max_days_off = 0

    for spent, off, _, _ in _iter_vacation_periods(timeline, year_end_idx, max_budget):
        key = (spent, off)
        counts[key] = counts.get(key, 0) + 1
        max_days_off = max(max_days_off, off)

    # Highest interestingness score across all populated cells, used to
    # normalize the heatmap coloring. Computed per (spent, off) without the
    # holiday bonus so a cell's color is deterministic.
    max_score = 0.0
    for spent, off in counts:
        max_score = max(max_score, score_period(spent, off))

    grid = []
    for days_off in range(1, max_days_off + 1):
        row = [counts.get((days_spent, days_off), 0) for days_spent in range(0, max_budget + 1)]
        grid.append(row)

    return {
        "grid": grid,
        "max_days_off": max_days_off,
        "max_budget": max_budget,
        "max_score": max_score,
    }


def find_periods_for_cell(
    year: int, target_spent: int, target_off: int, day_types: dict[str, str]
) -> list[dict]:
    """
    Find all periods matching exact (days_spent, days_off) combination.
    Returns up to 10 periods with day details including 3 context days on each side.
    """
    timeline, year_end_idx = _get_year_timeline(year, day_types)
    if not timeline:
        return []

    matching = []
    context_days = 3

    for spent, off, ext_start, ext_end in _iter_vacation_periods(timeline, year_end_idx, target_spent):
        if spent == target_spent and off == target_off:
            # Include context days before and after
            display_start = max(0, ext_start - context_days)
            display_end = min(len(timeline) - 1, ext_end + context_days)

            days = []
            for i in range(display_start, display_end + 1):
                day = timeline[i]
                in_period = ext_start <= i <= ext_end
                # Calculate fade: 1.0 for period days, decreasing for context
                if in_period:
                    opacity = 1.0
                elif i < ext_start:
                    opacity = 0.25 + 0.25 * (context_days - (ext_start - i)) / context_days
                else:
                    opacity = 0.25 + 0.25 * (context_days - (i - ext_end)) / context_days

                days.append({
                    "date": day["date"],
                    "is_working": day["is_working"],
                    "is_weekend": day["is_weekend"],
                    "day_type": day["type"],
                    "in_period": in_period,
                    "opacity": opacity,
                })

            matching.append({
                "start_date": timeline[ext_start]["date"],
                "end_date": timeline[ext_end]["date"],
                "days": days,
            })

            if len(matching) >= 10:
                break

    return matching


def find_top_opportunities(
    year: int, max_budget: int, day_types: dict[str, str], top_n: int = 6, context_days: int = 2
) -> list[dict]:
    """
    Find the most interesting vacation periods of the year, ranked by score.

    Periods are scored, sorted, then greedily selected so that no two highlighted
    opportunities overlap on the calendar (otherwise the Christmas cluster, say,
    would fill every slot with near-duplicate windows).
    """
    timeline, year_end_idx = _get_year_timeline(year, day_types)
    if not timeline:
        return []

    scored = []
    for spent, off, ext_start, ext_end in _iter_vacation_periods(timeline, year_end_idx, max_budget):
        if spent <= 0:
            continue
        holidays = _count_holidays(timeline, ext_start, ext_end)
        score = score_period(spent, off, holidays)
        if score <= 0:
            continue
        scored.append((score, spent, off, ext_start, ext_end, holidays))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected = []
    used: list[tuple[int, int]] = []
    seen_recipes: set[tuple[int, int]] = set()
    for score, spent, off, ext_start, ext_end, holidays in scored:
        # Show distinct kinds of opportunity: skip a (spent, off) recipe we've
        # already highlighted, and skip windows that overlap a selected one.
        if (spent, off) in seen_recipes:
            continue
        if any(not (ext_end < s or ext_start > e) for s, e in used):
            continue
        seen_recipes.add((spent, off))
        used.append((ext_start, ext_end))

        display_start = max(0, ext_start - context_days)
        display_end = min(len(timeline) - 1, ext_end + context_days)
        days = []
        for i in range(display_start, display_end + 1):
            day = timeline[i]
            in_period = ext_start <= i <= ext_end
            days.append({
                "date": day["date"],
                "is_working": day["is_working"],
                "is_weekend": day["is_weekend"],
                "day_type": day["type"],
                "in_period": in_period,
                "opacity": 1.0 if in_period else 0.35,
            })

        selected.append({
            "start_date": timeline[ext_start]["date"],
            "end_date": timeline[ext_end]["date"],
            "spent": spent,
            "off": off,
            "holidays": holidays,
            "score": score,
            "days": days,
        })

        if len(selected) >= top_n:
            break

    return selected


def _render_day_squares(days: list[dict]) -> str:
    """Render a period's days as colored squares (shared by detail + highlight views)."""
    squares = ""
    for day in days:
        in_period = day.get("in_period", True)
        if day["is_working"]:
            color = "#1976D2" if in_period else "#9E9E9E"
        elif day["is_weekend"]:
            color = "#CE93D8"
        else:
            color = "#81D4FA"

        opacity = day.get("opacity", 1.0)
        title = day["date"].strftime("%d %b %a")
        if in_period and day["is_working"]:
            title += " (vacation)"
        squares += f'<span class="day-sq" style="background:{color};opacity:{opacity:.2f}" title="{title}"></span>'
    return squares


def create_vacation_cell_detail_html(
    year: int, days_spent: int, days_off: int, username: str, hash_value: str, periods: list[dict]
) -> str:
    """Generate HTML page showing periods for a specific cell."""
    rows_html = ""
    for i, p in enumerate(periods, 1):
        start_fmt = p["start_date"].strftime("%d %b")
        end_fmt = p["end_date"].strftime("%d %b")

        squares = _render_day_squares(p["days"])

        rows_html += f"""
            <tr>
                <td>{i}</td>
                <td>{start_fmt} - {end_fmt}</td>
                <td><div class="day-squares">{squares}</div></td>
            </tr>"""

    if not periods:
        rows_html = '<tr><td colspan="3" style="text-align:center;padding:20px;">No periods found</td></tr>'

    ratio_text = f"{days_off / days_spent:.1f}x" if days_spent > 0 else "FREE"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Vacation Periods - {days_spent}d spent, {days_off}d off</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 8px;
            background: white;
            color: #333;
        }}
        h1 {{ font-size: 16px; margin: 0 0 4px 0; color: #1976D2; }}
        p {{ font-size: 12px; color: #666; margin: 0 0 8px 0; }}
        a {{ color: #1976D2; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            font-size: 12px;
        }}
        th, td {{
            padding: 6px 8px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #1976D2;
            color: white;
            font-weight: 500;
        }}
        .day-squares {{
            display: flex;
            gap: 2px;
            flex-wrap: wrap;
        }}
        .day-sq {{
            width: 14px;
            height: 14px;
            border-radius: 2px;
            display: inline-block;
        }}
        .legend {{
            display: flex;
            gap: 12px;
            margin: 8px 0;
            font-size: 10px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .legend-box {{
            width: 12px;
            height: 12px;
            border-radius: 2px;
        }}
        .back {{ margin-bottom: 8px; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="back"><a href="/vacation-grid?year={year}&username={escape(username)}&hash={escape(hash_value)}">&larr; Back to grid</a></div>
    <h1>Spend {days_spent} days, get {days_off} days off ({ratio_text})</h1>
    <p>Showing up to 10 matching periods for {year}</p>

    <div class="legend">
        <div class="legend-item"><div class="legend-box" style="background:#1976D2"></div> Vacation day</div>
        <div class="legend-item"><div class="legend-box" style="background:#9E9E9E"></div> Working day</div>
        <div class="legend-item"><div class="legend-box" style="background:#CE93D8"></div> Weekend</div>
        <div class="legend-item"><div class="legend-box" style="background:#81D4FA"></div> Holiday</div>
    </div>

    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Period</th>
                <th>Days</th>
            </tr>
        </thead>
        <tbody>{rows_html}
        </tbody>
    </table>
</body>
</html>"""

    return html


def create_vacation_grid_html(
    year: int, budget: int, username: str, hash_value: str, grid_data: dict,
    opportunities: list[dict] | None = None
) -> str:
    """Generate HTML page displaying vacation grid."""
    grid = grid_data["grid"]
    max_days_off = grid_data["max_days_off"]
    max_budget = grid_data["max_budget"]
    max_score = grid_data.get("max_score", 0.0)
    opportunities = opportunities or []

    def score_to_color(score: float) -> tuple[str, str]:
        """Convert interestingness score to a heatmap color (log-normalized)."""
        if max_score <= 0 or score <= 0:
            return "hsl(30, 70%, 45%)", "white"
        t = math.log1p(score) / math.log1p(max_score)
        hue = 30 + t * (210 - 30)
        return f"hsl({hue:.0f}, 70%, 45%)", "white"

    rows_html = ""
    for days_off_idx, row in enumerate(reversed(grid)):
        days_off = max_days_off - days_off_idx
        cells = f'<td class="axis-label">{days_off}</td>'
        for days_spent_idx, count in enumerate(row):
            days_spent = days_spent_idx
            if count == 0:
                cells += '<td class="cell empty">0</td>'
            else:
                score = score_period(days_spent, days_off)
                bg, text = score_to_color(score)
                link = f"/vacation-grid-detail?year={year}&username={escape(username)}&hash={escape(hash_value)}&spent={days_spent}&off={days_off}"
                cells += f'<td class="cell" style="background:{bg};color:{text}"><a href="{link}">{count}</a></td>'
        rows_html += f"<tr>{cells}</tr>\n"

    # Right-side "Top opportunities" panel
    cards_html = ""
    for i, opp in enumerate(opportunities, 1):
        spent, off = opp["spent"], opp["off"]
        ratio_text = f"{off / spent:.1f}x" if spent > 0 else "FREE"
        start_fmt = opp["start_date"].strftime("%d %b")
        end_fmt = opp["end_date"].strftime("%d %b")
        squares = _render_day_squares(opp["days"])
        holiday_badge = (
            f'<span class="badge">🎉 {opp["holidays"]} holiday{"s" if opp["holidays"] != 1 else ""}</span>'
            if opp["holidays"] else ""
        )
        link = f"/vacation-grid-detail?year={year}&username={escape(username)}&hash={escape(hash_value)}&spent={spent}&off={off}"
        cards_html += f"""
            <a class="opp-card" href="{link}">
                <div class="opp-head">
                    <span class="opp-rank">#{i}</span>
                    <span class="opp-headline">{spent}&rarr;{off} days <span class="opp-ratio">{ratio_text}</span></span>
                </div>
                <div class="opp-dates">{start_fmt} &ndash; {end_fmt} {holiday_badge}</div>
                <div class="day-squares">{squares}</div>
            </a>"""
    if not opportunities:
        cards_html = '<p style="color:#999;font-size:11px;">No opportunities found.</p>'

    x_labels = '<td class="axis-label"></td>'
    for days_spent in range(0, max_budget + 1):
        x_labels += f'<td class="axis-label">{days_spent}</td>'

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Vacation Grid - {year}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 8px;
            background: white;
            color: #333;
        }}
        h1 {{ font-size: 16px; margin: 0 0 4px 0; color: #1976D2; }}
        p {{ font-size: 12px; color: #666; margin: 0 0 8px 0; }}
        .grid-container {{
            overflow-x: auto;
        }}
        table {{
            border-collapse: collapse;
            font-size: 10px;
        }}
        .cell {{
            width: 22px;
            height: 22px;
            text-align: center;
            vertical-align: middle;
            border: 1px solid #ddd;
        }}
        .empty {{ background: #f0f0f0; color: #ccc; }}
        .cell a {{ color: inherit; text-decoration: none; display: block; }}
        .cell a:hover {{ text-decoration: underline; }}
        .axis-label {{
            font-size: 9px;
            color: #666;
            text-align: center;
            padding: 2px 4px;
            font-weight: 500;
        }}
        .axis-title {{
            font-size: 11px;
            color: #333;
            margin: 4px 0;
        }}
        .legend {{
            display: flex;
            gap: 12px;
            margin-top: 8px;
            font-size: 10px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .legend-box {{
            width: 12px;
            height: 12px;
            border-radius: 2px;
        }}
        .layout {{
            display: flex;
            gap: 16px;
            align-items: flex-start;
            flex-wrap: wrap;
        }}
        .grid-side {{ flex: 1 1 auto; min-width: 0; }}
        .opp-side {{
            flex: 0 0 240px;
            max-width: 100%;
        }}
        .opp-side h2 {{
            font-size: 14px;
            margin: 0 0 2px 0;
            color: #1976D2;
        }}
        .opp-sub {{ font-size: 11px; color: #999; margin: 0 0 8px 0; }}
        .opp-card {{
            display: block;
            text-decoration: none;
            color: inherit;
            background: #fff;
            border: 1px solid #eee;
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.06);
        }}
        .opp-card:hover {{ border-color: #1976D2; box-shadow: 0 2px 6px rgba(25,118,210,0.15); }}
        .opp-head {{ display: flex; align-items: baseline; gap: 6px; }}
        .opp-rank {{ font-size: 11px; color: #999; font-weight: 600; }}
        .opp-headline {{ font-size: 13px; font-weight: 600; color: #333; }}
        .opp-ratio {{ color: #1976D2; }}
        .opp-dates {{ font-size: 11px; color: #666; margin: 2px 0 6px 0; }}
        .badge {{
            display: inline-block;
            font-size: 10px;
            color: #00796B;
            background: #E0F2F1;
            border-radius: 3px;
            padding: 1px 4px;
            margin-left: 4px;
        }}
        form {{
            margin-top: 10px;
            padding: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
        }}
        label {{ font-size: 12px; color: #666; }}
        input[type="number"] {{
            width: 50px;
            padding: 4px 6px;
            border: 1px solid #ddd;
            border-radius: 3px;
            font-size: 12px;
        }}
        button {{
            padding: 4px 12px;
            background: #1976D2;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
        }}
        button:hover {{ background: #1565C0; }}
    </style>
</head>
<body>
    <h1>Vacation Possibilities Grid - {year}</h1>
    <p>Each cell shows count of vacation periods. X: days spent, Y: days off</p>

    <div class="legend">
        <div class="legend-item"><div class="legend-box" style="background:linear-gradient(to right, hsl(30,70%,45%), hsl(90,70%,45%), hsl(150,70%,45%), hsl(210,70%,45%));width:80px"></div> less &rarr; more interesting</div>
        <div class="legend-item"><div class="legend-box" style="background:#f0f0f0;border:1px solid #ddd"></div> None</div>
    </div>

    <div class="layout">
        <div class="grid-side">
            <p class="axis-title">Y: Days off &darr;</p>
            <div class="grid-container">
                <table>
                    <tbody>
                        {rows_html}
                    </tbody>
                    <tfoot>
                        <tr>{x_labels}</tr>
                    </tfoot>
                </table>
            </div>
            <p class="axis-title">X: Days spent &rarr;</p>
        </div>

        <aside class="opp-side">
            <h2>⭐ Top opportunities</h2>
            <p class="opp-sub">Best bang-for-buck breaks, ranked by interestingness.</p>
            {cards_html}
        </aside>
    </div>

    <form method="GET">
        <input type="hidden" name="year" value="{year}">
        <input type="hidden" name="username" value="{escape(username)}">
        <input type="hidden" name="hash" value="{escape(hash_value)}">
        <label>Max budget:</label>
        <input type="number" name="budget" min="1" max="50" value="{budget}">
        <button type="submit">Recalculate</button>
    </form>
</body>
</html>"""

    return html
