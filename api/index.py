"""
Vercel serverless entry point — wraps the FastAPI app.
"""
import sys
import os

# Ensure the project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env variables if present (Vercel uses Environment Variables in dashboard)
from dotenv import load_dotenv
load_dotenv()

from main import app
