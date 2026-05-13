import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000")

LLM_MODEL = "gemma2-9b-it"
TOOL_TIMEOUT = 30.0
AGENT_TIMEOUT = 120.0
