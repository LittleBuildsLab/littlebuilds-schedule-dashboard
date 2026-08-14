from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import os.path

from flask import Flask, render_template
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


app = Flask(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
LOCAL_TIMEZONE = ZoneInfo("America/Winnipeg")


def get_calendar_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def format_clock(date_time):
    return date_time.strftime("%I:%M %p").lstrip("0")


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
            )
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
            "time": free_until
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
            "time": next_time
        }

    else:
        next_event = {
            "title": "Nothing scheduled",
            "time": "Rest of week is clear"
        }

    today_events = []

    for event in events:
        if event["start"].date() == now.date():
            if event["all_day"]:
                today_events.append(
                    f"All day — {event['title']}"
                )
            else:
                today_events.append(
                    f"{format_clock(event['start'])} — "
                    f"{event['title']}"
                )

    if not today_events:
        today_events.append("Free / Buffer")

    week_events = []

    for event in events:
        day_name = event["start"].strftime("%A")

        if event["all_day"]:
            week_events.append(
                f"{day_name} — {event['title']}"
            )
        else:
            week_events.append(
                f"{day_name} {format_clock(event['start'])} — "
                f"{event['title']}"
            )

    if not week_events:
        week_events.append("No scheduled events")

    return render_template(
        "dashboard.html",
        now_event=now_event,
        next_event=next_event,
        today_events=today_events,
        week_events=week_events
    )


if __name__ == "__main__":
    app.run(debug=True)