"""
FastAPI router for Bug RCA Service
Provides REST API endpoints for RCA analysis
"""

import logging
from fastapi import APIRouter, HTTPException, status, Query
from typing import Optional, List, Tuple
from datetime import datetime
import os
import glob
import json
import uuid
from difflib import SequenceMatcher

from services.bug_rca.schemas.base_schema import (
    RCARequest, RCAResponse, BugLogEntry, FullRCARequest, FullRCAResponse,
    DashboardResponse, DashboardStatistics, IncidentQuestion,
    BugMatchingRequest, BugMatchingResponse, MatchedScenario, AnalysisDepth,
    MatchIncidentRequest, MatchedIncidentResponse
)
from services.bug_rca.graph import RCAWorkflow

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and workflow
router = APIRouter()
workflow_graph = RCAWorkflow()

# --- Constants ---
MAX_LOGS_FOR_ANALYSIS = 100
MATCHING_SCORE_WEIGHTS = {
    "keyword": 0.15,
    "error_type": 0.25,
    "service_name": 0.20,
    "error_message": 0.15,
    "similarity": 0.10,
}

# --- Helper Functions ---

def compress_logs(logs: List[BugLogEntry]) -> List[BugLogEntry]:
    """Compress log entries by grouping identical errors to reduce token usage."""
    if not logs:
        return logs
        
    grouped = {}
    for log in logs:
        # Create a unique signature for this error type
        sig = f"{log.service_name}::{log.error_message}"
        if sig not in grouped:
            grouped[sig] = log.model_copy() if hasattr(log, "model_copy") else log.copy()
            if grouped[sig].metadata is None:
                grouped[sig].metadata = {}
            grouped[sig].metadata["occurrences"] = 1
            grouped[sig].metadata["first_seen"] = str(log.timestamp)
            grouped[sig].metadata["last_seen"] = str(log.timestamp)
        else:
            grouped[sig].metadata["occurrences"] += 1
            grouped[sig].metadata["last_seen"] = str(log.timestamp)
            
    return list(grouped.values())


# ============ Health Check Endpoints ============

@router.get("/", tags=["Health"])
def read_root():
    """Service root endpoint"""
    return {
        "service": "bug_rca",
        "message": "Bug Report/Logs Summary + RCA Service",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "analyze": "/analyze"
        }
    }


@router.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "bug_rca",
        "version": "1.0.0"
    }


# ============ RCA Analysis Endpoints ============

@router.post(
    "/analyze",
    response_model=RCAResponse,
    status_code=status.HTTP_200_OK,
    tags=["Analysis"],
    summary="Perform Root Cause Analysis on bug logs",
    responses={
        200: {"description": "Successful analysis"},
        400: {"description": "Invalid request"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)
def analyze_logs(request: RCARequest) -> RCAResponse:
    """
    Analyze bug logs and generate Root Cause Analysis
    
    **Request Parameters:**
    - `logs`: List of bug log entries (required, 1-50 entries)
    - `analysis_depth`: Level of analysis - "quick", "standard", or "detailed" (default: "standard")
    - `focus_areas`: Specific areas to focus on (optional)
    
    **Response:**
    Returns complete RCA analysis with root cause identification, affected systems, 
    severity assessment, business impact, and recommendations.
    
    **Example Request:**
    ```json
    {
        "logs": [
            {
                "timestamp": "2024-01-15T10:30:00Z",
                "service_name": "api-gateway",
                "error_message": "NullPointerException in RequestHandler",
                "environment": "production"
            }
        ],
        "analysis_depth": "standard",
        "focus_areas": ["authentication", "validation"]
    }
    ```
    
    **Example Response:**
    ```json
    {
        "request_id": "550e8400-e29b-41d4-a716-446655440000",
        "analysis": {
            "root_cause": "Null pointer in request validation",
            "affected_systems": ["api-gateway", "auth-service"],
            "severity": "high",
            "business_impact": "Users unable to authenticate affecting 15% of user base",
            "recommendations": [
                "Add null-safety checks in validation layer",
                "Implement input sanitization",
                "Add monitoring for this error pattern"
            ],
            "confidence_score": 0.85,
            "related_errors": []
        },
        "processing_time_ms": 2350.5,
        "model_used": "openrouter-llm",
        "analysis_summary": "Analyzed 1 bug logs. Root Cause: Null pointer in request validation. Severity: HIGH...",
        "timestamp": "2024-01-15T10:35:00Z"
    }
    ```
    """
    
    try:
        logger.info(f"Received RCA analysis request with {len(request.logs)} logs")
        
        # Validate request
        if not request.logs or len(request.logs) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one log entry is required"
            )
        
        if len(request.logs) > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 1000 log entries allowed per request"
            )
            
        # Compress logs to save tokens
        original_count = len(request.logs)
        request.logs = compress_logs(request.logs)
        logger.info(f"Compressed {original_count} logs down to {len(request.logs)} unique signatures")
        
        # Execute analysis
        response = workflow_graph.execute(request)
        
        logger.info(f"RCA analysis completed. Request ID: {response.request_id}")
        return response
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in RCA analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during RCA analysis"
        )


