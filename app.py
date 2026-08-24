from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import json
import os
import os.path

from flask import Flask, render_template
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


app = Flask(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
LOCAL_TIMEZONE = ZoneInfo("America/Winnipeg")
TIMELINE_START_HOUR = 7
TIMELINE_END_HOUR = 21


def get_calendar_service():
    creds = None

    token_json = os.environ.get("GOOGLE_TOKEN_JSON")

    if token_json:
        creds = Credentials.from_authorized_user_info(
            json.loads(token_json),
            SCOPES
        )
    elif os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.environ.get("RENDER"):
                raise RuntimeError(
                    "GOOGLE_TOKEN_JSON is not configured on Render."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        if not os.environ.get("RENDER"):
            with open("token.json", "w") as token:
                token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def format_clock(date_time):
    return date_time.strftime("%I:%M %p").lstrip("0")


def format_short_date(date_value):
    return f"{date_value.strftime('%b')} {date_value.day}"


def format_long_date(date_value):
    return (
        f"{date_value.strftime('%A')}, "
        f"{date_value.strftime('%B')} {date_value.day}"
    )


def event_theme(title):
    normalized = title.lower()

    themes = [
        (
            ("core", "study", "exam", "quiz", "comptia", "course"),
            "Study",
            "study"
        ),
        (
            ("project", "lab", "vm", "linux", "windows", "code"),
            "IT Project",
            "project"
        ),
        (
            ("tile", "tag", "toupin", "email", "invoice", "work"),
            "Work",
            "work"
        ),
        (
            ("plan", "review", "audit", "weekly"),
            "Planning",
            "planning"
        ),
        (
            ("shop", "grocery", "appointment", "home"),
            "Personal",
            "personal"
        )
    ]

    for keywords, label, css_class in themes:
        if any(keyword in normalized for keyword in keywords):
            return {"label": label, "class": css_class}

    return {"label": "Scheduled", "class": "scheduled"}


def event_status(event, now):
    if event["end"] <= now:
        return "past"
    if event["start"] <= now < event["end"]:
        return "current"
    return "upcoming"


def make_timeline_event(event, now):
    day_start_minutes = TIMELINE_START_HOUR * 60
    day_end_minutes = TIMELINE_END_HOUR * 60
    timeline_minutes = day_end_minutes - day_start_minutes

    start_minutes = event["start"].hour * 60 + event["start"].minute
    end_minutes = event["end"].hour * 60 + event["end"].minute

    if event["end"].date() > event["start"].date():
        end_minutes = 24 * 60

    clipped_start = max(start_minutes, day_start_minutes)
    clipped_end = min(end_minutes, day_end_minutes)

    if clipped_end <= day_start_minutes or clipped_start >= day_end_minutes:
        return None

    top = ((clipped_start - day_start_minutes) / timeline_minutes) * 100
    height = ((clipped_end - clipped_start) / timeline_minutes) * 100
    theme = event_theme(event["title"])

    return {
        "title": event["title"],
        "time": (
            f"{format_clock(event['start'])} – "
            f"{format_clock(event['end'])}"
        ),
        "top": round(top, 3),
        "height": round(max(height, 3.9), 3),
        "status": event_status(event, now),
        "theme_label": theme["label"],
        "theme_class": theme["class"]
    }


def normalize_event(event):
    title = event.get("summary", "(No title)")

    if "dateTime" in event["start"]:
        start = datetime.fromisoformat(
            event["start"]["dateTime"].replace("Z", "+00:00")
        ).astimezone(LOCAL_TIMEZONE)

        end = datetime.fromisoformat(
            event["end"]["dateTime"].replace("Z", "+00:00")
        ).astimezone(LOCAL_TIMEZONE)

        all_day = False

    else:
        start_date = datetime.fromisoformat(
            event["start"]["date"]
        ).date()

        end_date = datetime.fromisoformat(
            event["end"]["date"]
        ).date()

        start = datetime.combine(
            start_date,
            time.min,
            tzinfo=LOCAL_TIMEZONE
        )

        end = datetime.combine(
            end_date,
            time.min,
            tzinfo=LOCAL_TIMEZONE
        )

        all_day = True

    return {
        "title": title,
        "start": start,
        "end": end,
        "all_day": all_day
    }


def get_week_events(now):
    service = get_calendar_service()

    today_start = datetime.combine(
        now.date(),
        time.min,
        tzinfo=LOCAL_TIMEZONE
    )

    days_until_monday = 7 - now.weekday()
    week_end = today_start + timedelta(days=days_until_monday)

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=today_start.isoformat(),
            timeMax=week_end.isoformat(),
            maxResults=100,
            singleEvents=True,
            orderBy="startTime",
            timeZone="America/Winnipeg"
        )
        .execute()
    )

    return [
        normalize_event(event)
        for event in result.get("items", [])
    ]


