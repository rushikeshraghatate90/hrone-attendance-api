"""HROne Employee Attendance & Analytics API.

Configuration: MONGO_URI and MONGO_DB (environment variables override .env).
All API timestamps are Unix epoch milliseconds; attendance calendar dates use IST.
"""
from __future__ import annotations
from fastapi.responses import Response

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from zoneinfo import ZoneInfo
from bson import json_util

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI must be configured in the environment or .env file")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000, tz_aware=True, tzinfo=timezone.utc)
db = client[MONGO_DB]
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
PRESENT_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}
ALL_STATUSES = PRESENT_STATUSES | {"ABSENT", "LEAVE"}
MAX_EPOCH_MS = 4102444800000
MIN_EPOCH_MS = 100000000000
app = FastAPI(title="HROne Employee Attendance & Analytics API", version="1.0.0")


def fail(status: int, detail: str):
    raise HTTPException(status, detail)


def parse_date(value: str) -> date:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        fail(422, "Date must be a valid YYYY-MM-DD value")


def parse_month(value: str) -> tuple[date, date]:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        fail(422, "Month must use YYYY-MM format")
    try:
        start = date.fromisoformat(value + "-01")
    except ValueError:
        fail(422, "Month must use YYYY-MM format")
    end = (date(start.year + (start.month == 12), start.month % 12 + 1, 1) - timedelta(days=1))
    return start, end


