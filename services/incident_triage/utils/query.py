import os
import csv
from database import engine
from sqlalchemy import text

def get_closed_incidents():
    query = text("""
        SELECT 
            Number as number,
            "Short description" as short_description,
            Description as description,
            State as state,
            Resolution as resolution
        FROM incidents
        WHERE LOWER(State) IN ('closed', 'resolved')
    """)

    with engine.connect() as conn:
        result = conn.execute(query)
        rows = result.fetchall()

    return [row._mapping for row in rows]

def get_incidents(status: str):
    query = text("""
        SELECT 
            Number as number,
            "Short description" as short_description,
            "Assigned To" as assigned_to,
            State as state
        FROM incidents
        WHERE LOWER(State) = :status
        ORDER BY Number DESC
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"status": status.lower()})
        rows = result.fetchall()
    
    return rows

def get_incident_by_id(incident_id: str):
    if not incident_id:
        return []

    query = text(f"""
        SELECT 
            Number as number,
            "Short description" as short_description,
            Description as description,
            State as state
        FROM incidents
        WHERE Number = :id
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"id": incident_id})
        row = result.fetchone()

    return row._mapping if row else None

def get_incidents_by_ids(incident_ids: list[str]):
    if not incident_ids:
        return []

    # Create dynamic placeholders
    placeholders = ", ".join([f":id{i}" for i in range(len(incident_ids))])

    query = text(f"""
        SELECT 
            Number as number,
            "Short description" as short_description,
            Description as description,
            Resolution as resolution,
            State as state
        FROM incidents
        WHERE Number IN ({placeholders})
    """)

    # Build params dict
    params = {f"id{i}": incident_ids[i] for i in range(len(incident_ids))}

    with engine.connect() as conn:
        result = conn.execute(query, params)
        rows = result.fetchall()

    return [row._mapping for row in rows]

def update_incident_resolution(incident_id: str, resolution: str):
    query = text("""
        UPDATE incidents
        SET 
            Resolution = :resolution,
            State = 'Resolved'
        WHERE Number = :incident_id
    """)

    with engine.connect() as conn:
        conn.execute(query, {
            "incident_id": incident_id,
            "resolution": resolution
        })
        conn.commit()

def get_latest_incident_number():
    query = text("""
        SELECT Number FROM incidents
        WHERE Number LIKE 'INC%'
        ORDER BY Number DESC LIMIT 1
    """)
    with engine.connect() as conn:
        result = conn.execute(query)
        row = result.fetchone()
        return row[0] if row else "INC4001000"

def create_incident(incident_data: dict):
    csv_path = os.path.join("services", "incident_triage", "data", "incidents.csv")
    if not os.environ.get("VERCEL"):
        with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                incident_data.get("affected_user", ""),
                incident_data.get("number", ""),
                incident_data.get("short_description", ""),
                incident_data.get("description", ""),
                incident_data.get("assigned_to", ""),
                incident_data.get("state", ""),
                incident_data.get("resolution", "")
            ])

    insert_query = text("""
        INSERT INTO incidents (
            "Affected User", "Number", "Short description", "Description", 
            "Assigned To", "State", "Resolution"
        ) VALUES (
            :affected_user, :number, :short_description, :description, 
            :assigned_to, :state, :resolution
        )
    """)
    with engine.connect() as conn:
        conn.execute(insert_query, {
            "affected_user": incident_data.get("affected_user", ""),
            "number": incident_data.get("number", ""),
            "short_description": incident_data.get("short_description", ""),
            "description": incident_data.get("description", ""),
            "assigned_to": incident_data.get("assigned_to", ""),
            "state": incident_data.get("state", ""),
            "resolution": incident_data.get("resolution", "")
        })
        conn.commit()

