from contextlib import asynccontextmanager
import os
from atlassian import Jira
from dotenv import load_dotenv
import drawsvg as draw
import calendar
from datetime import date, datetime, time, timedelta
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import Response
from typing import Annotated
import hmac
import hashlib
import math

cache_duration = 5  # Default is 5 minutes
secret_key = "default-secret-key-change-me"
jira_url = "invalid-url"
jira_api_token = "invalid-token"
jira = None

svg_cache = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    global cache_duration
    cache_duration = int(os.getenv("CACHE_DURATION", cache_duration))
    global secret_key
    secret_key = os.getenv("HASH_SECRET_KEY", secret_key)

    global jira_url
    jira_url = os.getenv("JIRA_URL")
    global jira_api_token
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    if not jira_url or not jira_api_token:
        raise ValueError("JIRA_URL or JIRA_API_TOKEN is not set")

    global jira
    jira = Jira(jira_url, token=jira_api_token)

    try:
        jira.myself()
    except Exception as e:
        raise ValueError(f"Failed to authenticate with Jira: {str(e)}")

    yield

app = FastAPI(lifespan=lifespan)

def generate_request_hash(year: int, month: int, username: str) -> str:
    message = f"{year}-{month}-{username}".encode('utf-8')
    h = hmac.new(secret_key.encode('utf-8'), message, hashlib.sha256)
    return h.hexdigest()

