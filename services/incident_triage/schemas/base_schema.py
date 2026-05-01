from pydantic import BaseModel, field_validator
from typing import List, Optional

class IncidentStatus(BaseModel):
    status: str

    @field_validator("status")
    def validate_status(cls, value):
        allowed = {"in progress", "open", "closed", "resolved", "pending"}
        value_lower = value.lower()

        if value_lower not in allowed:
            raise ValueError(f"Status must be one of {allowed}")

        return value_lower

class IncidentSummary(BaseModel):
    number: str
    short_description: str
    assigned_to: str
    state: str

class IncidentListResponse(BaseModel):
    count: int
    incidents: List[IncidentSummary]


class SimilarIncident(BaseModel):
    incident_id: str
    short_description: str
    description: str
    resolution: str

class IncidentAnalysisResponse(BaseModel):
    summary: str 
    root_cause: str 
    recommendation: str 
    confidence: str 
    estimated_effort: str
    similar_incidents: List[SimilarIncident]


class IncidentResolveRequest(BaseModel):
    incident_id: str
    resolution: str

class IncidentCreateRequest(BaseModel):
    affected_user: str
    number: Optional[str] = None
    short_description: str
    description: str
    assigned_to: str
    state: Optional[str] = "Open"
    resolution: str = ""