@router.post(
    "/quick-analyze",
    response_model=RCAResponse,
    status_code=status.HTTP_200_OK,
    tags=["Analysis"],
    summary="Quick RCA analysis (performance optimized)"
)
def quick_analyze(request: RCARequest) -> RCAResponse:
    """
    Quick analysis endpoint (optimized for speed)
    
    Similar to /analyze but forces "quick" analysis depth for faster response
    """
    
    try:
        # Force quick analysis depth
        request.analysis_depth = AnalysisDepth.QUICK
        
        logger.info(f"Received quick RCA analysis request with {len(request.logs)} logs")
        request.logs = compress_logs(request.logs)
        response = workflow_graph.execute(request)
        
        return response
        
    except Exception as e:
        logger.error(f"Error in quick analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Quick analysis failed"
        )


@router.post(
    "/detailed-analyze",
    response_model=RCAResponse,
    status_code=status.HTTP_200_OK,
    tags=["Analysis"],
    summary="Detailed RCA analysis (comprehensive)"
)
def detailed_analyze(request: RCARequest) -> RCAResponse:
    """
    Detailed analysis endpoint (comprehensive analysis)
    
    Similar to /analyze but forces "detailed" analysis depth for thorough results
    """
    
    try:
        # Force detailed analysis depth
        request.analysis_depth = AnalysisDepth.DETAILED
        
        logger.info(f"Received detailed RCA analysis request with {len(request.logs)} logs")
        request.logs = compress_logs(request.logs)
        response = workflow_graph.execute(request)
        
        return response
        
    except Exception as e:
        logger.error(f"Error in detailed analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Detailed analysis failed"
        )


# ============ Batch Analysis Endpoints ============

@router.post(
    "/batch-analyze",
    status_code=status.HTTP_200_OK,
    tags=["Batch Operations"],
    summary="Analyze multiple log batches"
)
def batch_analyze(requests: List[RCARequest]) -> List[RCAResponse]:
    """
    Analyze multiple RCA requests in batch
    
    **Parameters:**
    - `requests`: Array of RCARequest objects
    
    **Returns:**
    Array of RCAResponse objects in the same order as requests
    """
    
    try:
        logger.info(f"Received batch analysis with {len(requests)} requests")
        
        responses = []
        for req in requests:
            try:
                req.logs = compress_logs(req.logs)
                response = workflow_graph.execute(req)
                responses.append(response)
            except Exception as e:
                logger.error(f"Error in batch item: {str(e)}")
                # Optionally skip failed items or return error response
                continue
        
        logger.info(f"Batch analysis completed with {len(responses)} successful items")
        return responses
        
    except Exception as e:
        logger.error(f"Batch analysis failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Batch analysis failed"
        )


# ============ Information Endpoints ============

from pathlib import Path

