import os
import pandas as pd
from sqlalchemy import create_engine, text

# SQLite DB — use /tmp on Vercel (only writable dir in serverless)
if os.environ.get("VERCEL"):
    DATABASE_URL = "sqlite:////tmp/rbac.db"
else:
    DATABASE_URL = "sqlite:///./rbac.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# Multiple data folders (add more as needed)
DATA_FOLDERS = [
    "services/user_access/data",
    "services/incident_triage/data"
]

def get_existing_tables(engine):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table';")
        )
        return {row[0] for row in result.fetchall()}

def load_new_tables(engine):
    print("Checking for new tables...")

    existing_tables = get_existing_tables(engine)

    loaded_any = False

    for folder in DATA_FOLDERS:
        if not os.path.exists(folder):
            print(f"Skipping missing folder: {folder}")
            continue

        for file in os.listdir(folder):
            if not file.endswith(".csv"):
                continue

            table_name = file.replace(".csv", "")

            if table_name in existing_tables:
                continue

            file_path = os.path.join(folder, file)

            print(f"Loading new table: {table_name} from {file_path}")

            df = pd.read_csv(file_path)

            df.to_sql(
                table_name,
                engine,
                if_exists="fail",  # ensures no overwrite
                index=False
            )

            loaded_any = True
            print(f"Loaded {table_name}")

    if not loaded_any:
        print("No new tables found. DB is up to date.")
    else:
        print("New tables added successfully!")

def initialize_database():
    load_new_tables(engine)