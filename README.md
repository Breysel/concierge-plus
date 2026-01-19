# Stage+ Classical Concierge API

A FastAPI backend that recommends classical music albums from a Stage+ catalog using Claude for natural language narration.

## Quick Start
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ANTHROPIC_API_KEY="sk-ant-..."
export CATALOG_CSV_PATH="https://drive.google.com/uc?export=download&id=..."

# Run the server
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

## API Endpoints

### POST /chat

Send a message and get album recommendations.
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Bach, something dark"}'
```

**Request body:**
```json
{
  "message": "string (required)",
  "conversation_id": "string (optional, for multi-turn)",
  "history": [{"role": "user", "content": "..."}],
  "debug": false
}
```

**Response:**
```json
{
  "reply": "markdown string with recommendations",
  "mode": "reco | smalltalk",
  "conversation_id": "uuid"
}
```

### GET /health

Check service status.
```json
{
  "ok": true,
  "version": "router-v2",
  "catalog_loaded": true,
  "uptime_seconds": 123
}
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | - | Anthropic API key |
| `CATALOG_CSV_PATH` | Yes | - | URL or local path to catalog CSV |
| `CATALOG_CACHE_DIR` | No | `/tmp` | Where to cache downloaded catalog |
| `CONCIERGE_LOG_DIR` | No | `/tmp/concierge_plus_logs` | Log directory |
| `CLAUDE_TEMPERATURE` | No | `0.3` | LLM temperature |
| `CLAUDE_MAX_TOKENS` | No | `500` | Max response tokens |

## Deployment (Render)

1. Create a new Web Service on Render
2. Set environment variables in Render dashboard
3. Deploy from GitHub

**Recommended Render settings:**
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn api_server:app --host 0.0.0.0 --port $PORT`

## Evaluation Suite

Run the chat suite locally:
```bash
python eval/run_chat_suite.py --base-url http://localhost:8000
```

Run the chat suite against Render:
```bash
python eval/run_chat_suite.py --base-url https://concierge-plus-api.onrender.com --sleep-ms 800
```

## Project Structure
```
.
├── api_server.py          # FastAPI application
├── backend/
│   ├── catalog.py         # Catalog loading and search
│   ├── llm.py             # Anthropic API calls
│   ├── prompts.py         # System prompts and templates
│   ├── ranking.py         # Scoring strategies
│   ├── routing.py         # Intent routing logic
│   └── telemetry.py       # Logging utilities
├── requirements.txt
└── README.md
```

## Admin Endpoints (optional)

Set `ADMIN_TOKEN` to enable log exports:
```bash
curl -H "X-Admin-Token: your-token" \
  https://your-app.onrender.com/admin/logs/chat_turns.csv
```
