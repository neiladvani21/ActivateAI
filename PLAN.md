# Moment Trigger Assistant — Product Roadmap

## Vision

Build an AI-powered **Full-Stack Marketing Execution Assistant** — not a research tool, not a chatbot, but a complete end-to-end system that does what an entire marketing team does in one place.

A real marketing team has a strategist, a copywriter, a designer, a media planner, and an analyst. This tool replicates all of them:

- **Strategist** — reads the market: location context, weather, time of day, competitor presence, audience demographics
- **Copywriter** — writes 3 offer copy variants tailored to the moment, audience, and channel
- **Designer** — generates campaign banners and creatives ready to deploy
- **Media Planner** — recommends which channel (push, SMS, in-app), what geofence size, what activation window
- **Analyst** — tracks past campaign performance, suggests what works better next time

The output is not a chat response or a report. It is a **complete, ready-to-launch campaign package** — copy, creative, channel plan, geofence config — that a marketing team can deploy immediately.

The end state: a marketing team opens this tool, types their location and brand, and gets back everything they need to run an activation. No back-and-forth, no manual work, no external tools needed.

---

## Current State (What We Have Built)

- Single LangChain agent using Groq (llama-3.3-70b-versatile)
- Tools: `get_weather`, `geocode_location`, `search_pois`, `suggest_geofence`
- SQLite conversation memory per session
- React-Leaflet map showing POIs + geofence circle with Google Maps directions links
- Pollinations.ai image generation (free, triggered only on explicit user request)
- Image proxy endpoint to avoid browser CORS issues
- Time-based activation copy (browser sends local time)
- MCP server (FastAPI) wrapping Overpass API for POI data with 3 mirror fallbacks
- TTL-based in-memory caching: geocode (24h), weather (10min), POIs (30min)
- Streaming responses via FastAPI SSE + React streaming reader (word-by-word output)
- In-memory offer copy store per session for instant banner follow-up (no agent re-run)
- Frontend: React + Tailwind dark theme, ActivateAI branding, prompt cards, streaming cursor

### Known Limitations
- Single agent does everything — banner follow-ups require re-running all tools
- Groq free tier: 100k tokens/day limit causes outages during heavy testing
- Pollinations image quality is poor (AI models bad at readable text)
- Agent output is raw markdown in a chat bubble — not structured campaign data
- No competitor POI analysis
- No copy variants — only one offer copy per response
- Overpass API rate limits with no caching

---

## Phase 1 — Stabilize & Clean (Current Priority)

**Goal:** Make what we have production-stable before adding anything new.

### 1.1 Fix Follow-up Banner Generation ✅ Done
- **Problem:** When user says "now generate a banner", the agent re-runs all tools from scratch instead of reusing the previous offer copy
- **Fix:** Save the last extracted offer copy per session in an in-memory dict. On banner-only follow-up requests, skip the agent entirely and return the image directly
- **Implementation:**
  - `_session_offer_copy: Dict[str, str]` module-level store in `agent/main.py`
  - `_is_banner_only_request()` — detects "generate banner / create image / show banner" etc.
  - `_extract_offer_copy()` — regex-extracts the offer copy string from agent response text
  - `_build_image_url_from_copy()` — builds the Pollinations URL from any offer copy string
  - Both `/chat` and `/chat/stream` short-circuit: if message is banner-only AND session has saved copy → skip agent, return image immediately
  - After every normal agent response, offer copy is extracted and saved to `_session_offer_copy[session_id]`
- **Note:** In-memory only — resets on server restart. Will integrate with persistent storage (Nano Banana / Phase 4) later

### 1.2 Switch to a More Reliable Free Model
- **Problem:** Groq llama-3.3-70b has a 100k TPD limit — hits cap during normal testing
- **Fix:** Use `llama-3.1-8b-instant` for tool calls (500k TPD), keep 70B only for final response synthesis
- **Alternative:** Add Gemini Flash as a fallback when Groq is rate-limited

### 1.3 Overpass Result Caching ✅ Done
- **Problem:** Same city query hits Overpass every time, causing rate limits and slow responses
- **Fix:** In-memory cache with a 10-minute TTL keyed on `(lat, lon, radius, category/brand)`
- **Files:** `mcp-server/services/pois_service.py`
- **Status:** Implemented in `mcp-server/services/cache.py` with 30-min TTL for POIs. Cache hit ~0.012s vs ~1s uncached.

### 1.4 Weather + Geocoding Caching ✅ Done
- **Problem:** Same location geocoded on every message in a session
- **Fix:** Cache geocoding results per session, weather results for 10 minutes
- **Files:** `mcp-server/services/`
- **Status:** Geocode cached 24h, weather cached 10min — both wired to `cache.py`.

