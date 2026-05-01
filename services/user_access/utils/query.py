import os
import csv
import uuid

from datetime import datetime
from sqlalchemy import text

from database import engine

def get_access_requests_by_status(status: str):
    query = text("""
        SELECT 
            ar.request_id,
            ar.user_id,
            u.name AS user_name,
            ar.resource_id,
            r.resource_name,
            ar.requested_action,
            ar.status,
            ar.created_at
        FROM access_requests ar
        JOIN users u ON ar.user_id = u.user_id
        JOIN resources r ON ar.resource_id = r.resource_id
        WHERE LOWER(ar.status) = LOWER(:status)
        ORDER BY ar.created_at DESC
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"status": status})
        rows = result.fetchall()

    return [dict(row._mapping) for row in rows]

def get_request_base(request_id: str):
    query = text("""
        SELECT 
            ar.request_id,
            ar.user_id,
            u.name AS user_name,
            ar.resource_id,
            r.resource_name,
            r.resource_type,
            r.sensitivity,
            ar.requested_action,
            ar.scope_id,
            ar.justification
        FROM access_requests ar
        JOIN users u ON ar.user_id = u.user_id
        JOIN resources r ON ar.resource_id = r.resource_id
        WHERE ar.request_id = :request_id
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"request_id": request_id}).fetchone()

    return dict(result._mapping) if result else None

def get_user_roles(user_id: str):
    query = text("""
        SELECT 
            r.role_name,
            ur.scope_id
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = :user_id
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"user_id": user_id}).fetchall()

    return [
        {"role": row.role_name, "scope": row.scope_id}
        for row in result
    ]

def get_required_permission(action: str, resource_type: str):
    query = text("""
        SELECT permission_id
        FROM permissions
        WHERE action = :action
          AND resource_type = :resource_type
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            "action": action,
            "resource_type": resource_type
        }).fetchone()

    return result.permission_id if result else None

def get_roles_for_permission(permission_id: str):
    query = text("""
        SELECT r.role_name
        FROM role_permissions rp
        JOIN roles r ON rp.role_id = r.role_id
        WHERE rp.permission_id = :permission_id
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            "permission_id": permission_id
        }).fetchall()

    return [row.role_name for row in result]

def get_historical_requests(action: str, resource_type: str, scope_id: str, request_id: str):
    query = text("""
        SELECT 
            ar.request_id,
            ad.decision,
            ad.decided_at
        FROM access_requests ar
        JOIN resources r ON ar.resource_id = r.resource_id
        JOIN access_decisions ad ON ar.request_id = ad.request_id
        WHERE 
            ar.requested_action = :action
            AND r.resource_type = :resource_type
            AND ar.scope_id = :scope_id
            AND ar.request_id != :request_id
        ORDER BY ad.decided_at DESC
        LIMIT 10
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            "action": action,
            "resource_type": resource_type,
            "scope_id": scope_id,
            "request_id": request_id
        }).fetchall()

    approved = []
    rejected = []

    for row in result:

        if row.decision == "APPROVED":
            approved.append(row.request_id)
        elif row.decision == "REJECTED":
            rejected.append(row.request_id)

    return {
        "approved_request_ids": approved,
        "rejected_request_ids": rejected
    }