@app.route("/")
def home():
    now = datetime.now(LOCAL_TIMEZONE)
    events = get_week_events(now)

    current_events = [
        event
        for event in events
        if not event["all_day"]
        and event["start"] <= now < event["end"]
    ]

    upcoming_events = [
        event
        for event in events
        if event["start"] > now
    ]

    if current_events:
        current = current_events[0]

        now_event = {
            "title": current["title"],
            "time": (
                f"{format_clock(current['start'])} – "
                f"{format_clock(current['end'])}"
            ),
            "theme_class": event_theme(current["title"])["class"]
        }

    else:
        if upcoming_events:
            next_start = upcoming_events[0]["start"]

            if next_start.date() == now.date():
                free_until = f"Until {format_clock(next_start)}"
            else:
                free_until = "Rest of today"
        else:
            free_until = "Rest of today"

        now_event = {
            "title": "Free / Buffer",
            "time": free_until,
            "theme_class": "buffer"
        }

    if upcoming_events:
        upcoming = upcoming_events[0]

        if upcoming["all_day"]:
            next_time = "All day"

        elif upcoming["start"].date() == now.date():
            next_time = format_clock(upcoming["start"])

        elif upcoming["start"].date() == now.date() + timedelta(days=1):
            next_time = (
                f"Tomorrow · {format_clock(upcoming['start'])}"
            )

        else:
            next_time = (
                f"{upcoming['start'].strftime('%A')} · "
                f"{format_clock(upcoming['start'])}"
            )

        next_event = {
            "title": upcoming["title"],
            "time": next_time,
            "theme_class": event_theme(upcoming["title"])["class"]
        }

    else:
        next_event = {
            "title": "Nothing scheduled",
            "time": "Rest of week is clear",
            "theme_class": "buffer"
        }

    today_timeline_events = []
    today_all_day_events = []

    for event in events:
        if event["start"].date() != now.date():
            continue

        if event["all_day"]:
            theme = event_theme(event["title"])
            today_all_day_events.append(
                {
                    "title": event["title"],
                    "theme_class": theme["class"]
                }
            )
            continue

        timeline_event = make_timeline_event(event, now)
        if timeline_event:
            today_timeline_events.append(timeline_event)

    timeline_hours = []
    timeline_minutes = (
        TIMELINE_END_HOUR - TIMELINE_START_HOUR
    ) * 60

    for hour in range(TIMELINE_START_HOUR, TIMELINE_END_HOUR + 1):
        label_time = datetime.combine(
            now.date(),
            time(hour=hour),
            tzinfo=LOCAL_TIMEZONE
        )
        timeline_hours.append(
            {
                "label": format_clock(label_time),
                "top": round(
                    ((hour - TIMELINE_START_HOUR) * 60)
                    / timeline_minutes
                    * 100,
                    3
                )
            }
        )

    current_minutes = now.hour * 60 + now.minute
    if (
        TIMELINE_START_HOUR * 60
        <= current_minutes
        <= TIMELINE_END_HOUR * 60
    ):
        now_position = round(
            (
                current_minutes - TIMELINE_START_HOUR * 60
            )
            / timeline_minutes
            * 100,
            3
        )
    else:
        now_position = None

    week_groups = []
    grouped_events = {}

    for event in events:
        event_date = event["start"].date()
        grouped_events.setdefault(event_date, []).append(event)

    for event_date in sorted(grouped_events):
        day_events = []

        for event in grouped_events[event_date]:
            theme = event_theme(event["title"])
            day_events.append(
                {
                    "title": event["title"],
                    "time": (
                        "All day"
                        if event["all_day"]
                        else (
                            f"{format_clock(event['start'])} – "
                            f"{format_clock(event['end'])}"
                        )
                    ),
                    "theme_class": theme["class"],
                    "status": event_status(event, now)
                }
            )

        week_groups.append(
            {
                "day": event_date.strftime("%A"),
                "date": format_short_date(event_date),
                "is_today": event_date == now.date(),
                "events": day_events
            }
        )

    return render_template(
        "dashboard.html",
        now_event=now_event,
        next_event=next_event,
        today_timeline_events=today_timeline_events,
        today_all_day_events=today_all_day_events,
        timeline_hours=timeline_hours,
        now_position=now_position,
        week_groups=week_groups,
        today_heading=format_long_date(now.date()),
        refreshed_at=format_clock(now)
    )


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True)
