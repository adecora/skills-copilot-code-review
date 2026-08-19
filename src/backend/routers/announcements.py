"""
Announcement endpoints for the High School Management System API
"""

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementInput(BaseModel):
    message: str
    start_date: Optional[str] = None
    expiration_date: str

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Announcement message cannot be empty")
        return value.strip()

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, value: Optional[str]) -> Optional[str]:
        return _validate_iso_date(value, "start_date") if value else None

    @field_validator("expiration_date")
    @classmethod
    def validate_expiration_date(cls, value: str) -> str:
        return _validate_iso_date(value, "expiration_date")


def _validate_iso_date(value: str, field_name: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a valid date (YYYY-MM-DD)")
    return value


def _require_teacher(teacher_username: Optional[str]) -> None:
    """Ensure the request comes from a signed-in teacher/admin account"""
    if not teacher_username or not teachers_collection.find_one({"_id": teacher_username}):
        raise HTTPException(
            status_code=401, detail="Authentication required for this action")


def _serialize(announcement: Dict[str, Any]) -> Dict[str, Any]:
    announcement = dict(announcement)
    announcement["id"] = announcement.pop("_id")
    return announcement


def _is_active(announcement: Dict[str, Any], today: date) -> bool:
    start_date = announcement.get("start_date")
    if start_date and date.fromisoformat(start_date) > today:
        return False

    expiration_date = announcement.get("expiration_date")
    return not (expiration_date and date.fromisoformat(expiration_date) < today)


@router.get("/active", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get announcements that are currently visible to all visitors"""
    today = date.today()
    active = [a for a in announcements_collection.find() if _is_active(a, today)]
    active.sort(key=lambda a: a["expiration_date"])
    return [_serialize(a) for a in active]


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Get every announcement - requires teacher authentication"""
    _require_teacher(teacher_username)
    announcements = announcements_collection.find().sort("expiration_date", 1)
    return [_serialize(a) for a in announcements]


@router.post("", response_model=Dict[str, Any])
@router.post("/", response_model=Dict[str, Any])
def create_announcement(
    announcement: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create a new announcement - requires teacher authentication"""
    _require_teacher(teacher_username)
    _validate_date_order(announcement)

    new_announcement = {
        "_id": uuid4().hex,
        "message": announcement.message,
        "start_date": announcement.start_date,
        "expiration_date": announcement.expiration_date,
        "created_by": teacher_username
    }
    announcements_collection.insert_one(new_announcement)
    return _serialize(new_announcement)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    announcement: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement - requires teacher authentication"""
    _require_teacher(teacher_username)
    _validate_date_order(announcement)

    existing = announcements_collection.find_one({"_id": announcement_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated_fields = {
        "message": announcement.message,
        "start_date": announcement.start_date,
        "expiration_date": announcement.expiration_date
    }
    announcements_collection.update_one(
        {"_id": announcement_id}, {"$set": updated_fields})
    existing.update(updated_fields)
    return _serialize(existing)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement - requires teacher authentication"""
    _require_teacher(teacher_username)

    result = announcements_collection.delete_one({"_id": announcement_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}


def _validate_date_order(announcement: AnnouncementInput) -> None:
    if announcement.start_date and announcement.start_date > announcement.expiration_date:
        raise HTTPException(
            status_code=400,
            detail="Start date must be on or before the expiration date")