def create_calendar_svg(year: int, month: int, jira_username: str, additional_vacation_days: set[str] = set(), daily_hours: float = 7.5, started_working: str | None = None) -> str:

    from_date = f"{year}-{month:02d}-01"
    to_date = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"

    worked_time = {}
    dopust_days = set()  # Track days with annual leave
    sick_days = set()    # Track days with sick leave
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
                    ):
                        summary = worklog["issue"]["summary"]
                        if summary.startswith("Letni dopust"):
                            time_spent = daily_hours * 3600  # daily_hours in seconds
                            dopust_days.add(extracted_date)
                        elif summary.startswith("Bolniška odsotnost"):
                            time_spent = worklog.get("timeSpentSeconds", 0)
                            # for every 8 hours of work, remove half an hour of vacation
                            factor_of_time_to_remove = (time_spent / 8) * 0.5
                            time_spent = time_spent - factor_of_time_to_remove
                            sick_days.add(extracted_date)
                        else:
                            time_spent = worklog.get("timeSpentSeconds", 0)
                    else:
                        time_spent = worklog.get("timeSpentSeconds", 0)
                    if extracted_date:
                        worked_time[extracted_date] = (
                            worked_time.get(extracted_date, 0) + time_spent
                        )
    except Exception as e:
        print(f"Error fetching worklog data: {str(e)}")

    # Add additional vacation days
    for vacation_date in additional_vacation_days:
        if vacation_date.startswith(f"{year}-{month:02d}"):  # Only process dates in the target month
            worked_time[vacation_date] = daily_hours * 3600  # daily_hours in seconds
            dopust_days.add(vacation_date)

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

    # Helper function to determine if a date is a working day
    def is_working_day(date_str: str) -> bool:
        """Returns True if the date is a working day (not vacation, not before start date, and marked as WORKING_DAY)"""
        # Skip if before started_working
        if started_working and date_str < started_working:
            return False
        # Not a working day if it's a vacation day
        if date_str in dopust_days:
            return False
        # Check if it's marked as a working day
        return day_types.get(date_str) == "WORKING_DAY"

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
        # Check if date is before started_working
        if started_working and date_str < started_working:
            expected_hours = 0
        else:
            expected_hours = daily_hours if day_type == "WORKING_DAY" else 0
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

    # Count actual working days that have passed (for meaningful average)
    total_hours_worked = sum(seconds / 3600 for seconds in worked_time.values())

    # Determine the last day to count for average calculation
    if is_past_month:
        last_day_for_avg = calendar.monthrange(year, month)[1]
    elif is_current_month:
        last_day_for_avg = today.day
    else:
        # Future month - no days have passed yet
        last_day_for_avg = 0

    # Count working days that have passed (excluding vacation and pre-start days)
    elapsed_working_days = 0
    for day in range(1, last_day_for_avg + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        if is_working_day(date_str):
            elapsed_working_days += 1

    avg_hours = total_hours_worked / elapsed_working_days if elapsed_working_days > 0 else 0

    remaining_working_days = 0
    if not is_past_month:
        for day in range(
            today.day if is_current_month else 1,
            calendar.monthrange(year, month)[1] + 1,
        ):
            date_str = f"{year}-{month:02d}-{day:02d}"
            if is_working_day(date_str):
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
        f"({elapsed_working_days}) {format_time(avg_hours)}",
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

    target_y = graph_y + graph_height - (daily_hours / max_hours) * graph_height
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

    def draw_sickness_icon(d, x, y):
        # Position the icon on the right side of the cell, at the same height as hours
        icon_x = x + cell_size["width"] - 32  # 32 pixels from right edge
        icon_y = y + 24  # Align with hours text
        
        # Scale the icon to appropriate size (16x16)
        scale = 0.67  # 16/24 to scale from 24x24 to 16x16
        
        # SVG path data for the sickness icon
        paths = [
            "M16.3188 4.39811C16.2142 4.63431 16.1229 4.86707 16.0449 5.0964C14.8581 4.39956 13.4757 4 12 4C8.26861 4 5.13388 6.55463 4.24939 10.0103C3.32522 10.0868 2.51988 10.5821 2.02371 11.306C2.38011 6.10691 6.71045 2 12 2C13.7733 2 15.4388 2.46156 16.8829 3.27111C16.6426 3.71554 16.4546 4.09121 16.3188 4.39811Z",
            "M16.6694 9.62311C16.782 9.7483 16.8987 9.86257 17.0193 9.96593C16.9678 9.9932 16.915 10.0195 16.8609 10.0447C16.35 10.2824 15.6778 10.438 14.9463 10.242C14.2147 10.046 13.7104 9.57517 13.3868 9.11381C13.0676 8.65868 12.8921 8.16974 12.8252 7.82758L14.2973 7.53961C14.3274 7.69373 14.4264 7.98373 14.6149 8.25248C14.799 8.51501 15.0357 8.71304 15.3345 8.7931C15.5814 8.85925 15.8319 8.83445 16.0755 8.7475C16.2274 9.06007 16.4253 9.35194 16.6694 9.62311Z",
            "M12 22C7.62613 22 3.90811 19.1919 2.55043 15.2802C3.07478 15.729 3.75574 16 4.50001 16C4.68514 16 4.86636 15.9832 5.04222 15.9511C6.41837 18.3693 9.01875 20 12 20C16.4183 20 20 16.4183 20 12C20 11.5146 19.9568 11.0392 19.8739 10.5776C20.4168 10.4171 20.9024 10.0989 21.3306 9.62311C21.4357 9.50632 21.5323 9.38569 21.6203 9.26122C21.8676 10.1316 22 11.0503 22 12C22 17.5228 17.5229 22 12 22Z",
            "M9.70411 7.53961C9.67396 7.69373 9.57502 7.98373 9.38652 8.25248C9.20239 8.51501 8.96567 8.71304 8.66689 8.7931C8.36811 8.87315 8.0641 8.82001 7.77337 8.68472C7.47575 8.54623 7.24507 8.34455 7.1419 8.22615L6.01101 9.21159C6.24005 9.47444 6.63649 9.81014 7.14052 10.0447C7.65143 10.2824 8.32358 10.438 9.05512 10.242C9.78666 10.046 10.291 9.57517 10.6146 9.11381C10.9338 8.65868 11.1093 8.16974 11.1762 7.82758L9.70411 7.53961Z",
            "M8.99481 13.4947C9.79184 12.6977 10.8728 12.2499 12 12.2499C13.1272 12.2499 14.2082 12.6977 15.0052 13.4947C15.8022 14.2917 16.25 15.3727 16.25 16.4999V17.2499H7.75001V16.4999C7.75001 16.2383 7.77413 15.9792 7.82113 15.7256L5.5016 14.7315C5.20706 14.9023 4.86495 15 4.5 15C3.39543 15 2.5 14.1046 2.5 13C2.5 11.8954 3.39543 11 4.5 11C5.59904 11 6.49103 11.8865 6.49993 12.9834L8.63815 13.8998C8.74775 13.7581 8.86677 13.6227 8.99481 13.4947ZM11.9683 15.7499C11.8933 15.4605 11.6899 15.2077 11.3939 15.0809L10.0896 14.5218C10.6018 14.0271 11.2866 13.7499 12 13.7499C12.7294 13.7499 13.4288 14.0396 13.9446 14.5554C14.2793 14.8901 14.5189 15.3024 14.6458 15.7499H11.9683Z",
            "M19 9C18.45 9 17.9792 8.80417 17.5875 8.4125C17.1958 8.02083 17 7.55 17 7C17 6.55 17.125 6.07083 17.375 5.5625C17.625 5.05417 18.1667 4.2 19 3C19.8333 4.2 20.375 5.05417 20.625 5.5625C20.875 6.07083 21 6.55 21 7C21 7.55 20.8042 8.02083 20.4125 8.4125C20.0208 8.80417 19.55 9 19 9Z"
        ]
        
        # Create a group for the icon with translation and scale
        g = draw.Group(transform=f'translate({icon_x},{icon_y}) scale({scale})')
        
        # Add each path to the group
        for path_data in paths:
            g.append(draw.Path(path_data, fill="#9575CD"))
        
        # Add the group to the drawing
        d.append(g)

    def draw_holiday_icon(d, x, y):
        # Position the icon on the right side of the cell, at the same height as hours
        icon_x = x + cell_size["width"] - 32  # 32 pixels from right edge
        icon_y = y + 24  # Align with hours text
        
        # Scale the icon to appropriate size (16x16)
        scale = 0.33  # 16/48 to scale from 48x48 to 16x16
        
        # Create a group for the icon with translation and scale
        g = draw.Group(transform=f'translate({icon_x},{icon_y}) scale({scale})')
        
        # SVG paths for the holiday icon
        paths = [
            {"d": "M4 24H7", "stroke-width": "4"},
            {"d": "M10 10L12 12", "stroke-width": "4"},
            {"d": "M24 4V7", "stroke-width": "4"},
            {"d": "M14 24C14 18.4776 18.4776 14 24 14C29.5224 14 34 18.4776 34 24C34 27.3674 32.3357 30.3458 29.785 32.1578", "stroke-width": "4"},
            {"d": "M38 10L36 12", "stroke-width": "4"},
            {"d": "M44 24L41 24", "stroke-width": "4"},
            {"d": "M37.9814 37.982L36.3614 36.362", "stroke-width": "4"},
            {"d": "M23.4999 28C20.4999 28 14 28.2 14 31C14 33.8 18.6058 33.7908 20.9998 34C23 34.1747 26.4624 35.6879 25.9999 38C24.9998 43 8.99982 42 4.99994 42", "stroke-width": "4"}
        ]
        
        # Add each path to the group
        for path_data in paths:
            path = draw.Path(path_data["d"], stroke="#1976D2", stroke_width=path_data["stroke-width"], 
                           stroke_linecap="round", stroke_linejoin="round", fill="none")
            g.append(path)
        
        # Add the group to the drawing
        d.append(g)

    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        hours = worked_time.get(date_str, 0) / 3600
        bar_x = graph_x + 10 + (day - 1) * (bar_width + bar_spacing)
        current_day_type = day_types.get(date_str)

        # Grey out bars for dates before started_working
        if started_working and date_str < started_working:
            bar_color = "#CCCCCC"
        elif date_str in dopust_days:
            bar_color = "#0D47A1"  # Dark blue for annual leave
        elif date_str in sick_days:
            bar_color = "#9575CD"  # Pale purple for sick leave
        else:
            min_hours = 4
            lower_margin = daily_hours - (5 / 60)  # 5 minutes below target
            upper_margin = daily_hours + (5 / 60)  # 5 minutes above target

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

            # If it's a holiday type with work, ensure color is at least blue
            if (current_day_type in ["HOLIDAY", "HOLIDAY_AND_NON_WORKING_DAY", "NON_WORKING_DAY"]) and hours > 0:
                if bar_color == "#C62828" or bar_color == "#EF6C00":
                    bar_color = "#1976D2"

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
                # Grey out dates before started_working
                if started_working and date_str < started_working:
                    fill_color = "#E0E0E0"
                else:
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
                # Check if date is before started_working
                if started_working and date_str < started_working:
                    expected_hours = 0
                else:
                    expected_hours = daily_hours if day_type == "WORKING_DAY" else 0
                overtime = max(0, hours_worked - expected_hours)
                star_count = int(overtime * 2)  # 2 stars per hour (1 star per 30 minutes)
                if star_count > 0:
                    draw_stars(d, x, y, star_count)

                # Add sickness icon if it's a sick day
                if date_str in sick_days:
                    draw_sickness_icon(d, x, y-4)
                # Add holiday icon if it's an annual leave day
                elif date_str in dopust_days:
                    draw_holiday_icon(d, x, y-4)

                d.append(draw.Text(str(day), 12, x + 8, y + 16))

                hours_color = "#0D47A1" if date_str in dopust_days else "#9575CD" if date_str in sick_days else "black"
                d.append(
                    draw.Text(
                        format_time(hours_worked), 10, x + 8, y + 32, fill=hours_color
                    )
                )

                day_type = day_types.get(date_str, "WORKING_DAY")
                # Check if date is before started_working
                if started_working and date_str < started_working:
                    expected_hours = 0
                else:
                    expected_hours = daily_hours if day_type == "WORKING_DAY" else 0
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

                # Add WD indicator for working days
                if is_working_day(date_str):
                    d.append(draw.Text("WD", 8, x + cell_size["width"] - 4, y + cell_size["height"] - 4, fill="#666666", text_anchor="end", font_weight="bold"))
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
    vacationDays: Annotated[str | None, Query(description="CSV of ISO dates (YYYY-MM-DD) to be treated as vacation days")] = None,
    dailyHours: Annotated[float, Query(ge=1, le=24, description="Target daily work hours")] = 7.5,
    startedWorking: Annotated[str | None, Query(description="ISO date (YYYY-MM-DD) when work started - days before this are greyed out with 0 goal")] = None,
) -> Response:
    expected_hash = generate_request_hash(year, month, username)
    if not hmac.compare_digest(hash, expected_hash):
        raise HTTPException(status_code=403, detail="Invalid hash")

    # Validate startedWorking date if provided
    if startedWorking:
        try:
            date.fromisoformat(startedWorking)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format in startedWorking. Use ISO format YYYY-MM-DD")

    # Check cache first
    cache_key = f"{year}-{month}-{username}-{vacationDays or ''}-{dailyHours}-{startedWorking or ''}"
    if cache_key in svg_cache and svg_cache[cache_key]["timestamp"] > datetime.now() - timedelta(minutes=cache_duration):
        svg_content = svg_cache[cache_key]["svg"]
    else:
        # Parse vacation days if provided
        additional_vacation_days = set()
        if vacationDays:
            try:
                additional_vacation_days = set(date.strip() for date in vacationDays.split(','))
                # Validate date format
                for date_str in additional_vacation_days:
                    date.fromisoformat(date_str)  # This will raise ValueError if format is invalid
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format in vacationDays. Use ISO format YYYY-MM-DD")

        svg_content = create_calendar_svg(year, month, username, additional_vacation_days, dailyHours, startedWorking)
        
        # Update cache
        svg_cache[cache_key] = {
            "svg": svg_content,
            "timestamp": datetime.now()
        }

    headers = {
        "Cache-Control": f"public, max-age={cache_duration * 60}",  # Convert minutes to seconds for HTTP header
        "Content-Type": "image/svg+xml",
    }
    return Response(content=svg_content, headers=headers)
