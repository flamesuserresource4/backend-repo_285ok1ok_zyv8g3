import os
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="Smart Railway Track Inspection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

def oid(id_str: str) -> ObjectId:
    if not ObjectId.is_valid(id_str):
        raise HTTPException(status_code=400, detail="Invalid id")
    return ObjectId(id_str)

# Request models
class SectionCreate(BaseModel):
    name: str
    color_safe: str = "#16a34a"
    color_faulty: str = "#dc2626"

class SectionUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(safe|faulty)$")
    color_safe: Optional[str] = None
    color_faulty: Optional[str] = None

class MarkPayload(BaseModel):
    status: str = Field(..., pattern="^(safe|faulty)$")

class InspectPayload(BaseModel):
    section_id: str
    status: str = Field(..., pattern="^(safe|faulty)$")
    detail: Optional[str] = None

class LoginPayload(BaseModel):
    name: str
    email: str

# Root and health
@app.get("/")
def read_root():
    return {"message": "Smart Railway Track Inspection API is running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# Sections CRUD
@app.get("/api/sections")
def list_sections():
    sections = list(db["tracksection"].find().sort("name"))
    for s in sections:
        s["id"] = str(s.pop("_id"))
    return sections

@app.post("/api/sections", status_code=201)
def create_section(payload: SectionCreate):
    now = datetime.now(timezone.utc)
    doc = {
        "name": payload.name,
        "status": "safe",
        "color_safe": payload.color_safe,
        "color_faulty": payload.color_faulty,
        "last_check": None,
        "persistent_faults": 0,
        "created_at": now,
        "updated_at": now,
    }
    inserted_id = db["tracksection"].insert_one(doc).inserted_id
    doc["id"] = str(inserted_id)
    doc.pop("_id", None)
    return doc

@app.patch("/api/sections/{section_id}")
def update_section(section_id: str, payload: SectionUpdate):
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        return {"updated": False}
    updates["updated_at"] = datetime.now(timezone.utc)
    result = db["tracksection"].update_one({"_id": oid(section_id)}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Section not found")
    s = db["tracksection"].find_one({"_id": oid(section_id)})
    s["id"] = str(s.pop("_id"))
    return s

@app.delete("/api/sections/{section_id}")
def delete_section(section_id: str):
    result = db["tracksection"].delete_one({"_id": oid(section_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Section not found")
    return {"deleted": True}

@app.post("/api/sections/{section_id}/mark")
def mark_section(section_id: str, payload: MarkPayload):
    now = datetime.now(timezone.utc)
    section = db["tracksection"].find_one({"_id": oid(section_id)})
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    is_repeat_fault = section.get("status") == "faulty" and payload.status == "faulty"
    updates = {
        "status": payload.status,
        "last_check": datetime.now(timezone.utc).isoformat(),
        "updated_at": now,
    }
    if is_repeat_fault:
        updates["persistent_faults"] = section.get("persistent_faults", 0) + 1
    result = db["tracksection"].update_one({"_id": oid(section_id)}, {"$set": updates})
    # Create inspection record
    insp = {
        "section_id": section_id,
        "status": payload.status,
        "detail": "manual-mark",
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "created_at": now,
    }
    db["inspection"].insert_one(insp)
    # Create alert if faulty
    if payload.status == "faulty":
        db["alert"].insert_one({
            "section_id": section_id,
            "message": f"Fault detected at section {section.get('name','')}.",
            "severity": "high",
            "acknowledged": False,
            "created_at": now,
        })
    s = db["tracksection"].find_one({"_id": oid(section_id)})
    s["id"] = str(s.pop("_id"))
    return s

# Inspections
@app.post("/api/inspect", status_code=201)
def inspect(payload: InspectPayload):
    section = db["tracksection"].find_one({"_id": oid(payload.section_id)})
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    now = datetime.now(timezone.utc)
    insp = {
        "section_id": payload.section_id,
        "status": payload.status,
        "detail": payload.detail,
        "inspected_at": now.isoformat(),
        "created_at": now,
    }
    db["inspection"].insert_one(insp)
    # Update section
    is_repeat_fault = section.get("status") == "faulty" and payload.status == "faulty"
    updates = {
        "status": payload.status,
        "last_check": now.isoformat(),
        "updated_at": now,
    }
    if is_repeat_fault:
        updates["persistent_faults"] = section.get("persistent_faults", 0) + 1
    db["tracksection"].update_one({"_id": oid(payload.section_id)}, {"$set": updates})
    if payload.status == "faulty":
        db["alert"].insert_one({
            "section_id": payload.section_id,
            "message": f"Fault detected at section {section.get('name','')} (auto)",
            "severity": "high",
            "acknowledged": False,
            "created_at": now,
        })
    return {"created": True}

@app.get("/api/inspections")
def list_inspections(section_id: Optional[str] = None, limit: int = 50):
    query = {"section_id": section_id} if section_id else {}
    cursor = db["inspection"].find(query).sort("created_at", -1).limit(limit)
    inspections = list(cursor)
    for i in inspections:
        i["id"] = str(i.pop("_id"))
    return inspections

# Alerts
@app.get("/api/alerts")
def list_alerts(only_open: bool = True):
    query = {"acknowledged": False} if only_open else {}
    alerts = list(db["alert"].find(query).sort("created_at", -1).limit(100))
    for a in alerts:
        a["id"] = str(a.pop("_id"))
    return alerts

@app.post("/api/alerts/ack/{alert_id}")
def ack_alert(alert_id: str):
    result = db["alert"].update_one({"_id": oid(alert_id)}, {"$set": {"acknowledged": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"acknowledged": True}

# Summary
@app.get("/api/summary")
def summary():
    total = db["tracksection"].count_documents({})
    safe = db["tracksection"].count_documents({"status": "safe"})
    faulty = db["tracksection"].count_documents({"status": "faulty"})
    critical = db["tracksection"].count_documents({"persistent_faults": {"$gte": 3}})
    return {"total": total, "safe": safe, "faulty": faulty, "critical": critical}

# Export CSV
@app.get("/api/export/sections", response_class=PlainTextResponse)
def export_sections_csv():
    sections = list(db["tracksection"].find().sort("name"))
    lines = ["id,name,status,last_check,persistent_faults"]
    for s in sections:
        lines.append(f"{s.get('_id')},{s.get('name','')},{s.get('status','')},{s.get('last_check','')},{s.get('persistent_faults',0)}")
    csv_data = "\n".join(lines)
    headers = {"Content-Disposition": "attachment; filename=sections.csv"}
    return Response(content=csv_data, media_type="text/csv", headers=headers)

@app.get("/api/export/inspections", response_class=PlainTextResponse)
def export_inspections_csv(limit: int = 1000):
    cursor = db["inspection"].find({}).sort("created_at", -1).limit(limit)
    lines = ["id,section_id,status,detail,inspected_at"]
    for i in cursor:
        lines.append(f"{i.get('_id')},{i.get('section_id','')},{i.get('status','')},{i.get('detail','')},{i.get('inspected_at','')}")
    csv_data = "\n".join(lines)
    headers = {"Content-Disposition": "attachment; filename=inspections.csv"}
    return Response(content=csv_data, media_type="text/csv", headers=headers)

# Simple multi-user login (demo only)
@app.post("/api/login")
def login(payload: LoginPayload):
    token = f"tok-{abs(hash(payload.email))}"
    user = db["user"].find_one({"email": payload.email})
    if not user:
        db["user"].insert_one({"name": payload.name, "email": payload.email, "role": "viewer", "token": token, "created_at": datetime.now(timezone.utc)})
    else:
        db["user"].update_one({"_id": user["_id"]}, {"$set": {"token": token}})
    return {"name": payload.name, "email": payload.email, "token": token}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
