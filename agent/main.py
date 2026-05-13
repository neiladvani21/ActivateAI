import asyncio
import json
import re
import uuid
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from agent import run_with_history, stream_with_history
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

# In-memory store of last extracted offer copy per session
# { session_id: "Beat the morning rush at SoulCycle" }
_session_offer_copy: Dict[str, str] = {}

BANNER_KEYWORDS = [
    "generate image", "create image", "make image",
    "generate banner", "create banner", "make banner",
    "show banner", "show image", "create a banner", "generate a banner",
]

def _is_banner_only_request(message: str) -> bool:
    msg = message.lower().strip()
    return any(kw in msg for kw in BANNER_KEYWORDS)

def _extract_offer_copy(response_text: str) -> Optional[str]:
    """Extract offer copy from agent response and return the raw string (no URL)."""
    match = re.search(u'["""]([A-Z][^"""]{20,200})["""]', response_text)
    if not match:
        match = re.search(
            r'(?:suggested offer copy|offer copy)\s*(?:could be)?\s*[:\*]+\s*[""]?(.{20,200}?)[""!]?(?:\n|$)',
            response_text,
            re.IGNORECASE,
        )
    if not match:
        return None
    offer_copy = match.group(1).strip().strip('"').strip("'")
    if "[" in offer_copy or "Coffee Shop Name" in offer_copy:
        return None
    return offer_copy

def _build_image_url_from_copy(offer_copy: str) -> str:
    prompt = (
        f"Professional retail marketing banner, bold typography, vibrant colors. "
        f"Campaign message: {offer_copy}. "
        f"Clean modern design, no people, suitable for digital advertising."
    )
    return f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=800&height=400&nologo=true&seed=42"


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
    image_url: Optional[str] = None


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


def _build_image_url(response_text: str) -> Optional[str]:
    offer_copy = _extract_offer_copy(response_text)
    if not offer_copy:
        return None
    return _build_image_url_from_copy(offer_copy)


def _run_agent(session_id: str, message: str, local_time: str) -> dict:
    return run_with_history(session_id, message, local_time)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    local_time = request.local_time or "unknown"

    # Banner-only shortcut — skip agent entirely
    if _is_banner_only_request(request.message) and session_id in _session_offer_copy:
        offer_copy = _session_offer_copy[session_id]
        image_url = f"http://localhost:8001/image-proxy?url={quote(_build_image_url_from_copy(offer_copy), safe='')}"
        return ChatResponse(
            response=f'Generating your campaign banner with the offer: "{offer_copy}"',
            tools_used=[],
            session_id=session_id,
            pois=[],
            geofence_radius_m=None,
            map_center=None,
            image_url=image_url,
        )

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
        step[0].tool for step in steps if hasattr(step[0], "tool")
    ))
    pois, geofence_radius_m, map_center = _extract_map_data(steps)

    # Save offer copy for future banner requests
    offer_copy = _extract_offer_copy(result["output"])
    if offer_copy:
        _session_offer_copy[session_id] = offer_copy

    wants_image = _is_banner_only_request(request.message)
    image_url = _build_image_url(result["output"]) if wants_image else None
    if image_url:
        image_url = f"http://localhost:8001/image-proxy?url={quote(image_url, safe='')}"

    return ChatResponse(
        response=result["output"],
        tools_used=tools_used,
        session_id=session_id,
        pois=[POIData(**p) for p in pois],
        geofence_radius_m=geofence_radius_m,
        map_center=map_center,
        image_url=image_url,
    )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    local_time = request.local_time or "unknown"

    # Banner-only shortcut — skip agent entirely
    if _is_banner_only_request(request.message) and session_id in _session_offer_copy:
        offer_copy = _session_offer_copy[session_id]
        image_url = f"http://localhost:8001/image-proxy?url={quote(_build_image_url_from_copy(offer_copy), safe='')}"

        async def banner_generator():
            yield f"data: {json.dumps({'type': 'token', 'content': f'Generating your campaign banner with the offer: \"{offer_copy}\"'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'tools_used': [], 'pois': [], 'geofence_radius_m': None, 'map_center': None, 'image_url': image_url})}\n\n"

        return StreamingResponse(
            banner_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    wants_image = _is_banner_only_request(request.message)

    async def event_generator():
        try:
            async for chunk in stream_with_history(session_id, request.message, local_time):
                if chunk["type"] == "token":
                    yield f"data: {json.dumps(chunk)}\n\n"

                elif chunk["type"] == "done":
                    pois, geofence_radius_m, map_center = _extract_map_data(chunk["intermediate_steps"])
                    tools_used = list(dict.fromkeys(
                        step[0].tool for step in chunk["intermediate_steps"]
                        if hasattr(step[0], "tool")
                    ))
                    # Save offer copy for future banner requests
                    offer_copy = _extract_offer_copy(chunk["output"])
                    if offer_copy:
                        _session_offer_copy[session_id] = offer_copy
                    image_url = _build_image_url(chunk["output"]) if wants_image else None
                    if image_url:
                        image_url = f"http://localhost:8001/image-proxy?url={quote(image_url, safe='')}"

                    done_payload = {
                        "type": "done",
                        "session_id": session_id,
                        "tools_used": tools_used,
                        "pois": pois,
                        "geofence_radius_m": geofence_radius_m,
                        "map_center": map_center,
                        "image_url": image_url,
                    }
                    yield f"data: {json.dumps(done_payload)}\n\n"

        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'content': 'Agent timed out. Please retry.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/image-proxy")
async def image_proxy(url: str):
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Image fetch failed")
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))


@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    delete_session(session_id)
    return {"status": "cleared", "session_id": session_id}
