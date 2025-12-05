from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class LeadStatus(str, Enum):
    NEW = "New"
    CONTACTED = "Contacted"
    QUALIFIED = "Qualified"
    CLOSED = "Closed"


class TaskStatus(str, Enum):
    NEW = "New"
    IN_PROGRESS = "In Progress"
    QUALIFIED = "Qualified"
    DONE = "Done"


class Lead(BaseModel):
    id: str = Field(..., description="Unique lead identifier")
    name: str
    email: str
    phone: Optional[str] = None
    company: Optional[str] = None
    status: str = "New"  # Can be: New, Contacted, Qualified, Closed
    notes: Optional[str] = None
    trello_card_id: Optional[str] = Field(None, description="Linked Trello card ID")

    class Config:
        use_enum_values = True


class Task(BaseModel):
    id: str = Field(..., description="Unique task identifier")
    title: str
    status: str = "New"  # Can be: New, In Progress, Qualified, Done
    lead_id: Optional[str] = None
    notes: Optional[str] = None
    list_id: Optional[str] = None  # Trello list ID

    class Config:
        use_enum_values = True


class SyncResult(BaseModel):
    total_leads: int
    total_tasks: int
    created_tasks: int
    updated_tasks: int
    updated_leads: int
    errors: int
    error_details: list = []


class HealthResponse(BaseModel):
    status: str
    message: str
    environment: str