@router.get(
    "/datasets",
    tags=["Information"],
    summary="Get list of available log datasets (includes Jira)"
)
def get_datasets():
    """Get all available datasets — local JSON files + live Jira bugs."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    log_files = glob.glob(os.path.join(data_dir, "*.json"))

    datasets = []

    # Always list "Jira Bugs (Live)" as the first dataset
    datasets.append({
        "id": "jira-bugs",
        "name": "Jira Bugs (Live)",
        "path": "jira",
        "source": "jira",
    })

    # Then local scenario files
    for file in log_files:
        datasets.append({
            "id": os.path.basename(file),
            "name": os.path.basename(file).replace(".json", "").replace("_", " ").title(),
            "path": file,
            "source": "local",
        })

    return {"datasets": datasets}


@router.get(
    "/dataset/{dataset_id}",
    tags=["Information"],
    summary="Get specific dataset content by ID (supports 'jira-bugs')"
)
def get_dataset(dataset_id: str):
    """
    Get the content of a dataset.

    - **jira-bugs**: Fetches live bugs from Jira and converts them to
      the same log format the frontend expects.
    - **scenario_*.json**: Returns local file contents as before.
    """

    # ── Jira virtual dataset ──
    if dataset_id == "jira-bugs":
        try:
            from services.bug_rca.jira_client import get_jira_client
            client = get_jira_client()
            bugs = client.get_bugs(max_results=100, issue_type=None)

            # Convert Jira issues → log-entry format the frontend understands
            logs = []
            for bug in bugs:
                logs.append({
                    "timestamp": bug.get("created", ""),
                    "service_name": ", ".join(bug.get("components", [])) or bug.get("issue_type", "Bug"),
                    "error_message": bug.get("summary", ""),
                    "stack_trace": bug.get("description", ""),
                    "environment": "production",
                    "request_id": bug.get("key", ""),
                    "user_id": bug.get("reporter", ""),
                    "severity": _jira_priority_to_severity(bug.get("priority", "Medium")),
                    "status": bug.get("status", "To Do"),
                    "metadata": {
                        "jira_key": bug.get("key", ""),
                        "jira_url": bug.get("url", ""),
                        "assignee": bug.get("assignee", "Unassigned"),
                        "labels": bug.get("labels", []),
                        "resolution": bug.get("resolution"),
                        "updated": bug.get("updated", ""),
                    }
                })

            return logs
        except Exception as e:
            logger.error(f"Error fetching Jira bugs as dataset: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch bugs from Jira: {str(e)}"
            )

    # ── Local file dataset ──
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    file_path = os.path.join(data_dir, dataset_id)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found"
        )

    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error(f"Error reading dataset {dataset_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read dataset file"
        )


def _jira_priority_to_severity(priority: str) -> str:
    """Map Jira priority names to severity levels."""
    mapping = {
        "highest": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
        "lowest": "low",
    }
    return mapping.get(priority.lower(), "medium")


@router.get(
    "/info",
    tags=["Information"],
    summary="Get service information"
)
def get_info():
    """Get service metadata and capabilities"""
    
    return {
        "service": "bug_rca",
        "description": "Root Cause Analysis for bug logs",
        "version": "1.0.0",
        "capabilities": {
            "analysis_depths": ["quick", "standard", "detailed"],
            "max_logs_per_request": 50,
            "features": [
                "Error pattern extraction",
                "System dependency mapping",
                "Severity assessment",
                "Business impact analysis",
                "Actionable recommendations"
            ]
        },
        "endpoints": {
            "analyze": "POST /analyze",
            "quick_analyze": "POST /quick-analyze",
            "detailed_analyze": "POST /detailed-analyze",
            "batch_analyze": "POST /batch-analyze",
            "dashboard": "GET /dashboard",
            "analyze_with_description": "POST /analyze-with-description",
            "match_incident": "POST /match-incident",
            "match_and_analyze": "POST /match-and-analyze"
        }
    }


# ============ Dashboard & Statistics Endpoints ============

def _load_and_analyze_logs_from_files():
    """
    Load all log files AND live Jira bugs, then extract statistics.
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    log_files = glob.glob(os.path.join(data_dir, "*.json"))
    
    all_logs = []
    high_risk_count = 0
    medium_risk_count = 0
    low_risk_count = 0
    service_down_causes = {}
    error_messages = []

    # ── Pull Jira bugs as additional log entries ──
    try:
        from services.bug_rca.jira_client import get_jira_client
        client = get_jira_client()
        jira_bugs = client.get_bugs(max_results=100, issue_type=None)
        for bug in jira_bugs:
            sev = _jira_priority_to_severity(bug.get("priority", "Medium"))
            log_entry = {
                "timestamp": bug.get("created", ""),
                "service_name": ", ".join(bug.get("components", [])) or bug.get("issue_type", "Bug"),
                "error_message": bug.get("summary", ""),
                "environment": "production",
                "severity": sev,
                "status": bug.get("status", "To Do"),
                "metadata": {
                    "jira_key": bug.get("key", ""),
                    "source": "jira",
                }
            }

            if sev in ["critical", "high"]:
                high_risk_count += 1
            elif sev == "medium":
                medium_risk_count += 1
            else:
                low_risk_count += 1

            error_messages.append(bug.get("summary", ""))
            all_logs.append(log_entry)
    except Exception as e:
        logger.warning(f"Could not load Jira bugs for dashboard: {e}")

    # ── Local file logs ──
    try:
        for file_path in log_files:
            with open(file_path, 'r') as f:
                file_data = json.load(f)
                
                # Handle different data formats
                if isinstance(file_data, dict) and 'logs' in file_data:
                    logs = file_data['logs']
                elif isinstance(file_data, dict) and 'data' in file_data:
                    logs = file_data['data']
                elif isinstance(file_data, list):
                    logs = file_data
                else:
                    continue
                
                for log in logs:
                    # Extract severity from metadata or error message
                    severity = log.get('severity', 'medium')
                    if isinstance(severity, str):
                        severity = severity.lower()
                    
                    if severity in ['critical', 'high']:
                        high_risk_count += 1
                    elif severity == 'medium':
                        medium_risk_count += 1
                    else:
                        low_risk_count += 1
                    
                    # Track service down causes
                    if 'cause' in log:
                        cause = log.get('cause', 'unknown')
                        service_down_causes[cause] = service_down_causes.get(cause, 0) + 1
                    
                    # Collect error messages
                    error_msg = log.get('error_message', log.get('message', ''))
                    if error_msg:
                        error_messages.append(error_msg)
                    
                    all_logs.append(log)
    except Exception as e:
        logger.error(f"Error loading logs from files: {str(e)}")
    
    # Find most common error
    most_common_error = "Unknown"
    if error_messages:
        from collections import Counter
        error_counts = Counter(error_messages)
        most_common_error = error_counts.most_common(1)[0][0]
    
    return {
        "total_incidents": len(all_logs),
        "high_risk_incidents": high_risk_count,
        "medium_risk_incidents": medium_risk_count,
        "low_risk_incidents": low_risk_count,
        "service_down_causes": service_down_causes if service_down_causes else {"unknown": len(all_logs)},
        "most_common_error": most_common_error,
        "all_logs": all_logs,
        "last_incident_time": None  # Can be set from log timestamps if available
    }


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    tags=["Dashboard"],
    summary="Get incident dashboard with pre-populated questions"
)
def get_dashboard(time_window: str = Query("last_24h", description="Time window: last_24h, last_7d, last_30d")):
    """
    Get incident dashboard with statistics and pre-populated questions
    
    **Query Parameters:**
    - `time_window`: Time period for statistics (last_24h, last_7d, last_30d)
    
    **Returns:**
    Dashboard with incident statistics, pre-populated questions, insights, and suggested investigations
    
    **Example Response:**
    ```json
    {
        "statistics": {
            "total_incidents": 15,
            "high_risk_incidents": 3,
            "medium_risk_incidents": 7,
            "low_risk_incidents": 5,
            "service_down_causes": {
                "database_connection": 4,
                "memory_leak": 2,
                "timeout": 1
            },
            "most_common_error": "NullPointerException"
        },
        "questions": [
            {
                "question_id": "q1",
                "question": "What is the total number of incidents?",
                "metric_name": "total_incidents",
                "current_value": 15
            },
            {
                "question_id": "q2",
                "question": "How many high-risk incidents have occurred?",
                "metric_name": "high_risk_incidents",
                "current_value": 3
            }
        ],
        "insights": [
            "Database connection issues are the leading cause of service disruptions"
        ],
        "suggested_investigations": [
            "Review database connection pool configuration"
        ]
    }
    ```
    """
    
    try:
        logger.info(f"Dashboard request received for time window: {time_window}")
        
        # Load and analyze logs from data files
        stats = _load_and_analyze_logs_from_files()
        
        # Create dashboard statistics
        dashboard_stats = DashboardStatistics(
            total_incidents=stats["total_incidents"],
            high_risk_incidents=stats["high_risk_incidents"],
            medium_risk_incidents=stats["medium_risk_incidents"],
            low_risk_incidents=stats["low_risk_incidents"],
            service_down_causes=stats["service_down_causes"],
            most_common_error=stats["most_common_error"],
            incident_time_window=time_window
        )
        
        # Create pre-populated questions
        questions = [
            IncidentQuestion(
                question_id="q1",
                question="What is the total number of incidents in the system?",
                metric_name="total_incidents",
                current_value=stats["total_incidents"],
                description="Total count of all incidents detected in the system during the selected time period",
                trend="increasing" if stats["total_incidents"] > 10 else "stable"
            ),
            IncidentQuestion(
                question_id="q2",
                question="How many high-risk incidents have occurred?",
                metric_name="high_risk_incidents",
                current_value=stats["high_risk_incidents"],
                description="Number of incidents with critical or high severity that require immediate attention",
                trend="increasing" if stats["high_risk_incidents"] > 0 else "stable"
            ),
            IncidentQuestion(
                question_id="q3",
                question="How many low-risk incidents have occurred?",
                metric_name="low_risk_incidents",
                current_value=stats["low_risk_incidents"],
                description="Number of incidents with low severity that have minimal business impact",
                trend="decreasing" if stats["low_risk_incidents"] < 10 else "stable"
            ),
            IncidentQuestion(
                question_id="q4",
                question="What is causing the service down?",
                metric_name="service_down_causes",
                current_value=len(stats["service_down_causes"]),
                description="Types and frequencies of root causes leading to service disruptions",
                trend="stable"
            )
        ]
        
        # Generate insights
        insights = []
        if stats["high_risk_incidents"] > 0:
            insights.append(f"⚠️ {stats['high_risk_incidents']} high-risk incident(s) detected - immediate attention required")
        if stats["service_down_causes"]:
            top_cause = max(stats["service_down_causes"].items(), key=lambda x: x[1])
            insights.append(f"📊 '{top_cause[0]}' is the leading cause of service disruptions ({top_cause[1]} occurrences)")
        insights.append(f"🔍 Most common error: {stats['most_common_error']}")
        
        # Generate suggested investigations
        suggested_investigations = []
        for cause, count in stats["service_down_causes"].items():
            suggested_investigations.append(f"Investigate and fix '{cause}' (occurred {count} times)")
        suggested_investigations.append("Review error patterns in the validation layer")
        suggested_investigations.append("Implement monitoring for database connection issues")
        
        return DashboardResponse(
            statistics=dashboard_stats,
            questions=questions,
            insights=insights,
            suggested_investigations=suggested_investigations
        )
        
    except Exception as e:
        logger.error(f"Error in dashboard endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate dashboard"
        )


