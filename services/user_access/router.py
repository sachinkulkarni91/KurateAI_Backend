from fastapi import APIRouter, Depends, HTTPException

from services.user_access.agents.user_access_manager.main import *
from services.user_access.utils.query import *
from services.user_access.schemas.base_schema import AccessRequestFilter, AccessRequestListResponse, AnalyzeRequest, AnalyzeResponse, DecisionRequest, AccessRequestCreate

router = APIRouter()

def _build_decision_payload(context, current_roles, candidate_roles, requested_scope, history):
    return {
        "user": {
            "name": context["user_name"]
        },
        "request": {
            "action": context["requested_action"],
            "resource": context["resource_name"],
            "resource_type": context["resource_type"],
            "study": context["scope_id"],
            "sensitivity": context["sensitivity"]
        },
        "access_gap": {
            "current_role": current_roles,
            "candidate_role": candidate_roles,
            "requested_scope": requested_scope
        },
        "history": history
    }

@router.get("/get-access-requests", response_model=AccessRequestListResponse)
def get_access_requests(status: str):
    allowed = {"PENDING", "APPROVED", "REJECTED"}
    if status.upper() not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {allowed}")
        
    try:
        data = get_access_requests_by_status(status.upper())

        return {
            "count": len(data),
            "data": data
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{request_id}/analyze", response_model=AnalyzeResponse)
def get_analysis(request: AnalyzeRequest):
    # Data Processing
    context = get_request_base(request_id=request.req_id)
    roles = get_user_roles(context["user_id"])
    permission = get_required_permission(action=context['requested_action'], resource_type=context['resource_type'])
    candidate_roles = get_roles_for_permission(permission)
    history = get_historical_requests(
        action=context['requested_action'],
        resource_type=context['resource_type'],
        scope_id=context['scope_id'],
        request_id=request.req_id 
    )
    
    if request.status != 'PENDING':
        return {
            'request_id': request.req_id,
            'summary': "",
            'current_roles': roles,
            'candidate_roles': candidate_roles,
            'history': history,
            'impact': {
                "risk_level": "",
                "description": ""
            },
            'recommendation': {
                "decision": "",
                "confidence": "",
                "reason": ""
            }
        }
    else: 
        summary = "AI Analysis is currently unavailable because the API key is missing or invalid."
        decision = {
            "risk": "Unknown",
            "impact": "Cannot assess impact without AI agent.",
            "decision": "Manual Review Required",
            "confidence": "Low",
            "reason": "AI service is not configured. Please review this request manually."
        }
        
        try:
            # LLM Summarization
            summary_agent = SummaryAgent()
            summary = summary_agent.generate_summary(context)

            # LLM Decision
            decision_agent = DecisionAgent()
            payload = _build_decision_payload(context, roles, candidate_roles, context.get('scope_id', ''), history)
            decision = decision_agent.generate_decision(payload)
        except Exception as e:
            print(f"LLM Analysis failed: {str(e)}")

        return {
            'request_id': request.req_id,
            'summary': summary,
            'current_roles': roles,
            'candidate_roles': candidate_roles,
            'history': history,
            'impact': {
                "risk_level": decision["risk"],
                "description": decision["impact"]
            },
            'recommendation': {
                "decision": decision["decision"],
                "confidence": decision["confidence"],
                "reason": decision["reason"]
            }
        }

@router.post("/access-requests/{request_id}/decision")
def decide_access_request(request_id: str, payload: DecisionRequest):
    try:
        UpsertAgent.upsert_decision(request_id, payload)
        
        return {
            "message": f"Request {request_id} processed successfully"
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/create-request")
@router.post("/submit-access-request")
def create_new_access_request(request: AccessRequestCreate):
    request_data = request.model_dump()
    new_id = create_access_request(request_data)
    
    return {
        "message": "Access request created successfully",
        "request_id": new_id
    }