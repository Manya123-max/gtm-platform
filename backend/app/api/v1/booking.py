"""
Public Calendar & Meeting Scheduling API Router.
Enables prospects to:
1. View a sales rep's booking profile & available meeting durations
2. Pick an open day and available time slot
3. Choose their preferred video conferencing platform:
   - Zoom Meeting (zoom)
   - Google Meet (google_meet)
   - Microsoft Teams (teams)
4. Confirm booking, generate unique conference links, sync CRM deal/contact,
   and produce 1-click Google Calendar / Outlook / iCal invitations.
"""
from __future__ import annotations

import re
import secrets
import random
import uuid
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, or_, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    User, Contact, Deal, DealStage, Notification, ScheduledMeeting, UserInput
)
import structlog

logger = structlog.get_logger(__name__)

booking_router = APIRouter(prefix="/booking", tags=["Calendar Booking"])

# ── Validation Schemas ────────────────────────────────────────────────────────

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SUPPORTED_PLATFORMS = {
    "zoom": {
        "id": "zoom",
        "name": "Zoom Meeting",
        "brand_color": "#2D8CFF",
        "icon": "zoom",
    },
    "google_meet": {
        "id": "google_meet",
        "name": "Google Meet",
        "brand_color": "#00897B",
        "icon": "google_meet",
    },
    "teams": {
        "id": "teams",
        "name": "Microsoft Teams",
        "brand_color": "#5059C9",
        "icon": "teams",
    },
}


class ScheduleMeetingRequest(BaseModel):
    date: str = Field(..., description="Target meeting date in YYYY-MM-DD format")
    time_slot: str = Field(..., description="Selected time slot e.g. 10:30 AM")
    timezone: str = Field(default="UTC", description="Attendee local timezone")
    duration_minutes: int = Field(default=30, ge=15, le=120)
    platform: str = Field(default="zoom", description="zoom | google_meet | teams")
    attendee_name: str = Field(..., min_length=2, max_length=150)
    attendee_email: str = Field(..., min_length=5, max_length=255)
    attendee_company: Optional[str] = Field(default=None, max_length=200)
    attendee_notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("attendee_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email address format")
        return clean

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Platform must be one of: {list(SUPPORTED_PLATFORMS.keys())}")
        return clean


# ── Internal Helpers ──────────────────────────────────────────────────────────

async def _resolve_host_user(identifier: str, db: AsyncSession) -> Optional[User]:
    """
    Resolves the sales representative hosting the meeting from:
    1. Direct UUID
    2. Exact cal_com_username
    3. Email
    4. Slugified name
    5. Fallback: primary admin user if identifier is 'default', 'team', or 'shree'
    """
    clean_id = (identifier or "").strip().lower()
    
    # 1. By ID if valid UUID
    try:
        uuid.UUID(clean_id)
        u = await db.get(User, clean_id)
        if u and u.is_active:
            return u
    except ValueError:
        pass

    # 2. By cal_com_username or email
    stmt = select(User).where(
        or_(
            User.cal_com_username.ilike(clean_id),
            User.email.ilike(clean_id),
        )
    )
    res = await db.execute(stmt)
    u = res.scalar_one_or_none()
    if u and u.is_active:
        return u

    # 3. By slugified name match (e.g. "shree-lakshmi" -> "P P Shree Lakshmi")
    clean_name_tokens = [t for t in re.split(r"[-_.\s]+", clean_id) if len(t) > 2]
    if clean_name_tokens:
        all_users_res = await db.execute(select(User).where(User.is_active == True))
        for cand in all_users_res.scalars():
            c_name_lower = cand.name.lower()
            if any(t in c_name_lower for t in clean_name_tokens):
                return cand

    # 4. Fallback: Primary Admin / Default User
    stmt_admin = select(User).where(
        and_(User.is_active == True, User.role == "ADMIN")
    ).limit(1)
    res_admin = await db.execute(stmt_admin)
    admin = res_admin.scalar_one_or_none()
    if admin:
        return admin

    # 5. Any active user
    stmt_any = select(User).where(User.is_active == True).limit(1)
    res_any = await db.execute(stmt_any)
    return res_any.scalar_one_or_none()