# ============ Full RCA Analysis Endpoint ============

@router.post(
    "/analyze-with-description",
    response_model=FullRCAResponse,
    status_code=status.HTTP_200_OK,
    tags=["Analysis"],
    summary="Full RCA analysis with issue description and auto-loaded logs"
)
def analyze_with_description(request: FullRCARequest) -> FullRCAResponse:
    """
    Perform full RCA analysis based on issue description
    
    This endpoint combines issue description with logs from the system to provide
    comprehensive Root Cause Analysis including impact assessment and recommendations.
    
    **Request Parameters:**
    - `issue_description`: Detailed description of the issue (required)
    - `issue_type`: Type of issue - service_down, performance, crash, etc. (required)
    - `affected_service`: Service name that is affected (required)
    - `start_time`: When the issue started (optional)
    - `end_time`: When the issue ended (optional)
    - `affected_users_count`: Estimated number of affected users (optional)
    - `logs`: Pre-loaded logs (optional - will auto-load from data if not provided)
    - `analysis_depth`: Analysis level - quick, standard, or detailed (default: detailed)
    
    **Response:**
    Complete RCA analysis with timeline, business impact, immediate actions, and preventive measures
    
    **Example Request:**
    ```json
    {
        "issue_description": "API Gateway service went down, users unable to authenticate. Multiple null pointer exceptions in request validation",
        "issue_type": "service_down",
        "affected_service": "api-gateway",
        "start_time": "2024-01-15T10:30:00Z",
        "affected_users_count": 5000,
        "analysis_depth": "detailed"
    }
    ```
    
    **Example Response:**
    ```json
    {
        "request_id": "550e8400-e29b-41d4-a716-446655440000",
        "issue_summary": "API Gateway service outage due to null pointer exceptions",
        "logs_analyzed": 150,
        "affected_services": ["api-gateway", "auth-service"],
        "business_impact_assessment": "Complete service outage affecting 5000+ users, estimated $50K revenue impact",
        "immediate_actions": [
            "Roll back last deployment",
            "Restart API Gateway service",
            "Monitor error rates"
        ],
        "preventive_measures": [
            "Add null-safety checks in validation layer",
            "Implement comprehensive unit tests",
            "Add pre-deployment validation"
        ],
        "confidence_score": 0.92
    }
    ```
    """
    
    import time
    request_start_time = time.time()
    
    try:
        logger.info(f"Received full RCA analysis request for service: {request.affected_service}")
        
        # Load logs from data files if not provided
        if not request.logs:
            logger.info("Auto-loading logs from data files")
            stats = _load_and_analyze_logs_from_files()
            
            # Convert loaded logs to BugLogEntry format if needed
            loaded_logs = []
            for log in stats["all_logs"][:MAX_LOGS_FOR_ANALYSIS]:  # Limit log count
                try:
                    if isinstance(log, dict):
                        # Convert dict to BugLogEntry
                        entry = BugLogEntry(
                            timestamp=log.get('timestamp', datetime.utcnow()),
                            service_name=log.get('service_name', request.affected_service),
                            error_message=log.get('error_message', log.get('message', '')),
                            stack_trace=log.get('stack_trace'),
                            environment=log.get('environment', 'production'),
                            metadata=log.get('metadata', {})
                        )
                        loaded_logs.append(entry)
                except Exception as e:
                    logger.warning(f"Could not parse log entry: {str(e)}")
                    continue
            
            request.logs = loaded_logs if loaded_logs else []
        
        if not request.logs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No logs available for analysis. Please provide logs or ensure data files exist."
            )
        
        # Perform RCA analysis using workflow
        rca_request = RCARequest(
            logs=request.logs,
            analysis_depth=request.analysis_depth,
            focus_areas=["null_safety", "validation", "error_handling", request.affected_service]
        )
        
        rca_response = workflow_graph.execute(rca_request)
        
        # Build timeline from logs
        timeline = []
        if request.logs:
            # Group logs by time
            sorted_logs = sorted(request.logs, key=lambda x: x.timestamp if x.timestamp else datetime.utcnow())
            for log in sorted_logs[:10]:  # Top 10 events in timeline
                timeline.append({
                    "time": log.timestamp.isoformat() if log.timestamp else datetime.utcnow().isoformat(),
                    "event": log.error_message[:100],
                    "service": log.service_name,
                    "severity": "high" if "null" in log.error_message.lower() else "medium"
                })
        
        # Extract affected services
        affected_services = list(set([
            request.affected_service,
            *rca_response.analysis.affected_systems
        ]))
        
        # Calculate business impact
        impact_str = f"Issue affecting {request.affected_service}"
        if request.affected_users_count:
            impact_str += f" - {request.affected_users_count:,} users impacted"
        if request.start_time and request.end_time:
            duration = (request.end_time - request.start_time).total_seconds() / 60
            impact_str += f" - Downtime: {int(duration)} minutes"
        
        # Generate immediate and preventive actions
        immediate_actions = [
            f"Immediately investigate {rca_response.analysis.root_cause}",
            f"Review logs on {request.affected_service} for error patterns",
            "Contact on-call engineer for {request.affected_service}",
            "Notify stakeholders of the incident status"
        ]
        
        preventive_measures = [
            f"Implement fix: {rca_response.analysis.recommendations[0] if rca_response.analysis.recommendations else 'Review code changes'}",
            *rca_response.analysis.recommendations[1:],
            "Add comprehensive error handling and logging",
            "Implement automated testing for validation layer"
        ]
        
        # Calculate processing time
        processing_time = (time.time() - request_start_time) * 1000
        
        response = FullRCAResponse(
            request_id=rca_response.request_id,
            issue_summary=request.issue_description[:200],
            analysis=rca_response.analysis,
            logs_analyzed=len(request.logs),
            timeline=timeline,
            affected_services=affected_services,
            business_impact_assessment=impact_str,
            immediate_actions=immediate_actions[:3],
            preventive_measures=preventive_measures[:3],
            confidence_score=rca_response.analysis.confidence_score,
            processing_time_ms=processing_time,
            model_used=rca_response.model_used
        )
        
        logger.info(f"Full RCA analysis completed. Request ID: {response.request_id}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in full RCA analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Full RCA analysis failed: {str(e)}"
        )


