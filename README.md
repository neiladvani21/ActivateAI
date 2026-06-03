# ActivateAI — AI-Powered Marketing Activation Platform

ActivateAI is an AI-powered platform that combines real-time weather, location intelligence, and LLM reasoning to generate complete moment-based retail marketing activations — offer copy, geofence strategy, campaign banners, and a live POI map — from a single natural language prompt.

A real marketing team has a strategist, copywriter, designer, and media planner. This tool replicates all of them in one place.

## Architecture Overview

```text
┌──────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│   Dark theme chat UI · Streaming responses · Leaflet map     │
│   Tool badges · Campaign banner · Prompt cards               │
└──────────────────────────────┬───────────────────────────────┘
                               │ POST /chat/stream (SSE)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                   Agent API (FastAPI :8001)                  │
│   LangChain AgentExecutor · Groq llama-3.3-70b-versatile    │
│   Streaming via astream_events · In-memory session store     │
│   Banner shortcut · Image proxy · SQLite conversation memory │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP tool calls
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                   MCP Server (FastAPI :8000)                 │
│   TTL-based in-memory cache · 3 Overpass mirror fallbacks    │
└──────┬───────────────────────┬───────────────────────────────┘
       │                       │                       │
       ▼                       ▼                       ▼
 Open-Meteo API          Nominatim API           Overpass API
 (weather)               (geocoding)             (OSM POIs)
```

## Features

- **Natural language activation planning** — describe a brand and location, get a full campaign
- **Live POI search** — finds real nearby venues via OpenStreetMap (cafes, gyms, restaurants, etc.)
- **Weather-aware copy** — offer copy tailored to current weather and time of day
- **Geofence recommendation** — suggested radius with reasoning based on POI density
- **Interactive map** — Leaflet map with POI markers, geofence circle, and Google Maps directions links
- **Streaming responses** — word-by-word output via Server-Sent Events, no waiting for full response
- **Campaign banner generation** — Pollinations.ai banner triggered on demand, no re-running tools
- **TTL caching** — geocode (24h), weather (10min), POIs (30min) — fast follow-up queries

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Tailwind CSS, React-Leaflet, react-markdown |
| Agent API | FastAPI, LangChain, Groq (`llama-3.3-70b-versatile`) |
| MCP Server | FastAPI, httpx, Pydantic |
| Memory | SQLite (conversation history per session) |
| Image Generation | Pollinations.ai (free, no API key needed) |
| POI Data | Overpass API / OpenStreetMap |
| Weather | Open-Meteo (free, no API key needed) |
| Geocoding | Nominatim (free, no API key needed) |

## Prerequisites

- Python `3.10+`
- Node.js `18+`
- Groq API key — free at [console.groq.com](https://console.groq.com)

## Local Setup

Run services in this order: MCP server → Agent → Frontend.

### 1. MCP Server (port 8000)

```bash
cd mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Agent (port 8001)

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `agent/.env`:

```dotenv
GROQ_API_KEY=your_groq_api_key
MCP_SERVER_URL=http://localhost:8000
```

```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### 3. Frontend (port 3000)

```bash
cd frontend
npm install
npm start
```

Open `http://localhost:3000`

## Example Queries

Try these in the chat UI:

- `Find coffee shops near Austin TX and suggest a morning activation`
- `Find gyms near Jersey City NJ and suggest a workout campaign`
- `Find restaurants near Seattle and recommend a lunch hour geofence strategy`
- `Check weather near Chicago and suggest a cold weather retail activation`

After the agent responds with offer copy, follow up with:

- `Generate a banner` — returns a campaign banner image instantly using the saved offer copy, no re-running tools

## API Reference

### POST /chat/stream
Streaming chat endpoint (SSE). Used by the frontend.

```bash
curl -X POST http://localhost:8001/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Find coffee shops near Austin TX", "session_id": "abc123"}'
```

Yields SSE events:
- `{"type": "token", "content": "..."}` — streaming text tokens
- `{"type": "done", "session_id": "...", "tools_used": [...], "pois": [...], "geofence_radius_m": 500, "map_center": {...}, "image_url": null}` — final metadata

### POST /chat
Non-streaming fallback endpoint.

### DELETE /session/{session_id}
Clears conversation history for a session.

### GET /image-proxy?url=...
Proxies Pollinations image requests to avoid browser CORS issues.

## Repository Structure

```text
.
├── agent/
│   ├── agent.py          # LangChain AgentExecutor + streaming
│   ├── config.py         # Model, API keys, timeouts
│   ├── database.py       # SQLite conversation memory
│   ├── main.py           # FastAPI routes, banner shortcut, image proxy
│   ├── tools.py          # Tool definitions (weather, geocode, POIs, geofence)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx        # Main chat UI, streaming reader, map integration
│       ├── GeofenceMap.jsx # Leaflet map, POI markers, geofence circle
│       └── index.css
├── mcp-server/
│   ├── routes/            # FastAPI route handlers
│   ├── services/
│   │   ├── cache.py       # TTL in-memory cache
│   │   ├── geocode_service.py
│   │   ├── weather_service.py
│   │   └── pois_service.py
│   └── main.py
├── PLAN.md                # Full product roadmap and phase tracking
└── README.md
```

## Notes

- Overpass API (OpenStreetMap) is used for POI data. It is free but rate-limited. For production, prefer Foursquare Places API or Google Places API.
- Pollinations.ai image generation is free but slow (20-30s). Banner quality is limited — Phase 4 of the roadmap replaces it with Gemini Flash Image.
- SQLite is used for conversation memory. Sufficient for single-instance local use; Phase 7 migrates to PostgreSQL for multi-instance deployments.