def get_user_id_from_request(request_id: str):
    query = text("""
        SELECT user_id FROM access_requests
        WHERE request_id = :request_id
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"request_id": request_id}).fetchone()

    return result.user_id if result else None

def update_request_status(request_id: str, status: str):
    query = text("""
        UPDATE access_requests
        SET status = :status
        WHERE request_id = :request_id
    """)

    with engine.begin() as conn:
        conn.execute(query, {
            "status": status,
            "request_id": request_id
        })

def insert_access_decision(request_id: str, approver_id: str, decision: str, comments: str | None):
    query = text("""
        INSERT INTO access_decisions (
            decision_id,
            request_id,
            approver_id,
            decision,
            comments,
            decided_at
        )
        VALUES (
            :decision_id,
            :request_id,
            :approver_id,
            :decision,
            :comments,
            :decided_at
        )
    """)

    with engine.begin() as conn:
        conn.execute(query, {
            "decision_id": str(uuid.uuid4()),
            "request_id": request_id,
            "approver_id": approver_id,
            "decision": decision,
            "comments": comments,
            "decided_at": datetime.utcnow()
        })

def assign_roles(user_id: str, roles: list):
    query = text("""
        INSERT INTO user_roles (
            user_id,
            role_id,
            scope_type,
            scope_id,
            granted_at
        )
        VALUES (
            :user_id,
            :role_id,
            'study',
            :scope_id,
            :granted_at
        )
    """)

    with engine.begin() as conn:
        for role in roles:
            # resolve role_id from role_name
            role_lookup = conn.execute(
                text("SELECT role_id FROM roles WHERE role_name = :role_name"),
                {"role_name": role["role"]}
            ).fetchone()

            if not role_lookup:
                continue

            conn.execute(query, {
                "user_id": user_id,
                "role_id": role_lookup.role_id,
                "scope_id": role["scope"],
                "granted_at": datetime.utcnow()
            })

def get_latest_request_id():
    query = text("""
        SELECT request_id FROM access_requests
        WHERE request_id LIKE 'REQ%'
    """)
    with engine.connect() as conn:
        result = conn.execute(query).fetchall()
        if not result:
            return "REQ000"
        
        max_num = 0
        for row in result:
            num_str = row[0].replace('REQ', '')
            try:
                max_num = max(max_num, int(num_str))
            except ValueError:
                pass
        return f"REQ{max_num:03d}"

def get_resource_id_by_name(resource_name: str):
    query = text("SELECT resource_id FROM resources WHERE resource_name = :resource_name")
    with engine.connect() as conn:
        result = conn.execute(query, {"resource_name": resource_name}).fetchone()
    return result.resource_id if result else None

def ensure_user_exists(user_id: str, user_name: str):
    if not user_id or user_id.lower() == "string":
        user_id = "U999"
    if not user_name or user_name.lower() == "string":
        user_name = "Sachin"
        
    query = text("SELECT user_id FROM users WHERE user_id = :user_id")
    with engine.connect() as conn:
        result = conn.execute(query, {"user_id": user_id}).fetchone()
        
    if not result:
        insert_query = text("""
            INSERT INTO users (user_id, name, email, department, title, status)
            VALUES (:user_id, :name, :email, :department, :title, :status)
        """)
        with engine.begin() as conn:
            conn.execute(insert_query, {
                "user_id": user_id,
                "name": user_name,
                "email": f"{user_name.lower().replace(' ', '.')}@pharma.com",
                "department": "Engineering",
                "title": "Software Engineer",
                "status": "active"
            })
            
        csv_path = os.path.join("services", "user_access", "data", "users.csv")
        with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                user_id,
                user_name,
                f"{user_name.lower().replace(' ', '.')}@pharma.com",
                "Engineering",
                "Software Engineer",
                "active"
            ])
            
    return user_id

def create_access_request(data: dict):
    resource_id = get_resource_id_by_name(data.get("resource_name", ""))
    if not resource_id:
        raise ValueError(f"Resource with name '{data.get('resource_name')}' not found")

    final_user_id = ensure_user_exists(data.get("user_id", ""), data.get("user_name", ""))

    latest_id = get_latest_request_id()
    num = int(latest_id.replace("REQ", "")) + 1
    new_id = f"REQ{num:03d}"

    
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    csv_path = os.path.join("services", "user_access", "data", "access_requests.csv")
    with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            new_id,
            final_user_id,
            resource_id,
            data.get("requested_action", ""),
            data.get("scope_type", "study"),
            data.get("scope_id", ""),
            data.get("justification", ""),
            "PENDING",
            now
        ])
    
    insert_query = text("""
        INSERT INTO access_requests (
            request_id, user_id, resource_id, requested_action,
            scope_type, scope_id, justification, status, created_at
        ) VALUES (
            :request_id, :user_id, :resource_id, :requested_action,
            :scope_type, :scope_id, :justification, 'PENDING', :created_at
        )
    """)
    with engine.connect() as conn:
        conn.execute(insert_query, {
            "request_id": new_id,
            "user_id": final_user_id,
            "resource_id": resource_id,
            "requested_action": data.get("requested_action", ""),
            "scope_type": data.get("scope_type", "study"),
            "scope_id": data.get("scope_id", ""),
            "justification": data.get("justification", ""),
            "created_at": now
        })
        conn.commit()
    
    return new_id