def parse_shift(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("Time must use HH:MM (24-hour format)")
    return value


def epoch_ms_to_utc(value: Any) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int) or value < MIN_EPOCH_MS or value > MAX_EPOCH_MS:
        fail(422, "Timestamp must be an integer epoch-millisecond value in the supported range")
    return datetime.fromtimestamp(value // 1000, UTC)


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_epoch_ms(value: datetime) -> int:
    return int(utc_datetime(value).timestamp()) * 1000


def response_doc(value: Any) -> Any:
    if isinstance(value, datetime):
        return to_epoch_ms(value)
    if isinstance(value, list):
        return [response_doc(v) for v in value]
    if isinstance(value, dict):
        return {k: response_doc(v) for k, v in value.items() if k != "_id"}
    return value


def round_half_up(value: float | Decimal, places: int = 2) -> float:
    quant = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def ist_datetime(day: str, shift: str) -> datetime:
    h, m = map(int, shift.split(":"))
    return datetime.combine(date.fromisoformat(day), time(h, m), IST).astimezone(UTC)


def attendance_day(punch_in: datetime, employee: dict) -> str:
    local = utc_datetime(punch_in).astimezone(IST)
    shift_end = employee.get("shift_end", "18:30")
    start = employee.get("shift_start", "09:30")
    if shift_end <= start and local.strftime("%H:%M") < shift_end:
        return (local.date() - timedelta(days=1)).isoformat()
    return local.date().isoformat()


def shift_bounds(day: str, employee: dict) -> tuple[datetime, datetime]:
    start = ist_datetime(day, employee.get("shift_start", "09:30"))
    end = ist_datetime(day, employee.get("shift_end", "18:30"))
    if employee.get("shift_end", "18:30") <= employee.get("shift_start", "09:30"):
        end += timedelta(days=1)
    return start, end


def compute_derived(employee: dict, day: str, punch_in: Optional[datetime], punch_out: Optional[datetime]) -> dict:
    if punch_in is None or punch_out is None:
        return {"work_hours": None, "late_minutes": 0, "overtime_minutes": 0, "half_day": False}
    punch_in, punch_out = utc_datetime(punch_in).replace(microsecond=0), utc_datetime(punch_out).replace(microsecond=0)
    shift_start, shift_end = shift_bounds(day, employee)
    late_seconds = (punch_in - shift_start).total_seconds()
    late = int(late_seconds // 60) if late_seconds > 600 else 0
    work_seconds = (punch_out - punch_in).total_seconds()
    work_hours = round_half_up(work_seconds / 3600, 2)
    overtime_seconds = (punch_out - shift_end).total_seconds()
    overtime = int(overtime_seconds // 60) if overtime_seconds >= 1800 else 0
    return {"work_hours": work_hours, "late_minutes": late, "overtime_minutes": max(0, overtime), "half_day": work_hours < 4.5}


def require_employee(emp_code: str) -> dict:
    try:
        employee = db.employees.find_one({"emp_code": emp_code})
    except PyMongoError:
        fail(503, "Database operation failed")
    if employee is None:
        fail(404, "Employee not found")
    return employee


def validate_pagination(page: int, page_size: int):
    if page < 1 or page_size < 1 or page_size > 100:
        fail(422, "page must be >= 1 and page_size must be between 1 and 100")


def is_workday(day: date) -> bool:
    return day.weekday() < 5


def working_days(start: date, end: date) -> int:
    return sum(1 for n in range((end - start).days + 1) if is_workday(start + timedelta(days=n)))


class EmployeeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=120, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("shift_start", "shift_end")
    @classmethod
    def shift_format(cls, v):
        try: return parse_shift(v)
        except ValueError as exc: raise ValueError(str(exc))

    @field_validator("joined_on")
    @classmethod
    def valid_joined_on(cls, v):
        parse_date(v); return v

    @model_validator(mode="after")
    def shifts_differ(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must differ")
        return self


class PunchInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("punched_at", mode="before")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None: epoch_ms_to_utc(v)
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v):
        if v not in PRESENT_STATUSES: raise ValueError("status must be PRESENT, WFH, or ON_DUTY")
        return v


class PunchOutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("punched_at", mode="before")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None: epoch_ms_to_utc(v)
        return v


class RegularizationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v):
        if v is not None and v not in ALL_STATUSES: raise ValueError("Invalid attendance status")
        return v

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def valid_timestamp(cls, v):
        if v is not None: epoch_ms_to_utc(v)
        return v


@app.on_event("startup")
def create_indexes():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="ix_employee_department_code")
    db.employees.create_index([("joined_on", ASCENDING), ("department", ASCENDING)], name="ix_employee_joined_department")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_employee")
    db.attendance_logs.create_index([("status", ASCENDING), ("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_status_date_employee")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("punch_in", DESCENDING)], name="ix_attendance_punchout_lookup")


@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        fail(503, "Database unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC).replace(microsecond=0)
    try: db.employees.insert_one(doc)
    except DuplicateKeyError: fail(409, "emp_code already exists")
    except PyMongoError: fail(503, "Database operation failed")
    return response_doc(doc)


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    query = {"department": department} if department is not None else {}
    try:
        total = db.employees.count_documents(query)
        items = list(db.employees.find(query, {"_id": 0}).sort("emp_code", ASCENDING).skip((page-1)*page_size).limit(page_size))
    except PyMongoError: fail(503, "Database operation failed")
    return {"items": response_doc(items), "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    employee = require_employee(body.emp_code)
    instant = datetime.now(UTC).replace(microsecond=0) if body.punched_at is None else epoch_ms_to_utc(body.punched_at)
    day = attendance_day(instant, employee)
    derived = compute_derived(employee, day, instant, None)
    doc = {"emp_code": body.emp_code, "date": day, "status": body.status, "punch_in": instant, "punch_out": None, **derived, "history": []}
    try: db.attendance_logs.insert_one(doc)
    except DuplicateKeyError: fail(409, "already punched in for this attendance date")
    except PyMongoError: fail(503, "Database operation failed")
    doc["id"] = str(doc.pop("_id")) if "_id" in doc else ""
    # insert_one mutates neither doc nor _id in all driver versions; fetch the inserted record for stable id.
    saved = db.attendance_logs.find_one({"emp_code": body.emp_code, "date": day}, {"_id": 1})
    if saved: doc["id"] = str(saved["_id"])
    return response_doc(doc)


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    employee = require_employee(body.emp_code)
    instant = datetime.now(UTC).replace(microsecond=0) if body.punched_at is None else epoch_ms_to_utc(body.punched_at)
    base = {"emp_code": body.emp_code, "status": {"$in": list(PRESENT_STATUSES)}, "punch_in": {"$ne": None, "$lte": instant}}
    try:
        record = db.attendance_logs.find_one({**base, "punch_out": None}, sort=[("punch_in", DESCENDING)])
        if record is None:
            closed = db.attendance_logs.find_one({**base, "punch_out": {"$ne": None}}, sort=[("punch_in", DESCENDING)])
            if closed: fail(409, "Attendance record already punched out")
            fail(404, "No open attendance record found")
        pin = utc_datetime(record["punch_in"])
        elapsed = (instant - pin).total_seconds()
        if elapsed <= 0 or elapsed > 86400: fail(422, "Punch-out must be after punch-in and within 24 hours")
        derived = compute_derived(employee, record["date"], pin, instant)
        updated = db.attendance_logs.find_one_and_update({"_id": record["_id"], "punch_out": None, "punch_in": record["punch_in"]}, {"$set": {"punch_out": instant, **derived}}, return_document=ReturnDocument.AFTER)
    except PyMongoError: fail(503, "Database operation failed")
    if updated is None: fail(409, "Attendance record was updated by another request")
    return response_doc(updated)


@app.get("/attendance")
def list_attendance(emp_code: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None, status: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    query: dict[str, Any] = {}
    if emp_code is not None: query["emp_code"] = emp_code
    if date_from:
        parse_date(date_from); query.setdefault("date", {})["$gte"] = date_from
    if date_to:
        parse_date(date_to); query.setdefault("date", {})["$lte"] = date_to
    if date_from and date_to and date_from > date_to: fail(422, "date_from must be on or before date_to")
    if status is not None:
        if status not in ALL_STATUSES: fail(422, "Invalid attendance status")
        query["status"] = status
    try:
        total = db.attendance_logs.count_documents(query)
        docs = list(db.attendance_logs.find(query).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page-1)*page_size).limit(page_size))
    except PyMongoError: fail(503, "Database operation failed")
    for d in docs: d["id"] = str(d.pop("_id"))
    return {"items": response_doc(docs), "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{day}")
def regularize_attendance(emp_code: str, day: str, body: RegularizationIn):
    parse_date(day)
    require_employee(emp_code)
    try: old = db.attendance_logs.find_one({"emp_code": emp_code, "date": day})
    except PyMongoError: fail(503, "Database operation failed")
    if old is None: fail(404, "Attendance record not found")
    employee = require_employee(emp_code)
    new_status = body.status if body.status is not None else old["status"]
    pin = epoch_ms_to_utc(body.punch_in) if body.punch_in is not None else old.get("punch_in")
    pout = epoch_ms_to_utc(body.punch_out) if body.punch_out is not None else old.get("punch_out")
    if new_status in {"ABSENT", "LEAVE"}:
        if body.punch_in is not None or body.punch_out is not None: fail(422, "ABSENT/LEAVE cannot include punch timestamps")
        pin = pout = None
        derived = {"work_hours": None, "late_minutes": 0, "overtime_minutes": 0, "half_day": False}
    else:
        if pin is None: fail(422, "A present status requires punch_in")
        if attendance_day(pin, employee) != day: fail(422, "punch_in must belong to the attendance date")
        if pout is not None:
            secs = (pout-pin).total_seconds()
            if secs <= 0 or secs > 86400: fail(422, "punch_out must be after punch_in and within 24 hours")
        derived = compute_derived(employee, day, pin, pout)
    changes = {}
    proposed = {"status": new_status, "punch_in": pin, "punch_out": pout, **derived}
    for key, value in proposed.items():
        if old.get(key) != value: changes[key] = {"from": old.get(key), "to": value}
    if not changes: fail(422, "Regularization does not change the record")
    history_entry = {"at": datetime.now(UTC).replace(microsecond=0), "by": body.regularized_by, "reason": body.reason, "changes": changes}
    try:
        updated = db.attendance_logs.find_one_and_update({"_id": old["_id"], "history": old.get("history", [])}, {"$set": proposed, "$push": {"history": history_entry}}, return_document=ReturnDocument.AFTER)
    except PyMongoError: fail(503, "Database operation failed")
    if updated is None: fail(409, "Attendance record changed concurrently; retry regularization")
    updated["id"] = str(updated.pop("_id"))
    return response_doc(updated)


def present_match():
    return {"$in": list(PRESENT_STATUSES)}


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., pattern=r"^\d{4}-\d{2}$")):
    employee = require_employee(emp_code)
    start, end = parse_month(month)
    effective_start = max(start, parse_date(employee["joined_on"]))
    wd = working_days(effective_start, end) if effective_start <= end else 0
    pipeline = [
        {"$match": {"emp_code": emp_code, "date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}},
        {"$group": {"_id": None,
            "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$status", list(PRESENT_STATUSES)]}, {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2,3,4,5,6]]}]}, {"$cond": ["$half_day", 0.5, 1]}, 0]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": "$late_minutes"}, "total_overtime_minutes": {"$sum": "$overtime_minutes"}}}
    ]
    try: rows = list(db.attendance_logs.aggregate(pipeline))
    except PyMongoError: fail(503, "Database operation failed")
    r = rows[0] if rows else {}
    pd = r.get("present_days", 0)
    return {"emp_code": emp_code, "month": month, "working_days": wd, "present_days": pd, "leave_days": r.get("leave_days", 0), "late_count": r.get("late_count", 0), "total_late_minutes": r.get("total_late_minutes", 0), "total_overtime_minutes": r.get("total_overtime_minutes", 0), "attendance_pct": None if wd == 0 else round_half_up(pd / wd * 100, 2)}