### 1.5 Streaming Responses ✅ Done
- **Problem:** User stares at spinner for 10-20 seconds
- **Fix:** FastAPI `StreamingResponse` + React streaming reader so text appears word by word
- **Files:** `agent/main.py`, `frontend/src/App.jsx`
- **Status:** End-to-end streaming via `astream_events(version="v2")` in `agent/agent.py`. Frontend uses `fetch` + `ReadableStream`. Animated "ActivateAI is working" pill badge shown while streaming.

**Effort:** 3-5 days  
**Outcome:** Stable, fast, no random outages

---

## Phase 2 — Multi-Agent Architecture

**Goal:** Replace the single agent with a coordinated multi-agent system so each agent has a focused job and follow-up requests work correctly.

### Architecture

```
User Request
     ↓
Orchestrator Agent  (high-reasoning model — decides the plan)
     ↓
┌──────────────────────────────────────────────────────┐
│  Research Agent        │  Strategy Agent             │
│  - search_pois         │  - audience fit by time     │
│  - get_weather         │  - channel recommendation   │
│  - geocode_location    │  - geofence sizing          │
│  - competitor_pois     │  - activation window        │
├──────────────────────────────────────────────────────┤
│  Creative Agent        │  (future) Analytics Agent   │
│  - write 3 copy vars   │  - past campaign lookup     │
│  - pick best variant   │  - ROI estimate             │
│  - generate banner     │  - reach estimate           │
└──────────────────────────────────────────────────────┘
     ↓
Structured Campaign Output
```

### Model Assignment
- **Orchestrator:** Gemini 1.5 Pro or Claude Haiku (good reasoning, low cost)
- **Research Agent:** Groq llama-3.1-8b-instant (fast, high TPD limit, just calling tools)
- **Strategy Agent:** Groq llama-3.3-70b or Gemini Flash (needs reasoning)
- **Creative Agent:** Claude Haiku or Gemini Flash (good at copywriting)

### Why This Fixes the Banner Problem
The Orchestrator sees "generate a banner" → checks if Research Agent already ran this session → if yes, routes directly to Creative Agent with saved context. No re-running tools.

### Framework Decision — To Be Made at Phase 2 Start

Do not lock in a framework now. Evaluate these three options when Phase 2 begins based on what the project needs at that point:

| Framework | Strength | Weakness | MCP Support |
|---|---|---|---|
| **LangGraph** | Fine-grained control, incremental from current LangChain code | Verbose, steep learning curve | Plugin (not native) |
| **CrewAI** | Simplest multi-agent API, role-based agents, easy to read | Less control, no native MCP yet | No |
| **Google ADK** | Native MCP support, clean parallel/sequential flows, best for Anthropic sandbox technique | Full rewrite, pushes toward Google/Gemini ecosystem | Native |

Decision criteria: if MCP code execution (Phase 4 cost reduction) is high priority → lean Google ADK. If staying in current Python/LangChain ecosystem matters → LangGraph. If speed of implementation matters most → CrewAI.

### Agent Persona Files

Each agent has two parts:
- A **`.md` persona file** — the agent's "brain". Written in plain English: role, goal, reasoning steps, rules, output format. Non-developers can read and edit this without touching code. All the intelligence lives here.
- A **thin `.py` file** — just loads the `.md` and wires it to tools and a model. No business logic here.

This is the pattern used in production Google ADK projects — personas in markdown, code just binds them. Adding a new agent = write one new `.md` file + one thin `.py` file.

```
agent/
  personas/
    orchestrator.md     ← intent detection rules, routing logic, what to delegate
    researcher.md       ← how to find POIs, what to prioritize, competitor logic
    strategist.md       ← geofence sizing rules, channel selection, timing windows
    copywriter.md       ← copy rules, 3 variant angles, character limits, tone
    creative.md         ← banner generation instructions, prompt structure
    analyst.md          ← (Phase 5) campaign history, performance pattern reading
  agents.py             ← all agents defined here, each loads its own .md persona
  graph.py              ← wires agents into the execution flow
  main.py               ← just calls graph.py, no agent logic lives here
```

No separate `.py` file per agent is needed. All agents are defined in a single `agents.py` file. Each agent loads its persona from the corresponding `.md` file. The intelligence lives in the markdown — the Python just binds it to tools and a model:

```python
def load_persona(name: str) -> str:
    return Path(f"personas/{name}.md").read_text()

researcher = LlmAgent(
    model=worker_model,
    name="researcher",
    instruction=load_persona("researcher"),
    tools=[search_pois, get_weather, geocode_location],
)

copywriter = LlmAgent(
    model=reasoning_model,
    name="copywriter",
    instruction=load_persona("copywriter"),
    tools=[],
)

strategist = LlmAgent(
    model=worker_model,
    name="strategist",
    instruction=load_persona("strategist"),
    tools=[suggest_geofence],
)
```

Each `.md` persona file will contain:
- **Role** — what this agent is (e.g. "Senior Marketing Copywriter")
- **Goal** — what it is trying to achieve
- **Reasoning steps** — how it should think through the problem (like a playbook)
- **Tools** — which tools it can use and when
- **Output format** — exact structure of what it should return
- **Rules** — constraints and guardrails (e.g. "copy must be under 160 characters")

**Files to create:**
- `agent/personas/orchestrator.md`
- `agent/personas/researcher.md`
- `agent/personas/strategist.md`
- `agent/personas/copywriter.md`
- `agent/personas/creative.md`
- `agent/agents.py` — all agents in one file, each loading its persona
- `agent/graph.py` — wires all agents into the execution flow

**Effort:** 1-2 weeks  
**Outcome:** Clean separation of intelligence (markdown) from code (Python). Easy to read, easy to modify, easy to extend. Adding a new agent = write one new `.md` persona + add a few lines to `agents.py`.

---

## Phase 3 — Richer Tools & Structured Output

**Goal:** Move from chat bubble output to structured campaign cards. Add tools that make the output genuinely useful for a marketing team.

### 3.1 Structured Campaign Output
Instead of markdown in a chat bubble, the API returns a structured object:
```json
{
  "location": "Jersey City, NJ",
  "weather": { "temp": 20, "condition": "clear" },
  "pois": [...],
  "geofence_radius_m": 1000,
  "offer_variants": [
    { "copy": "Morning commute offer...", "channel": "push", "timing": "7-9am" },
    { "copy": "Afternoon slump offer...", "channel": "in-app", "timing": "2-4pm" },
    { "copy": "Weekend special...", "channel": "SMS", "timing": "Sat 10am" }
  ],
  "recommended_channel": "push_notification",
  "estimated_reach": "~2,400 users in geofence",
  "banner_url": "..."
}
```

### 3.2 New Tools
- **`search_competitor_pois`** — find competitor locations near the target brand (e.g. Dunkin near Starbucks)
- **`estimate_foot_traffic`** — use time + location to estimate how busy an area is
- **`suggest_channels`** — recommend push/SMS/in-app based on time and audience
- **`generate_copy_variants`** — produce 3 offer copy variants with different angles (urgency, discount, FOMO)
- **`get_demographic_context`** — basic neighborhood demographics from census data (free API)

### 3.3 Frontend — Campaign Cards UI
Replace raw markdown with structured visual cards:
```
┌─────────────────────────────────────────┐
│ 📍 Jersey City, NJ  ☁️ 20°C Clear      │
├─────────────────────────────────────────┤
│ 15 coffee shops found · 1000m geofence  │
├─────────────────────────────────────────┤
│ OFFER VARIANTS                          │
│ ① Morning Rush  "Start your day at..." │
│ ② Afternoon     "Beat the 3pm slump..."│
│ ③ Weekend       "Treat yourself this.."│
├─────────────────────────────────────────┤
│ Channel: Push Notification              │
│ Best window: 7–9am weekdays             │
│ Est. reach: ~2,400 users                │
├─────────────────────────────────────────┤
│ [Map]          [Banner]  [Export PDF]   │
└─────────────────────────────────────────┘
```

### 3.4 Chat History Sidebar
- Show past sessions in a left sidebar
- Click any session to restore the conversation
- Store session metadata (location, brand, timestamp) in SQLite

### 3.5 Evaluate Code Mode Pattern (If Tool Context Gets Large)
- By Phase 3 we'll have 8-10 tool calls per request (competitor POIs, foot traffic, demographics, census)
- If intermediate tool results start bloating the LLM context, consider switching to the **code mode pattern** — LLM writes one JavaScript/Python program, a sandbox runs all tool calls internally, only the final JSON is returned to the LLM
- This eliminates intermediate result bloat entirely and removes the risk of coordinate/value hallucination across tool calls
- Only worth doing if context size becomes a real problem — re-evaluate at the start of Phase 3 once the new tools are scoped
- Reference: same pattern used in the CVE analysis project where MCP results stayed inside a Node.js vm.createContext sandbox and never re-entered LLM context

**Effort:** 2-3 weeks  
**Outcome:** Looks and feels like a real product, not a chatbot

---

