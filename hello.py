import os
from atlassian import Jira
from dotenv import load_dotenv
import drawsvg as draw
import calendar
from datetime import date
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import Response
from typing import Annotated
import hmac
import hashlib
import math

app = FastAPI()

def generate_request_hash(year: int, month: int, username: str) -> str:
    load_dotenv()
    secret_key = os.getenv("HASH_SECRET_KEY", "default-secret-key-change-me")
    message = f"{year}-{month}-{username}".encode('utf-8')
    h = hmac.new(secret_key.encode('utf-8'), message, hashlib.sha256)
    return h.hexdigest()

def create_calendar_svg(year: int, month: int, jira_username: str) -> str:
    load_dotenv()
    jira = Jira(os.getenv("JIRA_URL"), token=os.getenv("JIRA_API_TOKEN"))

    from_date = f"{year}-{month:02d}-01"
    to_date = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"

    worked_time = {}
    dopust_days = set()  # Track days with annual leave
    try:
        worklogs = jira.tempo_timesheets_get_worklogs(
            date_from=from_date, date_to=to_date, username=jira_username
        )

        if worklogs and isinstance(worklogs, list):
            for worklog in worklogs:
                if (
                    isinstance(worklog, dict)
                    and "dateStarted" in worklog
                    and "timeSpentSeconds" in worklog
                ):
                    extracted_date = worklog.get("dateStarted", "").split("T")[0]
                    if (
                        "issue" in worklog
                        and isinstance(worklog["issue"], dict)
                        and "summary" in worklog["issue"]
                        and worklog["issue"]["summary"].startswith("Letni dopust")
                    ):
                        time_spent = 7.5 * 3600  # 7.5 hours in seconds
                        dopust_days.add(extracted_date)
                    else:
                        time_spent = worklog.get("timeSpentSeconds", 0)
                    if extracted_date:
                        worked_time[extracted_date] = (
                            worked_time.get(extracted_date, 0) + time_spent
                        )
    except Exception as e:
        print(f"Error fetching worklog data: {str(e)}")

    day_types = {}
    try:
        from_date = f"{year}-{month:02d}-01"
        to_date = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        required_times = jira.tempo_timesheets_get_required_times(
            from_date=from_date, to_date=to_date, user_name=jira_username
        )
        if isinstance(required_times, list):
            day_types = {
                item["date"]: item["type"]
                for item in required_times
                if isinstance(item, dict)
            }
    except Exception as e:
        print(f"Error fetching Jira data: {str(e)}")

    cell_size = {"width": 80, "height": 65}
    padding = 8
    colors = {
        "NON_WORKING_DAY": "#E0E0E0",
        "WORKING_DAY": "white", 
        "HOLIDAY": "#E3F2FD",
        "HOLIDAY_AND_NON_WORKING_DAY": "#E1E9EE",
    }

    running_total = 0
    running_totals = {}
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        day_type = day_types.get(date_str, "WORKING_DAY")
        expected_hours = 7.5 if day_type == "WORKING_DAY" else 0
        hours_worked = worked_time.get(date_str, 0) / 3600
        running_total += hours_worked - expected_hours
        running_totals[date_str] = running_total

    d = draw.Drawing(
        cell_size["width"] * 7 + padding * 2,
        cell_size["height"] * 6 + padding * 2 + 60 + 100,
        font_family="Arial",
    )

    month_name = calendar.month_name[month]
    title = f"Work Hours Calendar - {month_name} {year} - {jira_username}"
    d.append(
        draw.Text(
            title,
            18,
            padding + (cell_size["width"] * 7) / 2,
            padding + 16,
            text_anchor="middle",
            font_weight="bold",
        )
    )

    today = date.today()
    current_month = today.replace(day=1)
    target_month = date(year, month, 1)
    is_past_month = target_month < current_month
    is_current_month = (
        target_month.year == today.year and target_month.month == today.month
    )

    worked_days = len(set(worked_time.keys()))
    total_hours_worked = sum(seconds / 3600 for seconds in worked_time.values())
    avg_hours = total_hours_worked / worked_days if worked_days > 0 else 0

    remaining_working_days = 0
    if not is_past_month:
        for day in range(
            today.day if is_current_month else 1,
            calendar.monthrange(year, month)[1] + 1,
        ):
            date_str = f"{year}-{month:02d}-{day:02d}"
            if day_types.get(date_str) == "WORKING_DAY" and date_str not in dopust_days:
                remaining_working_days += 1

    current_diff = running_total
    if remaining_working_days > 0:
        required_hours_per_day = (-current_diff) / remaining_working_days
    else:
        required_hours_per_day = abs(current_diff) if current_diff < 0 else 0

    stats_y = padding + 35
    card_height = 85

    d.append(
        draw.Rectangle(
            padding,
            stats_y,
            cell_size["width"] * 4,
            card_height + padding,
            fill="white",
            stroke="black",
        )
    )

    stats_labels = [
        "Average hours worked per day",
        "Accumulated difference",
    ]

    stats_values = [
        format_time(avg_hours),
        format_time(current_diff, show_plus=True),
    ]

    if not is_past_month:
        stats_labels.extend(
            ["Working days remaining", "Required hours per remaining work day"]
        )
        stats_values.extend(
            [f"{remaining_working_days}", format_time(required_hours_per_day)]
        )

    value_x = padding + (cell_size["width"] * 4 - 12)

    for i, (label, value) in enumerate(zip(stats_labels, stats_values)):
        d.append(draw.Text(label, 12, padding + 16, stats_y + 25 + i * 18))
        d.append(
            draw.Text(value, 12, value_x, stats_y + 25 + i * 18, text_anchor="end")
        )

    graph_x = 2 * padding + cell_size["width"] * 4 + padding * 2
    graph_y = stats_y
    graph_width = cell_size["width"] * 3 - padding * 3
    graph_height = card_height + padding

    d.append(
        draw.Rectangle(
            graph_x, graph_y, graph_width, graph_height, fill="white", stroke="black"
        )
    )

    max_hours = 10
    grid_steps = 5
    for i in range(grid_steps + 1):
        y_pos = graph_y + graph_height - (i * graph_height / grid_steps)
        hours = i * max_hours / grid_steps
        d.append(
            draw.Line(
                graph_x,
                y_pos,
                graph_x + graph_width,
                y_pos,
                stroke="#CCCCCC",
                stroke_width=0.5,
            )
        )
        d.append(draw.Text(f"{int(hours)}h", 8, graph_x - 2, y_pos, text_anchor="end"))

    target_y = graph_y + graph_height - (7.5 / max_hours) * graph_height
    d.append(
        draw.Line(
            graph_x,
            target_y,
            graph_x + graph_width,
            target_y,
            stroke="#1976D2",
            stroke_width=1,
        )
    )

    days_in_month = calendar.monthrange(year, month)[1]
    available_width = graph_width - 20
    bar_spacing = 1
    bar_width = max(
        1, (available_width - (days_in_month - 1) * bar_spacing) / days_in_month
    )

    def draw_stars(d, x, y, count, size=8):
        for i in range(min(count, 5)):  # Limit to 5 stars maximum
            star_x = x + cell_size["width"] - (size + 2) * (i + 1)
            star_y = y + size + 2
            
            # Create a 5-pointed star path
            points = []
            for j in range(5):
                angle = -90 + j * 72  # Start from top point
                outer_x = star_x + size/2 * math.cos(math.radians(angle))
                outer_y = star_y + size/2 * math.sin(math.radians(angle))
                points.append((outer_x, outer_y))
                
                inner_angle = angle + 36
                inner_x = star_x + size/4 * math.cos(math.radians(inner_angle))
                inner_y = star_y + size/4 * math.sin(math.radians(inner_angle))
                points.append((inner_x, inner_y))
            
            # Convert points to SVG path
            path_data = f"M {points[0][0]},{points[0][1]}"
            for px, py in points[1:]:
                path_data += f" L {px},{py}"
            path_data += " Z"
            
            d.append(draw.Path(path_data, fill="#2E7D32"))

    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        hours = worked_time.get(date_str, 0) / 3600 
        bar_x = graph_x + 10 + (day - 1) * (bar_width + bar_spacing)

        if date_str in dopust_days:
            bar_color = "#0D47A1"
        else:
            min_hours = 4
            lower_margin = 7 + (25 / 60)
            upper_margin = 7 + (35 / 60)

            if hours == 0:
                bar_color = "#CCCCCC"
            elif hours < min_hours:
                bar_color = "#C62828"
            elif hours < lower_margin:
                bar_color = "#EF6C00"
            elif hours < upper_margin:
                bar_color = "#1976D2"
            elif hours < 10:
                bar_color = "#2E7D32"
            else:
                bar_color = "#9C27B0"

        visible_hours = min(hours, 10)
        bar_height = (visible_hours / max_hours) * graph_height
        bar_y = graph_y + graph_height - bar_height
        
        d.append(draw.Rectangle(bar_x, bar_y, bar_width, bar_height, fill=bar_color))

        if day == 1 or day == days_in_month or day % 5 == 0:
            d.append(
                draw.Text(
                    str(day),
                    8,
                    bar_x + bar_width / 2,
                    graph_y + graph_height + 12,
                    text_anchor="middle",
                )
            )

    calendar_start_y = stats_y + card_height + padding + 30
    for i, day in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        x = padding + i * cell_size["width"]
        d.append(
            draw.Text(
                day,
                14,
                x + cell_size["width"] / 2,
                calendar_start_y,
                text_anchor="middle",
            )
        )

    for row, week in enumerate(calendar.monthcalendar(year, month)):
        for col, day in enumerate(week):
            x = padding + col * cell_size["width"]
            y = calendar_start_y + 10 + row * cell_size["height"]

            if day != 0:
                date_str = f"{year}-{month:02d}-{day:02d}"
                fill_color = colors[day_types.get(date_str, "WORKING_DAY")]
                d.append(
                    draw.Rectangle(
                        x,
                        y,
                        cell_size["width"],
                        cell_size["height"],
                        fill=fill_color,
                        stroke="black",
                    )
                )
                
                # Add overtime stars
                hours_worked = worked_time.get(date_str, 0) / 3600
                day_type = day_types.get(date_str, "WORKING_DAY")
                expected_hours = 7.5 if day_type == "WORKING_DAY" else 0
                overtime = max(0, hours_worked - expected_hours)
                star_count = int(overtime * 2)  # 2 stars per hour (1 star per 30 minutes)
                if star_count > 0:
                    draw_stars(d, x, y, star_count)

                d.append(draw.Text(str(day), 12, x + 8, y + 16))

                hours_color = "#0D47A1" if date_str in dopust_days else "black"
                d.append(
                    draw.Text(
                        format_time(hours_worked), 10, x + 8, y + 32, fill=hours_color
                    )
                )

                day_type = day_types.get(date_str, "WORKING_DAY")
                expected_hours = 7.5 if day_type == "WORKING_DAY" else 0
                diff = hours_worked - expected_hours
                diff_color = "#2E7D32" if diff >= 0 else "#C62828"
                diff_text = format_time(diff, show_plus=True)
                d.append(draw.Text(diff_text, 10, x + 8, y + 44, fill=diff_color))

                d.append(
                    draw.Line(
                        x + 8,
                        y + 48,
                        x + 40,
                        y + 48,
                        stroke="#666666",
                        stroke_width=0.5,
                    )
                )

                if date_str in running_totals:
                    total = running_totals[date_str]
                    total_color = "#2E7D32" if total >= 0 else "#C62828"
                    total_text = format_time(total, show_plus=True)
                    d.append(draw.Text(total_text, 10, x + 8, y + 58, fill=total_color))
            else:
                d.append(
                    draw.Rectangle(
                        x,
                        y,
                        cell_size["width"],
                        cell_size["height"],
                        fill="white",
                        stroke="black",
                    )
                )

    svg_content = d.as_svg()
    if svg_content is None:
        raise ValueError("Failed to generate SVG content")
    return svg_content

def format_time(hours: float, show_plus: bool = False) -> str:
    sign = "-" if hours < 0 else ("+" if show_plus and hours > 0 else "")
    total_minutes = int(abs(hours) * 60)
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{sign}{h}h {m}m"

@app.get("/calendar")
async def get_calendar(
    year: Annotated[int, Query(ge=2000, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    username: str,
    hash: str,
) -> Response:
    expected_hash = generate_request_hash(year, month, username)
    if not hmac.compare_digest(hash, expected_hash):
        raise HTTPException(status_code=403, detail="Invalid hash")
        
    svg_content = create_calendar_svg(year, month, username)
    headers = {
        "Cache-Control": "public, max-age=60",
        "Content-Type": "image/svg+xml",
    }
    return Response(content=svg_content, headers=headers)
