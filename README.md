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
