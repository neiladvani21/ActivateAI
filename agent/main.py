import asyncio
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import run_with_history
from config import AGENT_TIMEOUT
from database import delete_session, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Location Moment Trigger Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_thread_pool = ThreadPoolExecutor(max_workers=4)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    local_time: Optional[str] = None


class POIData(BaseModel):
    name: str
    lat: float
    lon: float
    distance_m: float
    type: str


class ChatResponse(BaseModel):
    response: str
    tools_used: List[str]
    session_id: str
    pois: List[POIData] = []
    geofence_radius_m: Optional[int] = None
    map_center: Optional[Dict[str, float]] = None


def _extract_map_data(intermediate_steps: list) -> tuple[list, Optional[int], Optional[dict]]:
    """Pull POI list, geofence radius, and map center from agent intermediate steps."""
    pois = []
    geofence_radius_m = None
    map_center = None

    for action, observation in intermediate_steps:
        tool_name = getattr(action, "tool", "")

        if tool_name == "search_pois" and isinstance(observation, str):
            match = re.search(r"__POI_DATA_JSON__:(\[.*\])", observation, re.DOTALL)
            if match:
                try:
                    pois = json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass

        if tool_name == "suggest_geofence" and isinstance(observation, str):
            match = re.search(r"(\d+)m", observation)
            if match:
                geofence_radius_m = int(match.group(1))

        if tool_name == "geocode_location" and isinstance(observation, str):
            lat_match = re.search(r"lat=([-\d]+\.[\d]+)", observation)
            lon_match = re.search(r"lon=([-\d]+\.[\d]+)", observation)
            if lat_match and lon_match:
                map_center = {
                    "lat": float(lat_match.group(1)),
                    "lon": float(lon_match.group(1)),
                }

    return pois, geofence_radius_m, map_center


def _run_agent(session_id: str, message: str, local_time: str) -> dict:
    return run_with_history(session_id, message, local_time)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    local_time = request.local_time or "unknown"

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_thread_pool, _run_agent, session_id, request.message, local_time),
            timeout=AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Agent timed out. Please retry.")

    steps = result.get("intermediate_steps", [])

    tools_used = list(dict.fromkeys(
        step[0].tool
        for step in steps
        if hasattr(step[0], "tool")
    ))

    pois, geofence_radius_m, map_center = _extract_map_data(steps)

    return ChatResponse(
        response=result["output"],
        tools_used=tools_used,
        session_id=session_id,
        pois=[POIData(**p) for p in pois],
        geofence_radius_m=geofence_radius_m,
        map_center=map_center,
    )


@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    delete_session(session_id)
    return {"status": "cleared", "session_id": session_id}