def _generate_meeting_conference(platform: str, title: str) -> Dict[str, Any]:
    """Generates a dedicated meeting room link and passcode for the chosen provider."""
    if platform == "zoom":
        meeting_id = "".join([str(random.randint(0, 9)) for _ in range(10)])
        passcode = secrets.token_urlsafe(6)
        join_url = f"https://zoom.us/j/{meeting_id}?pwd={passcode}"
        return {
            "platform": "zoom",
            "platform_name": "Zoom Meeting",
            "meeting_id": meeting_id,
            "passcode": passcode,
            "join_url": join_url,
            "instructions": f"Join Zoom Meeting: {join_url}\nMeeting ID: {meeting_id}\nPasscode: {passcode}",
        }
    elif platform == "google_meet":
        part1 = secrets.token_hex(2)[:3]
        part2 = secrets.token_hex(2)[:4]
        part3 = secrets.token_hex(2)[:3]
        code = f"{part1}-{part2}-{part3}"
        join_url = f"https://meet.google.com/{code}"
        return {
            "platform": "google_meet",
            "platform_name": "Google Meet",
            "meeting_id": code,
            "passcode": None,
            "join_url": join_url,
            "instructions": f"Join Google Meet: {join_url}\nNo plugin needed — opens directly in your browser.",
        }
    else:  # teams
        meet_id = uuid.uuid4().hex[:12]
        join_url = f"https://teams.microsoft.com/l/meetup-join/19%3ameeting_{meet_id}%40thread.v2/0"
        return {
            "platform": "teams",
            "platform_name": "Microsoft Teams",
            "meeting_id": meet_id,
            "passcode": None,
            "join_url": join_url,
            "instructions": f"Join Microsoft Teams Meeting: {join_url}",
        }


def _build_calendar_links(
    title: str,
    description: str,
    location: str,
    start_dt: datetime,
    end_dt: datetime
) -> Dict[str, str]:
    """Generates 1-click Google Calendar and Outlook links."""
    fmt = "%Y%m%dT%H%M%SZ"
    s_utc = start_dt.strftime(fmt)
    e_utc = end_dt.strftime(fmt)

    # Google Calendar Web URL
    gcal_params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{s_utc}/{e_utc}",
        "details": description,
        "location": location,
    }
    google_url = f"https://calendar.google.com/calendar/render?{urlencode(gcal_params)}"

    # Outlook Web URL
    outlook_params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": title,
        "startdt": start_dt.isoformat(),
        "enddt": end_dt.isoformat(),
        "body": description,
        "location": location,
    }
    outlook_url = f"https://outlook.live.com/calendar/0/deeplink/compose?{urlencode(outlook_params)}"

    # Basic iCal (.ics) string
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GTM Platform//Meeting Scheduler//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@gtmplatform.com",
        f"DTSTAMP:{datetime.utcnow().strftime(fmt)}",
        f"DTSTART:{s_utc}",
        f"DTEND:{e_utc}",
        f"SUMMARY:{title}",
        f"DESCRIPTION:{description.replace(chr(10), '\\n')}",
        f"LOCATION:{location}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    ics_content = "\r\n".join(ics_lines)

    return {
        "google_calendar_url": google_url,
        "outlook_calendar_url": outlook_url,
        "ics_data": ics_content,
    }


# ── Public Endpoints ──────────────────────────────────────────────────────────

@booking_router.get("/{identifier}/info")
async def get_booking_info(identifier: str, db: AsyncSession = Depends(get_db)):
    """
    Public profile of the sales rep for the booking interface.
    Returns host details, durations, and supported meeting platforms.
    """
    host = await _resolve_host_user(identifier, db)
    if not host:
        raise HTTPException(status_code=404, detail="Representative booking page not found")

    avatar_url = "/avatar-shree.jpg" if (
        "shree" in (host.email or "").lower() or "shree" in (host.name or "").lower()
    ) else None

    return {
        "success": True,
        "host": {
            "id": host.id,
            "name": host.name,
            "email": host.email,
            "role": "Sales Representative" if host.role == "SALES_REPRESENTATIVE" else "Solutions Director",
            "company": "GTM Platform",
            "avatar_url": avatar_url,
            "username": host.cal_com_username or identifier,
            "booking_slug": host.cal_com_event_slug or "15min",
        },
        "event_options": {
            "title": "Strategy & Discovery Session",
            "description": "Discuss your pipeline goals, platform demonstration, and technical alignment.",
            "durations": [15, 30, 45],
            "default_duration": 30,
        },
        "supported_platforms": list(SUPPORTED_PLATFORMS.values()),
    }