@app.get("/analytics/departments/summary")
def department_summary(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), department: Optional[str] = None):
    start, end = parse_month(month)
    match = {"joined_on": {"$lte": end.isoformat()}}
    if department is not None: match["department"] = department
    pipeline = [
        {"$match": match},
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", start.isoformat()]}, {"$lte": ["$date", end.isoformat()]}]}}}], "as": "logs"}},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": "$department", "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$logs.status", list(PRESENT_STATUSES)]}, {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$logs.date"}}}, [2,3,4,5,6]]}]}, {"$cond": ["$logs.half_day", 0.5, 1]}, 0]}},
            "hours": {"$push": {"$cond": [{"$and": [{"$in": ["$logs.status", list(PRESENT_STATUSES)]}, {"$ne": ["$logs.work_hours", None]}]}, "$logs.work_hours", None]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$logs.late_minutes", 0]}, 1, 0]}}, "total_late_minutes": {"$sum": {"$ifNull": ["$logs.late_minutes", 0]}},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}}, "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}}}},
        {"$project": {"_id": 0, "department": "$_id", "headcount": {"$size": "$headcount"}, "present_days": 1, "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1, "avg_work_hours": {"$let": {"vars": {"valid": {"$filter": {"input": "$hours", "as": "h", "cond": {"$ne": ["$$h", None]}}}}, "in": {"$cond": [{"$gt": [{"$size": "$$valid"}, 0]}, {"$round": [{"$avg": "$$valid"}, 2]}, None]}}}}},
        {"$match": {"headcount": {"$gt": 0}}}, {"$sort": {"department": 1}}
    ]
    try: rows = list(db.employees.aggregate(pipeline))
    except PyMongoError: fail(503, "Database operation failed")
    for row in rows:
        if row.get("avg_work_hours") is not None: row["avg_work_hours"] = round_half_up(row["avg_work_hours"], 2)
    return {"month": month, "items": rows}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), limit: int = Query(10, ge=1, le=50), department: Optional[str] = None):
    start, end = parse_month(month)
    pipeline = [
        {"$match": {"date": {"$gte": start.isoformat(), "$lte": end.isoformat()}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}}, {"$unwind": "$employee"},
    ]
    if department is not None: pipeline.append({"$match": {"employee.department": department}})
    pipeline += [{"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}}, {"$match": {"rank": {"$lte": limit}}}, {"$sort": {"total_late_minutes": -1, "_id": 1}}, {"$project": {"_id": 0, "emp_code": "$_id", "name": "$employee.name", "department": "$employee.department", "total_late_minutes": 1, "rank": 1}}]
    try: rows = list(db.attendance_logs.aggregate(pipeline))
    except PyMongoError: fail(503, "Database operation failed")
    return {"month": month, "limit": limit, "items": rows}


@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_date: str = Query(..., alias="from"), to_date: str = Query(..., alias="to")):
    first, last = parse_date(from_date), parse_date(to_date)
    if last < first: fail(422, "to must be on or after from")
    if (last-first).days > 91: fail(422, "Date range cannot exceed 92 days")
    try: exists = db.employees.find_one({"department": department}, {"_id": 1})
    except PyMongoError: fail(503, "Database operation failed")
    if exists is None: fail(404, "Department not found")
    pipeline = [
        {"$match": {"department": department, "joined_on": {"$lte": last.isoformat()}}},
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", first.isoformat()]}, {"$lte": ["$date", last.isoformat()]}]}}}], "as": "logs"}},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": {"$ifNull": ["$logs.date", None]}, "headcount": {"$addToSet": "$emp_code"}, "present_count": {"$sum": {"$cond": [{"$in": ["$logs.status", list(PRESENT_STATUSES)]}, {"$cond": ["$logs.half_day", 0.5, 1]}, 0]}}, "late_count": {"$sum": {"$cond": [{"$gt": ["$logs.late_minutes", 0]}, 1, 0]}}}},
        {"$match": {"_id": {"$ne": None}}}, {"$sort": {"_id": 1}}
    ]
    # Build the dense daily series inside MongoDB; no attendance documents are fetched for Python-side iteration.
    densify = [{"$documents": [{"start": datetime.combine(first, time.min, UTC), "end": datetime.combine(last, time.min, UTC)}]}, {"$project": {"days": {"$map": {"input": {"$range": [0, (last-first).days+1]}, "as": "i", "in": {"$dateToString": {"date": {"$dateAdd": {"startDate": "$start", "unit": "day", "amount": "$$i"}}, "format": "%Y-%m-%d", "timezone": "UTC"}}}}}}, {"$unwind": "$days"}, {"$project": {"_id": 0, "date": "$days"}}, {"$lookup": {"from": "employees", "let": {"d": "$date"}, "pipeline": [{"$match": {"department": department, "$expr": {"$lte": ["$joined_on", "$$d"]}}}, {"$count": "n"}], "as": "hc"}}, {"$lookup": {"from": "attendance_logs", "let": {"d": "$date"}, "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$date", "$$d"]}, {"$in": ["$emp_code", {"$map": {"input": {"$filter": {"input": {"$literal": []}, "as": "x", "cond": True}}, "as": "y", "in": "$$y"}}]}]}}}], "as": "unused"}}]
    # Use a single aggregation pipeline with a generated date axis and per-day lookups.
    trend_pipeline = [
        {"$documents": [{"start": datetime.combine(first, time.min, UTC), "end": datetime.combine(last, time.min, UTC)}]},
        {"$project": {"days": {"$map": {"input": {"$range": [0, (last-first).days+1]}, "as": "i", "in": {"$dateToString": {"date": {"$dateAdd": {"startDate": "$start", "unit": "day", "amount": "$$i"}}, "format": "%Y-%m-%d", "timezone": "UTC"}}}}}},
        {"$unwind": "$days"}, {"$project": {"_id": 0, "date": "$days"}},
        {"$lookup": {"from": "employees", "let": {"d": "$date"}, "pipeline": [{"$match": {"department": department, "$expr": {"$lte": ["$joined_on", "$$d"]}}}, {"$count": "n"}], "as": "hc"}},
        {"$lookup": {"from": "attendance_logs", "let": {"d": "$date"}, "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$date", "$$d"]}, {"$in": ["$emp_code", {"$let": {"vars": {"employees": []}, "in": "$$employees"}}]}]}}}], "as": "logs"}},
        {"$project": {"date": 1, "headcount": {"$ifNull": [{"$arrayElemAt": ["$hc.n", 0]}, 0]}, "logs": 1}},
        {"$project": {"date": 1, "headcount": 1, "present_count": {"$sum": {"$map": {"input": "$logs", "as": "l", "in": {"$cond": [{"$in": ["$$l.status", list(PRESENT_STATUSES)]}, {"$cond": ["$$l.half_day", 0.5, 1]}, 0]}}}}, "late_count": {"$size": {"$filter": {"input": "$logs", "as": "l", "cond": {"$gt": ["$$l.late_minutes", 0]}}}}}},
        {"$set": {"is_working_day": {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2,3,4,5,6]]}, "attendance_rate": {"$cond": [{"$and": [{"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2,3,4,5,6]]}, {"$gt": ["$headcount", 0]}]}, {"$round": [{"$divide": ["$present_count", "$headcount"]}, 4]}, None]}}},
        {"$setWindowFields": {"sortBy": {"date": 1}, "output": {"moving_avg_7d": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}}}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1, "present_count": 1, "late_count": 1, "attendance_rate": 1, "moving_avg_7d": 1}}, {"$sort": {"date": 1}}
    ]
    # Add employee codes into each day's lookup via department + joined date to preserve zero-log employees.
    # This version uses a correlated employee lookup for each day, then attendance lookup by employee code.
    trend_pipeline = [
        {"$documents": [{"start": datetime.combine(first, time.min, UTC)}]},
        {"$project": {"days": {"$map": {"input": {"$range": [0, (last-first).days+1]}, "as": "i", "in": {"$dateToString": {"date": {"$dateAdd": {"startDate": "$start", "unit": "day", "amount": "$$i"}}, "format": "%Y-%m-%d", "timezone": "UTC"}}}}}},
        {"$unwind": "$days"}, {"$project": {"_id": 0, "date": "$days"}},
        {"$lookup": {"from": "employees", "let": {"d": "$date"}, "pipeline": [{"$match": {"department": department, "$expr": {"$lte": ["$joined_on", "$$d"]}}}, {"$project": {"_id": 0, "emp_code": 1}}, {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code", "d": "$$d"}, "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$eq": ["$date", "$$d"]}]}}}], "as": "logs"}}, {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}}, {"$group": {"_id": None, "headcount": {"$sum": 1}, "present_count": {"$sum": {"$cond": [{"$in": ["$logs.status", list(PRESENT_STATUSES)]}, {"$cond": ["$logs.half_day", 0.5, 1]}, 0]}}, "late_count": {"$sum": {"$cond": [{"$gt": ["$logs.late_minutes", 0]}, 1, 0]}}}}], "as": "stats"}},
        {"$project": {"date": 1, "headcount": {"$ifNull": [{"$arrayElemAt": ["$stats.headcount", 0]}, 0]}, "present_count": {"$ifNull": [{"$arrayElemAt": ["$stats.present_count", 0]}, 0]}, "late_count": {"$ifNull": [{"$arrayElemAt": ["$stats.late_count", 0]}, 0]}}},
        {"$set": {"is_working_day": {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2,3,4,5,6]]}, "attendance_rate": {"$cond": [{"$and": [{"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2,3,4,5,6]]}, {"$gt": ["$headcount", 0]}]}, {"$round": [{"$divide": ["$present_count", "$headcount"]}, 4]}, None]}}},
        {"$setWindowFields": {"sortBy": {"date": 1}, "output": {"moving_avg_7d": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}}}},
        {"$project": {"_id": 0, "date": 1, "is_working_day": 1, "headcount": 1, "present_count": 1, "late_count": 1, "attendance_rate": 1, "moving_avg_7d": 1}}, {"$sort": {"date": 1}}
    ]
    try: rows = list(db.aggregate(trend_pipeline))
    except PyMongoError: fail(503, "Database operation failed")
    for row in rows:
        if row.get("attendance_rate") is not None: row["attendance_rate"] = round_half_up(row["attendance_rate"], 4)
        if row.get("moving_avg_7d") is not None: row["moving_avg_7d"] = round_half_up(row["moving_avg_7d"], 4)
    return {"department": department, "from": from_date, "to": to_date, "items": rows}


@app.get("/admin/explain/{endpoint}")
@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    month: Optional[str] = None,
    department: Optional[str] = None,
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: int = Query(10, ge=1, le=50),
):
    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }
    if endpoint not in allowed:
        fail(422, "Unsupported explain endpoint")

    try:
        if endpoint == "attendance_list":
            q = {}
            if emp_code:
                q["emp_code"] = emp_code
            if date_from or date_to:
                q["date"] = {}
                if date_from:
                    q["date"]["$gte"] = parse_date(date_from).isoformat()
                if date_to:
                    q["date"]["$lte"] = parse_date(date_to).isoformat()
                if date_from and date_to and date_from > date_to:
                    fail(422, "date_from must be on or before date_to")

            result = db.command(
                "explain",
                {
                    "find": "attendance_logs",
                    "filter": q,
                    "sort": {"date": -1, "emp_code": 1},
                    "skip": (page - 1) * page_size,
                    "limit": page_size,
                },
                verbosity="executionStats",
            )

        elif endpoint == "employee_monthly":
            if not month or not __import__("re").fullmatch(r"\d{4}-\d{2}", month):
                fail(422, "month=YYYY-MM is required")
            if not emp_code:
                fail(422, "emp_code is required")
            require_employee(emp_code)
            start, end = parse_month(month)

            pipeline = [
                {"$match": {
                    "emp_code": emp_code,
                    "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
                }},
                {"$group": {
                    "_id": None,
                    "present_days": {"$sum": {"$cond": [
                        {"$and": [
                            {"$in": ["$status", list(PRESENT_STATUSES)]},
                            {"$in": [
                                {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}},
                                [2, 3, 4, 5, 6],
                            ]},
                        ]},
                        {"$cond": ["$half_day", 0.5, 1]},
                        0,
                    ]}},
                    "leave_days": {"$sum": {"$cond": [
                        {"$eq": ["$status", "LEAVE"]}, 1, 0,
                    ]}},
                    "late_count": {"$sum": {"$cond": [
                        {"$gt": ["$late_minutes", 0]}, 1, 0,
                    ]}},
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "total_overtime_minutes": {"$sum": "$overtime_minutes"},
                }},
            ]
            result = db.command(
                "explain",
                {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}},
                verbosity="executionStats",
            )

        elif endpoint == "department_summary":
            if not month or not __import__("re").fullmatch(r"\d{4}-\d{2}", month):
                fail(422, "month=YYYY-MM is required")
            start, end = parse_month(month)
            match = {"joined_on": {"$lte": end.isoformat()}}
            if department is not None:
                match["department"] = department

            pipeline = [
                {"$match": match},
                {"$lookup": {
                    "from": "attendance_logs",
                    "let": {"code": "$emp_code"},
                    "pipeline": [{"$match": {"$expr": {"$and": [
                        {"$eq": ["$emp_code", "$$code"]},
                        {"$gte": ["$date", start.isoformat()]},
                        {"$lte": ["$date", end.isoformat()]},
                    ]}}}],
                    "as": "logs",
                }},
                {"$unwind": {
                    "path": "$logs",
                    "preserveNullAndEmptyArrays": True,
                }},
                {"$group": {
                    "_id": "$department",
                    "headcount": {"$addToSet": "$emp_code"},
                    "present_days": {"$sum": {"$cond": [
                        {"$and": [
                            {"$in": ["$logs.status", list(PRESENT_STATUSES)]},
                            {"$in": [
                                {"$dayOfWeek": {"$dateFromString": {"dateString": "$logs.date"}}},
                                [2, 3, 4, 5, 6],
                            ]},
                        ]},
                        {"$cond": ["$logs.half_day", 0.5, 1]},
                        0,
                    ]}},
                    "hours": {"$push": {"$cond": [
                        {"$and": [
                            {"$in": ["$logs.status", list(PRESENT_STATUSES)]},
                            {"$ne": ["$logs.work_hours", None]},
                        ]},
                        "$logs.work_hours",
                        None,
                    ]}},
                    "late_count": {"$sum": {"$cond": [
                        {"$gt": ["$logs.late_minutes", 0]}, 1, 0,
                    ]}},
                    "total_late_minutes": {"$sum": {
                        "$ifNull": ["$logs.late_minutes", 0],
                    }},
                    "leave_count": {"$sum": {"$cond": [
                        {"$eq": ["$logs.status", "LEAVE"]}, 1, 0,
                    ]}},
                    "on_duty_count": {"$sum": {"$cond": [
                        {"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0,
                    ]}},
                }},
                {"$project": {
                    "_id": 0,
                    "department": "$_id",
                    "headcount": {"$size": "$headcount"},
                    "present_days": 1,
                    "late_count": 1,
                    "total_late_minutes": 1,
                    "leave_count": 1,
                    "on_duty_count": 1,
                    "avg_work_hours": {"$let": {
                        "vars": {"valid": {"$filter": {
                            "input": "$hours",
                            "as": "h",
                            "cond": {"$ne": ["$$h", None]},
                        }}},
                        "in": {"$cond": [
                            {"$gt": [{"$size": "$$valid"}, 0]},
                            {"$round": [{"$avg": "$$valid"}, 2]},
                            None,
                        ]},
                    }},
                }},
                {"$match": {"headcount": {"$gt": 0}}},
                {"$sort": {"department": 1}},
            ]
            result = db.command(
                "explain",
                {"aggregate": "employees", "pipeline": pipeline, "cursor": {}},
                verbosity="executionStats",
            )

        elif endpoint == "late_leaderboard":
            if not month or not __import__("re").fullmatch(r"\d{4}-\d{2}", month):
                fail(422, "month=YYYY-MM is required")
            start, end = parse_month(month)

            pipeline = [
                {"$match": {
                    "date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
                    "late_minutes": {"$gt": 0},
                }},
                {"$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                }},
                {"$lookup": {
                    "from": "employees",
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "employee",
                }},
                {"$unwind": "$employee"},
            ]
            if department is not None:
                pipeline.append({"$match": {"employee.department": department}})
            pipeline += [
                {"$setWindowFields": {
                    "sortBy": {"total_late_minutes": -1},
                    "output": {"rank": {"$rank": {}}},
                }},
                {"$match": {"rank": {"$lte": limit}}},
                {"$sort": {"total_late_minutes": -1, "_id": 1}},
                {"$project": {
                    "_id": 0,
                    "emp_code": "$_id",
                    "name": "$employee.name",
                    "department": "$employee.department",
                    "total_late_minutes": 1,
                    "rank": 1,
                }},
            ]
            result = db.command(
                "explain",
                {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}},
                verbosity="executionStats",
            )

        else:
            if not date_from or not date_to:
                fail(422, "date_from and date_to are required for department_trend")
            first, last = parse_date(date_from), parse_date(date_to)
            if last < first:
                fail(422, "date_to must be on or after date_from")
            if (last - first).days > 91:
                fail(422, "Date range cannot exceed 92 days")
            if not department:
                fail(422, "department is required for department_trend")
            if db.employees.find_one({"department": department}, {"_id": 1}) is None:
                fail(404, "Department not found")

            trend_pipeline = [
                {"$documents": [{
                    "start": datetime.combine(first, time.min, UTC),
                }]},
                {"$project": {"days": {"$map": {
                    "input": {"$range": [0, (last - first).days + 1]},
                    "as": "i",
                    "in": {"$dateToString": {
                        "date": {"$dateAdd": {
                            "startDate": "$start",
                            "unit": "day",
                            "amount": "$$i",
                        }},
                        "format": "%Y-%m-%d",
                        "timezone": "UTC",
                    }},
                }}}},
                {"$unwind": "$days"},
                {"$project": {"_id": 0, "date": "$days"}},
                {"$lookup": {
                    "from": "employees",
                    "let": {"d": "$date"},
                    "pipeline": [
                        {"$match": {
                            "department": department,
                            "$expr": {"$lte": ["$joined_on", "$$d"]},
                        }},
                        {"$project": {"_id": 0, "emp_code": 1}},
                        {"$lookup": {
                            "from": "attendance_logs",
                            "let": {"code": "$emp_code", "d": "$$d"},
                            "pipeline": [{"$match": {"$expr": {"$and": [
                                {"$eq": ["$emp_code", "$$code"]},
                                {"$eq": ["$date", "$$d"]},
                            ]}}}],
                            "as": "logs",
                        }},
                        {"$unwind": {
                            "path": "$logs",
                            "preserveNullAndEmptyArrays": True,
                        }},
                        {"$group": {
                            "_id": None,
                            "headcount": {"$sum": 1},
                            "present_count": {"$sum": {"$cond": [
                                {"$in": ["$logs.status", list(PRESENT_STATUSES)]},
                                {"$cond": ["$logs.half_day", 0.5, 1]},
                                0,
                            ]}},
                            "late_count": {"$sum": {"$cond": [
                                {"$gt": ["$logs.late_minutes", 0]}, 1, 0,
                            ]}},
                        }},
                    ],
                    "as": "stats",
                }},
                {"$project": {
                    "date": 1,
                    "headcount": {"$ifNull": [
                        {"$arrayElemAt": ["$stats.headcount", 0]}, 0,
                    ]},
                    "present_count": {"$ifNull": [
                        {"$arrayElemAt": ["$stats.present_count", 0]}, 0,
                    ]},
                    "late_count": {"$ifNull": [
                        {"$arrayElemAt": ["$stats.late_count", 0]}, 0,
                    ]},
                }},
                {"$set": {
                    "is_working_day": {"$in": [
                        {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}},
                        [2, 3, 4, 5, 6],
                    ]},
                    "attendance_rate": {"$cond": [
                        {"$and": [
                            {"$in": [
                                {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}},
                                [2, 3, 4, 5, 6],
                            ]},
                            {"$gt": ["$headcount", 0]},
                        ]},
                        {"$round": [{"$divide": ["$present_count", "$headcount"]}, 4]},
                        None,
                    ]},
                }},
                {"$setWindowFields": {
                    "sortBy": {"date": 1},
                    "output": {"moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]},
                    }},
                }},
                {"$project": {
                    "_id": 0,
                    "date": 1,
                    "is_working_day": 1,
                    "headcount": 1,
                    "present_count": 1,
                    "late_count": 1,
                    "attendance_rate": 1,
                    "moving_avg_7d": 1,
                }},
                {"$sort": {"date": 1}},
            ]
            trend_explain_pipeline = [
                {"$match": {
                    "department": department,
                    "joined_on": {"$lte": last.isoformat()},
                }},
                {"$lookup": {
                    "from": "attendance_logs",
                    "let": {"code": "$emp_code"},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$emp_code", "$$code"]}}},
                    ],
                    "as": "attendance_matches",
                }},
            ]
            result = db.command(
                "explain",
                {"aggregate": "employees", "pipeline": trend_explain_pipeline, "cursor": {}},
                verbosity="executionStats",
            )

        return Response(
            content=json_util.dumps(result),
            media_type="application/json",
        )
    except HTTPException:
        raise
    except PyMongoError:
        fail(503, "Database operation failed")
