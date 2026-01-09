# Stage+ Classical Concierge MVP

A Streamlit app that recommends 3 Stage+ albums from a local CSV catalog. The catalog is the only source of truth, and the optional LLM is used only for narration.

## Local Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud Deploy

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io and deploy the repo.
3. In app settings, add secrets (do not commit secrets):
   - `ANTHROPIC_API_KEY`
   - `CATALOG_CSV_PATH` (local file path or URL)
4. Set access to private if needed, then invite viewers from the app settings.

## API Usage

Run the FastAPI server:

```bash
uvicorn api_server:app --host 0.0.0.0 --port $PORT
```

Example request:

```bash
curl -X POST http://127.0.0.1:8000/chat \\
  -H "Content-Type: application/json" \\
  -d '{"message":"bach, something dark","history":[]}'
```

## Frontend integration (Lovable)

Send a POST to `/chat` with a message and optional history. The reply is markdown.

```bash
curl -X POST http://127.0.0.1:8000/chat \\
  -H "Content-Type: application/json" \\
  -d '{"message":"Bach, but something dark","history":[{"role":"user","content":"Bach"}]}'
```

## Replace the Catalog

Set `CATALOG_CSV_PATH` to a local CSV path or a direct-download URL. The app reads it at startup and caches it.

Example URL:

```

## Logging (Render-friendly)

Set `CONCIERGE_LOG_DIR` to control where chat logs are written (default: `/tmp/concierge_plus_logs`).

Admin export endpoints (optional):
- `GET /admin/logs/chat_events.jsonl`
- `GET /admin/logs/chat_turns.csv`

To enable, set `ADMIN_TOKEN` and pass header `X-Admin-Token: <token>`. If `ADMIN_TOKEN` is not set, the endpoints return 404. Logs are ephemeral on Render free tier and reset on redeploy.

## Render Disk (persistent cache/logs)

Render Disk is mounted at an absolute path (example: `/var/data`). Suggested env vars:
- `ANTHROPIC_API_KEY`
- `CATALOG_CSV_PATH` (URL or local path)
- `CATALOG_CACHE_DIR=/var/data`
- `CONCIERGE_LOG_DIR=/var/data/concierge_plus_logs`
- `CLAUDE_MODEL` (fallback)
- `CLAUDE_ROUTER_MODEL` (recommended: Haiku)
- `CLAUDE_WRITER_MODEL` (recommended: Sonnet)
- `CLAUDE_MAX_TOKENS`, `CLAUDE_TEMPERATURE`
- `PRELOAD_CATALOG=1` (default)

## Sanity checks (manual)

- `/health` returns `version: router-v2` after deploy.
- `/chat` with "hello" mid-chat stays short (no onboarding bullets).
- `/chat` with "give me bach" then "something funny" keeps the Bach anchor.
https://drive.google.com/uc?export=download&id=1wR_FcZMJeDVtKM_hGVNNDuUIOgoGvg-D
```

## Security Notes

- This repo is public: do not commit catalog files or secrets.
- Never commit API keys.
- Use `.streamlit/secrets.toml` locally or secrets in Streamlit Cloud.

## Project Structure

```
.
|-- app.py
|-- backend/
|   |-- __init__.py
|   |-- catalog.py
|   |-- ranking.py
|   |-- llm.py
|   `-- prompts.py
|-- data/
|   `-- catalog.csv
|-- .streamlit/
|   |-- config.toml
|   `-- secrets.toml.example
|-- .gitignore
|-- requirements.txt
`-- README.md
```