## Phase 4 — Image Generation Upgrade & Cost Optimization

**Goal:** Replace Pollinations with a proper image generation service and add cost reduction across the board.

### 4.1 Google Nano Banana (Gemini Flash Image)
- **What it is:** Community name for Gemini 2.5 Flash Image Preview — Google's fast, cheap image generation model
- **Cost:** ~$0.013–0.039 per image
- **Quality:** Much better than Pollinations, designed for marketing use cases
- **Text rendering:** Significantly better — can render readable offer copy on the banner
- **Integration:** Google AI Python SDK, same credentials as Gemini text models
- **Fallback:** Keep Pollinations as free fallback when image generation is off

```python
# How integration would look
from google import genai
client = genai.Client(api_key=GOOGLE_API_KEY)
response = client.models.generate_image(
    model='imagen-3.0-generate-002',
    prompt=f"Marketing banner: {offer_copy}. Clean design, bold readable text.",
)
```

### 4.2 Anthropic MCP Code Execution (Cost Reduction)
- **What it is:** Run a sandboxed Python script to pre-process tool results before the LLM sees them
- **Result:** Anthropic demonstrated 150k tokens → 2k tokens (98.7% reduction)
- **Applied to us:** Overpass returns 138 POIs → sandbox script filters, ranks, deduplicates → LLM only sees top 5
- **Files:** Add a preprocessing step in the MCP server before returning POI results

### 4.3 Model Routing (Cascade Pattern)
- Simple intent queries (weather check, POI lookup) → Groq 8B (fast, cheap)
- Complex strategy queries (campaign planning, copy generation) → 70B or Claude
- Use a lightweight classifier to route before hitting the main model
- Research shows 85% cost reduction with 95% quality retention

### 4.4 Prompt Caching
- Anthropic Claude natively supports prompt caching — system prompt cached across calls
- 90% cost reduction on cached tokens
- Applicable once we move to Claude as a model option

### 4.5 Result Caching (Redis or In-Memory)
- Geocoding: same city name → same coordinates (cache indefinitely)
- Weather: same location → cache for 10 minutes
- POIs: same location + category → cache for 30 minutes
- Could add Redis for persistent caching across server restarts

**Effort:** 1-2 weeks  
**Outcome:** 60-80% cost reduction at scale, much better image quality

---

## Phase 5 — Analytics, Campaign History & A/B Testing

**Goal:** Make it useful beyond a single session — track what worked, suggest improvements.

### 5.1 Campaign History & Save
- Save every generated campaign to the database
- Browse past campaigns by location, brand, date
- "Export as PDF" button — download the full campaign brief
- "Copy offer copy" button — one click to clipboard

### 5.2 Mock Analytics Dashboard
- Show simulated campaign performance metrics per activation
- Click-through rate estimate based on time, weather, POI density
- Comparison: "This offer performed 23% better than your last Jersey City campaign"
- Heatmap of best-performing geofence sizes by category

### 5.3 A/B Copy Testing
- Generate 3 offer copy variants automatically
- User can rate them or pick a winner
- System learns which copy angles work better for which categories/times

### 5.4 Brand Profile Memory
- User sets up a brand profile: name, category, tone of voice, typical offer type
- Agent remembers it across sessions — no need to re-specify every time
- "Generate an activation for our usual Starbucks campaign" just works

**Effort:** 2-3 weeks  
**Outcome:** Feels like a full SaaS product, not a demo

---

## Tech Stack Summary

| Layer | Current | Target |
|---|---|---|
| Orchestration | Single LangChain agent | LangGraph multi-agent |
| LLM | Groq llama-3.3-70b | Orchestrator: Gemini Pro / Claude Haiku; Workers: Groq 8B |
| POI Data | Overpass API (3 mirrors) | Overpass + caching layer |
| Image Generation | Pollinations (free, low quality) | Google Nano Banana (Gemini Flash Image) |
| Memory | SQLite per session | SQLite + campaign history |
| Caching | None | In-memory (phase 1), Redis (phase 4) |
| Frontend | React chat UI | React campaign cards + sidebar |
| Output format | Markdown in chat bubble | Structured JSON → visual campaign cards |
| Streaming | None | FastAPI StreamingResponse |

---

## Priority Order

1. **Phase 1** — Stabilize (fix banner follow-up, caching, streaming) — do this before any new features
2. **Phase 2** — Multi-agent refactor — the architectural foundation everything else builds on
3. **Phase 3** — Structured output + new tools — makes it genuinely useful for marketing teams
4. **Phase 4** — Image upgrade + cost optimization — production-ready cost profile
5. **Phase 5** — Analytics + history — full SaaS feature set
6. **Phase 6** — Multi-agent performance & optimization — profile and fix latency after Phase 2 is stable
7. **Phase 7** — Infrastructure & deployment — do this last, once everything is built

