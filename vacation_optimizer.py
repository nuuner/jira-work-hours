from datetime import date, timedelta
from html import escape
from typing import Iterator


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

    grid = []
    for days_off in range(1, max_days_off + 1):
        row = [counts.get((days_spent, days_off), 0) for days_spent in range(0, max_budget + 1)]
        grid.append(row)

    return {"grid": grid, "max_days_off": max_days_off, "max_budget": max_budget}


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


def create_vacation_cell_detail_html(
    year: int, days_spent: int, days_off: int, username: str, hash_value: str, periods: list[dict]
) -> str:
    """Generate HTML page showing periods for a specific cell."""
    rows_html = ""
    for i, p in enumerate(periods, 1):
        start_fmt = p["start_date"].strftime("%d %b")
        end_fmt = p["end_date"].strftime("%d %b")

        squares = ""
        for day in p["days"]:
            in_period = day.get("in_period", True)
            if day["is_working"]:
                if in_period:
                    color = "#1976D2"  # Blue - vacation day
                else:
                    color = "#9E9E9E"  # Grey - regular working day (context)
            elif day["is_weekend"]:
                color = "#CE93D8"  # Light purple - weekend
            else:
                color = "#81D4FA"  # Light blue - holiday

            opacity = day.get("opacity", 1.0)
            title = day["date"].strftime("%d %b %a")
            if in_period and day["is_working"]:
                title += " (vacation)"
            squares += f'<span class="day-sq" style="background:{color};opacity:{opacity:.2f}" title="{title}"></span>'

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
    year: int, budget: int, username: str, hash_value: str, grid_data: dict
) -> str:
    """Generate HTML page displaying vacation grid."""
    grid = grid_data["grid"]
    max_days_off = grid_data["max_days_off"]
    max_budget = grid_data["max_budget"]

    def ratio_to_color(ratio: float) -> tuple[str, str]:
        """Convert ratio to background color and text color using smooth heatmap."""
        r = max(1.0, min(4.0, ratio))
        hue = 30 + (r - 1.0) * (210 - 30) / (4.0 - 1.0)
        bg = f"hsl({hue:.0f}, 70%, 45%)"
        return bg, "white"

    rows_html = ""
    for days_off_idx, row in enumerate(reversed(grid)):
        days_off = max_days_off - days_off_idx
        cells = f'<td class="axis-label">{days_off}</td>'
        for days_spent_idx, count in enumerate(row):
            days_spent = days_spent_idx
            if count == 0:
                cells += '<td class="cell empty">0</td>'
            else:
                ratio = days_off / days_spent if days_spent > 0 else float('inf')
                bg, text = ratio_to_color(ratio)
                link = f"/vacation-grid-detail?year={year}&username={escape(username)}&hash={escape(hash_value)}&spent={days_spent}&off={days_off}"
                cells += f'<td class="cell" style="background:{bg};color:{text}"><a href="{link}">{count}</a></td>'
        rows_html += f"<tr>{cells}</tr>\n"

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
        <div class="legend-item"><div class="legend-box" style="background:linear-gradient(to right, hsl(30,70%,45%), hsl(90,70%,45%), hsl(150,70%,45%), hsl(210,70%,45%));width:80px"></div> 1x &rarr; 4x ratio</div>
        <div class="legend-item"><div class="legend-box" style="background:#f0f0f0;border:1px solid #ddd"></div> None</div>
    </div>

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