# ============ Bug Matching & RCA Endpoint ============

@router.post(
    "/match-incident",
    response_model=MatchedIncidentResponse,
    status_code=status.HTTP_200_OK,
    tags=["Matching"],
    summary="Match a description to a known incident and return its logs"
)
def match_incident(request: MatchIncidentRequest) -> MatchedIncidentResponse:
    """
    Describe a bug with keywords and get the raw logs for the best-matching incident from our dataset.

    This endpoint is a lightweight version of `/match-and-analyze`. It performs the same matching logic
    but returns only the matched incident's information and raw logs, without performing a full
    Root Cause Analysis.

    **Request Parameters:**
    - `bug_description`: Describe the bug you encountered with keywords (required, min 10 chars).

    **Response:**
    - `matched_scenario`: Details of the best-matching scenario.
    - `logs`: A list of raw log entries from the matched incident.
    """
    request_id = str(uuid.uuid4())
    logger.info(f"Received incident matching request. Description: {request.bug_description[:100]}...")

    # Find best matching scenario
    scenario_metadata, match_score, matched_keywords = _find_best_matching_scenario(request.bug_description)

    if not scenario_metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No matching incident found in dataset for the given description."
        )

    logger.info(f"Best match found for incident matching: {scenario_metadata['scenario_id']} with score {match_score:.2f}")

    # Create BugLogEntry objects from matched scenario logs
    matched_logs = []
    for log in scenario_metadata['logs']: # Return all logs for this one
        try:
            entry = BugLogEntry.model_validate(log)
            matched_logs.append(entry)
        except Exception as e:
            logger.warning(f"Could not parse log entry in matched incident: {str(e)}")
            continue

    # Create matched scenario response object
    matched_scenario_obj = MatchedScenario(
        scenario_id=scenario_metadata['scenario_id'],
        scenario_name=scenario_metadata['scenario_name'],
        match_score=match_score,
        matched_keywords=matched_keywords,
        primary_error_type=scenario_metadata['primary_error'],
        affected_services_in_scenario=scenario_metadata['services'],
        error_count_in_dataset=scenario_metadata['error_count'],
        description=f"This scenario involves {scenario_metadata['scenario_name'].lower()}"
    )

    return MatchedIncidentResponse(
        request_id=request_id,
        matched_scenario=matched_scenario_obj,
        logs=matched_logs
    )

