from sqlalchemy import text
from database import engine

with engine.connect() as conn:
    # Find all UI-submitted test incidents (INC4002xxx)
    result = conn.execute(text("""
        SELECT "Number", "Short description", "Affected User" 
        FROM incidents 
        WHERE "Number" LIKE 'INC4002%'
    """))
    rows = result.fetchall()
    
    if not rows:
        print("No UI-submitted test incidents found in DB.")
    else:
        print(f"Found {len(rows)} UI-submitted incident(s) to remove:")
        for row in rows:
            print(f"  {row[0]} - {row[1]} ({row[2]})")
        
        conn.execute(text("""DELETE FROM incidents WHERE "Number" LIKE 'INC4002%'"""))
        conn.commit()
        print("Deleted from DB!")

# Also clean CSV
import csv
import os

csv_path = os.path.join("services", "incident_triage", "data", "incidents.csv")
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = list(reader)

original = len(rows)
clean_rows = [row for row in rows if row and not row[1].strip().startswith("INC4002")]
removed = original - len(clean_rows)

with open(csv_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(clean_rows)

print(f"CSV cleaned: removed {removed} test row(s), {len(clean_rows)} incidents remain.")
