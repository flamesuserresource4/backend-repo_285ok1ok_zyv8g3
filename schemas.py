"""
Database Schemas for Smart Railway Track Inspection

Each Pydantic model represents a MongoDB collection. The collection name is the
lowercase class name (e.g., TrackSection -> "tracksection").
"""
from typing import Optional, Literal
from pydantic import BaseModel, Field

class TrackSection(BaseModel):
    """Represents a railway track section being monitored"""
    name: str = Field(..., description="Human friendly section name, e.g., S1, Yard-2")
    status: Literal["safe", "faulty"] = Field("safe", description="Current status")
    color_safe: str = Field("#16a34a", description="Hex color used to display safe sections")
    color_faulty: str = Field("#dc2626", description="Hex color used to display faulty sections")
    last_check: Optional[str] = Field(None, description="ISO timestamp of last inspection")
    persistent_faults: int = Field(0, ge=0, description="Number of repeated faults")

class Inspection(BaseModel):
    """Represents a single inspection event for a section"""
    section_id: str = Field(..., description="ID of the TrackSection inspected")
    status: Literal["safe", "faulty"] = Field(..., description="Resulting status after inspection")
    detail: Optional[str] = Field(None, description="Optional detail such as sensor reading")
    inspected_at: Optional[str] = Field(None, description="ISO timestamp of the inspection time")

class Alert(BaseModel):
    """Represents an automatic alert raised when a fault is detected"""
    section_id: str = Field(..., description="ID of the section that raised the alert")
    message: str = Field(..., description="Alert message")
    severity: Literal["low", "medium", "high", "critical"] = Field("high")
    acknowledged: bool = Field(False, description="Whether the alert has been acknowledged")

class User(BaseModel):
    """Minimal user schema for multi-user access"""
    name: str
    email: str
    role: Literal["viewer", "operator", "admin"] = "viewer"
    token: Optional[str] = None