def _extract_scenario_metadata(file_path: str, file_name: str) -> dict:
    """
    Extract metadata from a scenario file for matching purposes
    """
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Handle different data formats
        logs = data if isinstance(data, list) else data.get('logs', data.get('data', []))
        
        if not logs:
            return None
        
        # Extract key information
        error_messages = [log.get('error_message', '') for log in logs if isinstance(log, dict)]
        services = list(set([log.get('service_name', 'unknown') for log in logs if isinstance(log, dict) and log.get('service_name')]))
        
        # Find primary error type
        primary_error = error_messages[0] if error_messages else "Unknown Error"
        
        # Create keywords from file name and error messages
        keywords = []
        file_keywords = file_name.replace('.json', '').replace('scenario_', '').replace('_', ' ').lower().split()
        keywords.extend(file_keywords)
        
        for error in error_messages[:3]:  # First 3 errors
            error_lower = error.lower()
            if 'exception' in error_lower or 'error' in error_lower:
                # Extract error type
                parts = error_lower.split(':')[0].split()
                keywords.extend(parts)
        
        keywords = list(set([k for k in keywords if len(k) > 2]))  # Remove short keywords
        
        return {
            "file_name": file_name,
            "scenario_id": file_name.replace('.json', ''),
            "scenario_name": file_name.replace('scenario_', '').replace('_', ' ').replace('.json', '').title(),
            "primary_error": primary_error,
            "error_count": len(error_messages),
            "services": services,
            "keywords": keywords,
            "error_messages": error_messages,
            "logs": logs
        }
    except Exception as e:
        logger.warning(f"Error extracting metadata from {file_name}: {str(e)}")
        return None