---

## Phase 6 — Multi-Agent Performance & Optimization

**Goal:** After Phase 2 is running, measure real latency and cut it where it actually hurts. Don't optimize blindly — profile first, then fix the bottlenecks.

**Decision: Do this after Phase 2 is stable and tested in practice.**

### 6.1 Latency Profiling First
- Add timing logs per agent and per tool call
- Identify where time is actually spent before touching anything
- Likely culprits: orchestrator model decision time, sequential agent calls that could be parallel, redundant tool calls across agents

### 6.2 Tool Result Caching (Highest ROI)
- **Geocoding** — same city name always returns same coordinates, cache indefinitely per session
- **Weather** — cache per location for 10 minutes (weather doesn't change faster than that)
- **POIs** — cache per (lat, lon, radius, category) for 30 minutes
- Simple in-memory dict with TTL — no Redis needed at this stage
- Expected impact: eliminates redundant Overpass and weather API calls on follow-up messages

### 6.3 Clean Inter-Agent Handoffs (Same Concept as Sandbox Pre-processing)
- When Research Agent finishes, it passes a clean summary to the next agent — not the raw tool output
- e.g. "5 gyms found, closest is SoulCycle at 51m, weather 22°C clear" — not 138 raw POI records
- This is the same idea as Anthropic's sandbox technique (running a processing step between tool result and LLM to trim what the LLM sees) — just applied at the inter-agent boundary instead of a separate execution environment
- Already partially done: `pois[:20]` in tools.py and distance sorting in pois_service.py

### 6.4 Parallel Agent Execution
- In the multi-agent graph, Research Agent and Strategy Agent can potentially run in parallel
- LangGraph supports parallel branches — evaluate if research and strategy can overlap
- Only worth doing if profiling (6.1) shows sequential agents are the bottleneck

### 6.5 What's Probably Not Worth It
- **Prompt caching** — only valuable at high request volume (thousands/day). Not needed until Phase 6 infra scale
- **Conversation history compression** — most sessions are 2-3 turns, not long enough to matter
- **Model distillation / fine-tuning** — overkill for this use case

**Effort:** 1 week (after profiling)
**Outcome:** Multi-agent response time back to single-agent levels, lower Groq token spend

---

## Phase 7 — Infrastructure & Production Deployment

**Goal:** Move from a local dev setup to a production-ready deployment once all features are built.

**Decision: Do this last — after Phase 5 is complete.**

### 6.1 Database — SQLite → PostgreSQL
- SQLite breaks under multiple server instances (each has its own file, sessions don't share)
- Switch to **PostgreSQL** — same SQL queries, minimal code change (~10 lines)
- Managed options: **Supabase** (free tier, good DX) or **Neon** (serverless Postgres)
- Use Redis for session/chat history if performance becomes a concern

### 6.2 Deployment Architecture
| Layer | Service | Why |
|---|---|---|
| Frontend (React) | **Vercel** | Best-in-class for React — global CDN, instant deploys, preview URLs on every PR |
| Agent backend (FastAPI) | **Railway** or **Render** | Supports long-running processes — Vercel serverless would time out on 15-30s agent calls |
| MCP server (FastAPI) | Same as agent backend | Co-deploy on Railway/Render |
| Database | **Supabase** or **Neon** | Managed Postgres, free tier, replaces SQLite |

### 6.3 Why Not Vercel for the Backend
Vercel runs serverless functions with a 10-second timeout on the free tier. Our agent takes 15-30 seconds. Every request would time out. Vercel is frontend-only for this project.

### 6.4 Scaling Considerations
- Multiple backend instances need shared DB (Postgres) and shared session store (Redis)
- Add a queue (e.g. Celery + Redis) if agent jobs become heavy enough to block the API
- Rate limiting per user session to protect Groq/Overpass quotas

**Effort:** 1 week  
**Outcome:** Publicly accessible, scalable, production-ready deployment

---

## Notes

- Do not add Phase 2+ features on top of the current single-agent architecture. The multi-agent refactor in Phase 2 is a prerequisite for everything that follows cleanly.
- When switching to paid image generation (Phase 4), keep Pollinations as a free fallback so the app still works without a Google API key.
- LangGraph is the right choice over raw LangChain multi-agent because it gives explicit control over the agent graph — which agent runs when, what state is shared, how errors are handled.
- The MCP server architecture we already have is good — in Phase 2 it becomes the tool server that all agents call, not just the single agent.