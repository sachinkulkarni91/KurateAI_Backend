from pydantic import BaseModel, Field, field_validator
from typing import List

class AccessRequestFilter(BaseModel):
    status: str

    @field_validator("status")
    def validate_status(cls, value):
        allowed = {"PENDING", "APPROVED", "REJECTED"}
        value = value.upper()

        if value not in allowed:
            raise ValueError(f"Status must be one of {allowed}")

        return value

class AccessRequestCreate(BaseModel):
    request_id: str | None = None
    user_id: str
    user_name: str | None = None
    resource_id: str | None = None
    resource_name: str
    requested_action: str
    status: str | None = None
    created_at: str | None = None
    
    scope_type: str = "study"
    scope_id: str = ""
    justification: str = ""



class AccessRequestItem(BaseModel):
    request_id: str
    user_id: str
    user_name: str
    resource_id: str
    resource_name: str
    requested_action: str
    status: str
    created_at: str

class AccessRequestListResponse(BaseModel):
    count: int
    data: List[AccessRequestItem]

class AnalyzeRequest(BaseModel):
    req_id: str
    status: str

    @field_validator("status")
    def validate_status(cls, value):
        allowed = {"PENDING", "APPROVED", "REJECTED"}
        value = value.upper()

        if value not in allowed:
            raise ValueError(f"Status must be one of {allowed}")

        return value

class CurrentRole(BaseModel):
    role: str
    scope: str

class Impact(BaseModel):
    risk_level: str
    description: str

class Recommendation(BaseModel):
    decision: str
    confidence: str
    reason: str

class History(BaseModel):
    approved_request_ids: List[str]
    rejected_request_ids: List[str]

class AnalyzeResponse(BaseModel):
    request_id: str

    summary: str

    current_roles: List[CurrentRole]
    candidate_roles: List[str]

    impact: Impact
    recommendation: Recommendation

    history: History

class RoleAssignment(BaseModel):
    role: str
    scope: str

class DecisionRequest(BaseModel):
    decision: str  # APPROVE | REJECT
    roles_to_assign: List[RoleAssignment] = []
    comments: str | None = None
    approver_id: str
    