def _calculate_match_score(user_description: str, scenario_metadata: dict) -> Tuple[float, List[str]]:
    """
    Calculate match score between user description and scenario
    Returns: (score: 0-1, matched_keywords: list)
    """
    if not scenario_metadata:
        return 0.0, []
    
    user_desc_lower = user_description.lower()
    matched_keywords = []
    score = 0.0
    
    # Keyword matching
    for keyword in scenario_metadata['keywords']:
        if keyword in user_desc_lower:
            matched_keywords.append(keyword)
            score += MATCHING_SCORE_WEIGHTS["keyword"]
    
    # Error type matching
    primary_error_lower = scenario_metadata['primary_error'].lower()
    if primary_error_lower in user_desc_lower:
        if 'primary_error' not in matched_keywords:
            matched_keywords.append(primary_error_lower)
        score += MATCHING_SCORE_WEIGHTS["error_type"]
    
    # Service name matching
    for service in scenario_metadata['services']:
        service_lower = service.lower()
        if service_lower in user_desc_lower:
            if service_lower not in matched_keywords:
                matched_keywords.append(service_lower)
            score += MATCHING_SCORE_WEIGHTS["service_name"]
    
    # Error message similarity
    for error_msg in scenario_metadata['error_messages'][:2]:
        error_lower = error_msg.lower()
        # Use simple substring matching for error messages
        if error_lower in user_desc_lower or user_desc_lower in error_lower:
            score += MATCHING_SCORE_WEIGHTS["error_message"]
            break
    
    # Sequence matching for overall similarity
    similarity = SequenceMatcher(None, user_desc_lower, primary_error_lower).ratio()
    score += similarity * MATCHING_SCORE_WEIGHTS["similarity"]
    
    # Cap score at 1.0
    score = min(score, 1.0)
    
    return score, matched_keywords