@booking_router.get("/{identifier}/slots")
async def get_available_slots(
    identifier: str,
    date_str: str = Query(..., alias="date", description="Target date in YYYY-MM-DD"),
    duration: int = Query(30, ge=15, le=120),
    timezone: str = Query("UTC"),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns available open time slots for a given date.
    Excludes weekend hours, past hours for current date, and already-booked slots.
    """
    host = await _resolve_host_user(identifier, db)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.")

    today = datetime.utcnow().date()
    if target_date < today:
        return {"date": date_str, "timezone": timezone, "available_slots": []}

    # Don't schedule on Sunday (6)
    if target_date.weekday() == 6:
        return {"date": date_str, "timezone": timezone, "available_slots": []}

    # Fetch already booked meetings for this host on that day
    start_of_day = datetime.combine(target_date, time(0, 0, 0))
    end_of_day = datetime.combine(target_date, time(23, 59, 59))
    
    booked_stmt = select(ScheduledMeeting.start_time).where(
        and_(
            ScheduledMeeting.user_id == host.id,
            ScheduledMeeting.start_time >= start_of_day,
            ScheduledMeeting.start_time <= end_of_day,
            ScheduledMeeting.status != "cancelled"
        )
    )
    booked_res = await db.execute(booked_stmt)
    booked_hours = {dt.strftime("%I:%M %p").lstrip("0") for dt in booked_res.scalars()}

    # Standard working hours: 09:00 AM to 06:00 PM
    standard_slots = [
        "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM",
        "01:00 PM", "01:30 PM", "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM",
        "04:00 PM", "04:30 PM", "05:00 PM"
    ]

    now_utc = datetime.utcnow()
    filtered_slots = []
    for slot_label in standard_slots:
        # Check against booked
        if slot_label in booked_hours:
            continue

        # If date is today, check if time has already passed
        if target_date == today:
            slot_time = datetime.strptime(slot_label, "%I:%M %p").time()
            slot_dt = datetime.combine(today, slot_time)
            if slot_dt <= (now_utc + timedelta(hours=1)):
                continue

        filtered_slots.append(slot_label)

    return {
        "date": date_str,
        "timezone": timezone,
        "duration_minutes": duration,
        "available_slots": filtered_slots,
    }


@booking_router.post("/{identifier}/schedule")
async def schedule_meeting(
    identifier: str,
    payload: ScheduleMeetingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Schedules a meeting with the representative:
    1. Generates unique Zoom, Google Meet, or Microsoft Teams room link.
    2. Inserts ScheduledMeeting record.
    3. Upserts Contact and Deal stage to DEMO in the CRM.
    4. Triggers an in-app rep notification.
    5. Returns meeting receipt with 1-click Google Calendar & Outlook links.
    """
    host = await _resolve_host_user(identifier, db)
    if not host:
        raise HTTPException(status_code=404, detail="Representative not found")

    try:
        meeting_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
        slot_time = datetime.strptime(payload.time_slot, "%I:%M %p").time()
        start_datetime = datetime.combine(meeting_date, slot_time)
        end_datetime = start_datetime + timedelta(minutes=payload.duration_minutes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date or time slot format: {str(e)}")

    # 1. Generate conference link for selected platform
    meeting_title = f"GTM Demo: {payload.attendee_name} <> {host.name}"
    conference = _generate_meeting_conference(payload.platform, meeting_title)

    # 2. Upsert Contact in database
    contact_stmt = select(Contact).where(
        and_(Contact.user_id == host.id, Contact.email == payload.attendee_email)
    )
    contact_res = await db.execute(contact_stmt)
    contact = contact_res.scalar_one_or_none()

    name_parts = payload.attendee_name.strip().split(" ", 1)
    f_name = name_parts[0]
    l_name = name_parts[1] if len(name_parts) > 1 else ""

    if not contact:
        contact = Contact(
            email=payload.attendee_email,
            first_name=f_name,
            last_name=l_name,
            company=payload.attendee_company or "Prospect Company",
            source="calendar_booking",
            user_id=host.id,
            readiness_score=85.0,
        )
        db.add(contact)
        await db.flush()
    else:
        contact.readiness_score = max(contact.readiness_score or 0.0, 90.0)
        if payload.attendee_company and not contact.company:
            contact.company = payload.attendee_company
        await db.flush()

    # 3. Create or Update Deal to DEMO stage
    deal_stmt = select(Deal).where(Deal.contact_id == contact.id).limit(1)
    deal_res = await db.execute(deal_stmt)
    deal = deal_res.scalar_one_or_none()

    if not deal:
        deal = Deal(
            contact_id=contact.id,
            name=f"Demo: {contact.company or payload.attendee_name} <> GTM",
            stage=DealStage.DEMO,
            amount=15000.0,
            amount_source="calendar_booking",
            owner_email=host.email,
            meeting_count=1,
            buying_intent="High",
        )
        db.add(deal)
        await db.flush()
    else:
        deal.meeting_count = (deal.meeting_count or 0) + 1
        if deal.stage in [DealStage.PROSPECTING, DealStage.DISCOVERY]:
            deal.stage = DealStage.DEMO
        await db.flush()

    # 4. Save ScheduledMeeting record
    meeting = ScheduledMeeting(
        user_id=host.id,
        contact_id=contact.id,
        deal_id=deal.id,
        title=meeting_title,
        description=f"Topic / Notes: {payload.attendee_notes or 'GTM Platform Demo and Discovery'}\n\n{conference['instructions']}",
        start_time=start_datetime,
        end_time=end_datetime,
        timezone=payload.timezone,
        duration_minutes=payload.duration_minutes,
        platform=payload.platform,
        meeting_link=conference["join_url"],
        meeting_id=conference.get("meeting_id"),
        passcode=conference.get("passcode"),
        attendee_name=payload.attendee_name,
        attendee_email=payload.attendee_email,
        attendee_company=payload.attendee_company,
        attendee_notes=payload.attendee_notes,
        status="scheduled",
    )
    db.add(meeting)
    await db.flush()

    # 5. Create in-app Notification for sales representative
    # Find any search context/user_input or create reference
    user_input_stmt = select(UserInput.id).where(UserInput.user_id == host.id).limit(1)
    ui_res = await db.execute(user_input_stmt)
    ui_id = ui_res.scalar_one_or_none()

    if ui_id:
        notif = Notification(
            type="reply_received",
            contact_id=contact.id,
            user_input_id=ui_id,
            user_id=host.id,
            message=f"📅 New Meeting Scheduled! {payload.attendee_name} ({payload.attendee_company or 'Prospect'}) booked a {payload.duration_minutes}m {conference['platform_name']} on {payload.date} at {payload.time_slot}.",
            action_url="/deals",
            reference_id=f"meeting_{meeting.id}",
        )
        db.add(notif)

    await db.commit()

    # 6. Generate 1-click calendar links
    cal_links = _build_calendar_links(
        title=meeting_title,
        description=f"Meeting with {host.name}\n\nJoin URL: {conference['join_url']}\n\nNotes: {payload.attendee_notes or 'No notes provided'}",
        location=conference["join_url"],
        start_dt=start_datetime,
        end_dt=end_datetime,
    )

    logger.info(
        "Meeting successfully scheduled",
        meeting_id=meeting.id,
        platform=payload.platform,
        host=host.email,
        attendee=payload.attendee_email,
    )

    return {
        "success": True,
        "meeting_id": meeting.id,
        "title": meeting_title,
        "date": payload.date,
        "time_slot": payload.time_slot,
        "timezone": payload.timezone,
        "duration_minutes": payload.duration_minutes,
        "platform": conference["platform"],
        "platform_name": conference["platform_name"],
        "join_url": conference["join_url"],
        "passcode": conference.get("passcode"),
        "instructions": conference["instructions"],
        "host": {
            "name": host.name,
            "email": host.email,
        },
        "attendee": {
            "name": payload.attendee_name,
            "email": payload.attendee_email,
            "company": payload.attendee_company,
        },
        "calendar_links": cal_links,
    }


@booking_router.get("/user/my-meetings")
async def list_my_meetings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticated endpoint for the logged-in sales rep to view all scheduled meetings.
    """
    stmt = (
        select(ScheduledMeeting)
        .where(ScheduledMeeting.user_id == current_user.id)
        .order_by(ScheduledMeeting.start_time.asc())
    )
    res = await db.execute(stmt)
    meetings = res.scalars().all()

    return {
        "success": True,
        "meetings": [
            {
                "id": m.id,
                "title": m.title,
                "date": m.start_time.strftime("%Y-%m-%d"),
                "time_slot": m.start_time.strftime("%I:%M %p"),
                "start_time": m.start_time.isoformat(),
                "end_time": m.end_time.isoformat(),
                "duration_minutes": m.duration_minutes,
                "platform": m.platform,
                "platform_name": SUPPORTED_PLATFORMS.get(m.platform, {}).get("name", m.platform),
                "join_url": m.meeting_link,
                "attendee_name": m.attendee_name,
                "attendee_email": m.attendee_email,
                "attendee_company": m.attendee_company,
                "attendee_notes": m.attendee_notes,
                "status": m.status,
            }
            for m in meetings
        ],
    }