def _find_best_matching_scenario(user_description: str) -> Tuple[dict, float, List[str]]:
    """
    Find the best matching scenario from dataset
    Returns: (scenario_metadata, match_score, matched_keywords)
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    log_files = glob.glob(os.path.join(data_dir, "*.json"))
    
    best_match = None
    best_score = 0.0
    best_keywords = []
    
    for file_path in log_files:
        file_name = os.path.basename(file_path)
        metadata = _extract_scenario_metadata(file_path, file_name)
        
        if metadata:
            score, keywords = _calculate_match_score(user_description, metadata)
            
            if score > best_score:
                best_score = score
                best_match = metadata
                best_keywords = keywords
    
    return best_match, best_score, best_keywords


@router.post(
    "/match-and-analyze",
    response_model=BugMatchingResponse,
    status_code=status.HTTP_200_OK,
    tags=["Matching"],
    summary="Match bug description to dataset and generate RCA"
)
def match_and_analyze_bug(request: BugMatchingRequest) -> BugMatchingResponse:
    """
    Describe a bug and get RCA for the matching bug from our dataset
    
    This endpoint:
    1. Takes your bug description
    2. Searches through our dataset of known bugs
    3. Finds the best matching bug scenario
    4. Generates comprehensive RCA for that matched bug
    
    **Request Parameters:**
    - `bug_description`: Describe the bug you encountered (required, min 10 chars)
    - `analysis_depth`: Analysis detail level - quick, standard, or detailed (default: detailed)
    
    **Response:**
    - Matched scenario with match score and keywords
    - Complete RCA analysis for the matched bug
    - Timeline of events from the matched dataset
    - Business impact and recommended actions
    
    **Example Request:**
    ```json
    {
        "bug_description": "Users are getting null pointer exceptions when they try to authenticate. The API gateway keeps crashing.",
        "analysis_depth": "detailed"
    }
    ```
    
    **Example Response:**
    ```json
    {
        "request_id": "550e8400-...",
        "matched_scenario": {
            "scenario_id": "scenario_1_null_pointer",
            "scenario_name": "Null Pointer Exception in Request Validation",
            "match_score": 0.95,
            "matched_keywords": ["null pointer", "exception", "authentication"],
            "primary_error_type": "NullPointerException in RequestValidator",
            "affected_services_in_scenario": ["api-gateway", "auth-service"],
            "error_count_in_dataset": 45,
            "description": "NullPointerException occurring in request validation layer"
        },
        "analysis": {
            "root_cause": "Null pointer in request validation when input is null",
            "severity": "critical",
            "confidence_score": 0.93
        },
        "logs_analyzed": 45,
        "timeline": [{"time": "2024-01-15T10:00:00Z", "event": "First error detected"}],
        "immediate_actions": ["Add null input validation", "Implement defensive checks"],
        "preventive_measures": ["Enhanced input validation", "Unit test coverage"]
    }
    ```
    """
    
    import time
    request_start_time = time.time()
    
    try:
        logger.info(f"Received bug matching request. Description: {request.bug_description[:100]}...")
        
        # Find best matching scenario
        scenario_metadata, match_score, matched_keywords = _find_best_matching_scenario(request.bug_description)
        
        if not scenario_metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No matching bug scenarios found in dataset. Please refine your description."
            )
        
        logger.info(f"Best match found: {scenario_metadata['scenario_id']} with score {match_score:.2f}")
        
        # Create BugLogEntry objects from matched scenario logs
        matched_logs = []
        for log in scenario_metadata['logs'][:MAX_LOGS_FOR_ANALYSIS]:  # Limit log count
            try:
                entry = BugLogEntry(
                    timestamp=log.get('timestamp', datetime.utcnow()),
                    service_name=log.get('service_name', 'unknown'),
                    error_message=log.get('error_message', log.get('message', '')),
                    stack_trace=log.get('stack_trace'),
                    environment=log.get('environment', 'production'),
                    user_id=log.get('user_id'),
                    request_id=log.get('request_id'),
                    metadata=log.get('metadata', {})
                )
                matched_logs.append(entry)
            except Exception as e:
                logger.warning(f"Could not parse log entry: {str(e)}")
                continue
        
        # Perform RCA analysis on matched logs
        rca_request = RCARequest(
            logs=matched_logs,
            analysis_depth=request.analysis_depth,
            focus_areas=[matched_keywords[0]] if matched_keywords else []
        )
        
        rca_response = workflow_graph.execute(rca_request)
        
        # Build timeline from matched logs
        timeline = []
        if matched_logs:
            sorted_logs = sorted(matched_logs, key=lambda x: x.timestamp if x.timestamp else datetime.utcnow())
            for log in sorted_logs[:10]:  # Top 10 events
                timeline.append({
                    "time": log.timestamp.isoformat() if log.timestamp else datetime.utcnow().isoformat(),
                    "event": log.error_message[:100],
                    "service": log.service_name,
                    "severity": "high" if any(kw in log.error_message.lower() for kw in ["error", "exception"]) else "medium"
                })
        
        # Create matched scenario response object
        matched_scenario = MatchedScenario(
            scenario_id=scenario_metadata['scenario_id'],
            scenario_name=scenario_metadata['scenario_name'],
            match_score=match_score,
            matched_keywords=matched_keywords,
            primary_error_type=scenario_metadata['primary_error'],
            affected_services_in_scenario=scenario_metadata['services'],
            error_count_in_dataset=scenario_metadata['error_count'],
            description=f"This scenario involves {scenario_metadata['scenario_name'].lower()}"
        )
        
        # Calculate business impact
        impact_str = f"Matched scenario: {scenario_metadata['scenario_name']}"
        if scenario_metadata['services']:
            impact_str += f" affecting {', '.join(scenario_metadata['services'])}"
        
        # Generate actions based on matched scenario
        immediate_actions = [
            f"Review fix for: {rca_response.analysis.root_cause}",
            f"Check deployment history for {', '.join(scenario_metadata['services'])}",
            "Prioritize fixing the validation layer"
        ]
        
        preventive_measures = rca_response.analysis.recommendations[:3] if rca_response.analysis.recommendations else [
            "Implement input validation",
            "Add error handling",
            "Enhanced testing"
        ]
        
        # Calculate processing time
        processing_time = (time.time() - request_start_time) * 1000
        
        response = BugMatchingResponse(
            request_id=rca_response.request_id,
            matched_scenario=matched_scenario,
            issue_summary=f"Matched to: {scenario_metadata['scenario_name']}",
            analysis=rca_response.analysis,
            logs_analyzed=len(matched_logs),
            timeline=timeline,
            affected_services=list(set(scenario_metadata['services']) | set(rca_response.analysis.affected_systems)),
            business_impact_assessment=impact_str,
            immediate_actions=immediate_actions,
            preventive_measures=preventive_measures,
            confidence_score=match_score * rca_response.analysis.confidence_score,
            processing_time_ms=processing_time,
            model_used=rca_response.model_used
        )
        
        logger.info(f"Bug matching and RCA completed. Match score: {match_score:.2f}, Request ID: {response.request_id}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bug matching: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bug matching failed: {str(e)}"
        )


# ============ Jira Integration Endpoints ============

@router.get(
    "/jira/bugs",
    tags=["Jira Integration"],
    summary="Fetch bugs from Jira",
)
def get_jira_bugs(
    jira_status: Optional[str] = Query(None, alias="status", description="Filter by Jira status, e.g. 'To Do', 'In Progress', 'Done'"),
    max_results: int = Query(50, ge=1, le=100, description="Maximum bugs to return"),
    issue_type: str = Query("Bug", description="Jira issue type to filter (use empty string for all)"),
):
    """
    Fetch bugs/issues from Jira Cloud.

    Returns a list of normalized bug objects with fields like key, summary,
    description, status, priority, assignee, etc.
    """
    try:
        from services.bug_rca.jira_client import get_jira_client
        client = get_jira_client()
        bugs = client.get_bugs(
            status=jira_status,
            max_results=max_results,
            issue_type=issue_type if issue_type else None,
        )
        return {
            "total": len(bugs),
            "project": client.project_key,
            "bugs": bugs,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Jira fetch failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch bugs from Jira: {str(e)}",
        )


@router.get(
    "/jira/bugs/{issue_key}",
    tags=["Jira Integration"],
    summary="Get a single Jira issue by key",
)
def get_jira_bug(issue_key: str):
    """Fetch details for a single Jira issue (e.g. KAN-1)."""
    try:
        from services.bug_rca.jira_client import get_jira_client
        client = get_jira_client()
        bug = client.get_issue(issue_key)
        return bug
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Jira issue fetch failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch issue {issue_key} from Jira: {str(e)}",
        )


@router.get(
    "/jira/statuses",
    tags=["Jira Integration"],
    summary="Get available Jira statuses for the project",
)
def get_jira_statuses():
    """Return the list of available workflow statuses for the configured Jira project."""
    try:
        from services.bug_rca.jira_client import get_jira_client
        client = get_jira_client()
        statuses = client.get_statuses()
        return {"project": client.project_key, "statuses": statuses}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Jira statuses fetch failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch statuses from Jira: {str(e)}",
        )


def status_code_503():
    """Helper to return 503 status code."""
    return 503