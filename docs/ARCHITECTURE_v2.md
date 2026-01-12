# Concierge Plus: Retrieval-Augmented Intelligence for Music Discovery

**Technical Architecture Overview**  
*Stage+ Recommendation Engine MVP*

---

## The Big Picture: Claude as the Brain

Concierge Plus is best understood as **giving Claude a superpower**: complete mastery of the Stage+ music library, including knowledge of what real listeners actually enjoy.

Claude is incredibly intelligent, but it doesn't know which specific albums are in the Stage+ catalog, which recordings are popular, or which hidden gems have passionate followings. The system solves this by giving Claude an **extended memory** — the catalog — that it can query through the backend.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   "What should I listen to? I want Bach, but something dark."           │
│                                                                         │
│                              THE BRAIN                                  │
│                     ┌─────────────────────┐                             │
│                     │       CLAUDE        │                             │
│                     │                     │                             │
│                     │  • Understands      │                             │
│                     │    natural language │                             │
│                     │  • Makes decisions  │                             │
│                     │  • Writes responses │                             │
│                     │  • Has personality  │                             │
│                     └──────────┬──────────┘                             │
│                                │                                        │
│              ┌─────────────────┼─────────────────┐                      │
│              │                 │                 │                      │
│              ▼                 ▼                 ▼                      │
│   ┌──────────────────────────────────────────────────────────┐          │
│   │                    THE EXTENDED MEMORY                   │          │
│   │                  (Backend + Catalog CSV)                 │          │
│   │                                                          │          │
│   │  • albums with metadata (Mixpanel bounce)                │          │
│   │  • Real listener behavior (who played what, for how long)│          │
│   │  • Popularity scores derived from actual engagement (MP) │          │
│   │  • Search & retrieval capabilities                       │          │
│   └──────────────────────────────────────────────────────────┘          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## How They Work Together

### The Partnership

| Component | Role | Analogy |
|-----------|------|---------|
| **Claude (Haiku)** | Decision Maker | The brain deciding what to look for |
| **Backend + CSV** | Memory & Retrieval | A perfectly organized library with a librarian |
| **Claude (Sonnet)** | Narrator & Curator | The brain selecting and explaining the best picks |

### The Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  USER: "Bach, but something dark, no organ"                             │
│                                                                         │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  STEP 1: CLAUDE HAIKU (The Brain) understands the request       │    │
│  │                                                                 │    │
│  │  "The user wants Bach, dark mood, exclude organ. I should       │    │
│  │   search for Bach, rank by engagement (sticky listeners),       │    │
│  │   and filter out organ music."                                  │    │
│  │                                                                 │    │
│  │  Decision output:                                               │    │
│  │  {                                                              │    │
│  │    intent: "reco",                                              │    │
│  │    strategy: "vibe",                                            │    │
│  │    query: "Bach dark",                                          │    │
│  │    rank_by: "score_sticky",                                     │    │
│  │    filters: { exclude_instruments: ["organ"] }                  │    │
│  │  }                                                              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  STEP 2: BACKEND (The Memory) retrieves matching albums         │    │
│  │                                                                 │    │
│  │  Searches album using Claude's instructions:                    │    │
│  │  • Fuzzy match "Bach dark" against titles & metadata            │    │
│  │  • Filter out anything with organ                               │    │
│  │  • Sort by score_sticky (albums people listen to deeply)        │    │
│  │  • Return top 12 candidates                                     │    │
│  │                                                                 │    │
│  │  Result: 12 Bach albums ranked by listener engagement           │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  STEP 3: CLAUDE SONNET (The Brain) curates & narrates           │    │
│  │                                                                 │    │
│  │  Reviews 12 candidates, picks the 3 best fits, writes:          │    │
│  │                                                                 │    │
│  │  "Looking for Bach with a darker edge — here are three that     │    │
│  │   should resonate.                                              │    │
│  │                                                                 │    │
│  │   1) Bach: Mass in B Minor — Collegium Vocale Gent              │    │
│  │      This monumental work carries a profound weight..."         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│         │                                                               │
│         ▼                                                               │
│  USER sees: Warm, personalized recommendations with explanations        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## The Superpower: Behavioral Intelligence

The catalog isn't just a list of albums — it contains **real listener behavior** from Mixpanel analytics. This gives Claude insight into what people actually enjoy, not just what exists.

### Raw Behavioral Data

Every album has engagement metrics from real Stage+ users:

| Metric | What It Measures | Example |
|--------|------------------|---------|
| **unique_users** | How many people played this album | 2,847 listeners |
| **consumption_time** | Total minutes played across all users | 142,350 minutes |
| **avg_time_per_user** | How long each listener engaged | 50 minutes/person |

### Derived Scores (The Intelligence Layer)

These raw metrics are transformed into **smart scores** that power different recommendation strategies:

| Score | Formula | What It Finds | When Claude Uses It |
|-------|---------|---------------|---------------------|
| **score_poplite** | unique_users × log(consumption_time) | Popular, accessible albums | "Gateway" requests, new users |
| **score_sticky** | avg_time_per_user (normalized) | Albums people listen to deeply | Mood/vibe requests ("something dark") |
| **score_hidden_gem** | High avg_time + low unique_users | Beloved by few, ignored by many | "Surprise me", "hidden gems" |

### Why This Matters

```
Traditional recommendation: "Here are Bach albums, sorted alphabetically"

Concierge Plus:
├── User wants "popular Bach" → sort by score_poplite
│   → Returns Karajan's symphonies, Gould's Goldbergs (the classics)
│
├── User wants "Bach for deep focus" → sort by score_sticky  
│   → Returns albums where listeners stayed for 60+ minutes
│
└── User wants "obscure Bach" → sort by score_hidden_gem
    → Returns albums with 50 passionate listeners, not 5,000 casual ones
```

Claude decides which score to use based on understanding the user's intent. The backend executes that decision against real engagement data.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              USER                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Lovable)                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  │
│  │  Chat Interface │  │  Link Preview   │  │  Open Graph Metadata    │  │
│  │  (React/TS)     │  │  Edge Function  │  │  Extraction             │  │
│  └────────┬────────┘  └────────┬────────┘  └─────────────────────────┘  │
└───────────┼─────────────────────┼───────────────────────────────────────┘
            │                     │
            │ POST /chat          │ Fetch og:image, og:title
            ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    BACKEND — The Extended Memory (Render)               │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                      FastAPI Server                             │    │
│  │                                                                 │    │
│  │  Workflow Controller:                                           │    │
│  │  1. Receives user message                                       │    │
│  │  2. Asks Claude Haiku: "What does user want?"                   │    │
│  │  3. Executes search based on Haiku's decision                   │    │
│  │  4. Asks Claude Sonnet: "Write a response with these albums"    │    │
│  │  5. Returns response to frontend                                │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                              │                                          │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Catalog (CSV in Memory)                      │    │
│  │                                                                 │    │
│  │  1,723 albums with:                                             │    │
│  │  • Metadata (composers, artists, genres, epochs, instruments)   │    │
│  │  • Behavioral scores (poplite, sticky, hidden_gem)              │    │
│  │  • Engagement data (unique_users, consumption_time)             │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
            │
            │  Claude makes decisions, Backend executes them
            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    CLAUDE — The Brain (Anthropic API)                   │
│                                                                         │
│  ┌──────────────────────────────┐  ┌──────────────────────────────┐     │
│  │      Claude Haiku 4.5        │  │      Claude Sonnet 4.5       │     │
│  │      (Fast, Analytical)      │  │      (Eloquent, Creative)    │     │
│  │                              │  │                              │     │
│  │  • Understands user intent   │  │  • Picks best 3 from 12      │     │
│  │  • Decides search strategy   │  │  • Writes explanations       │     │
│  │  • Extracts filters          │  │  • Maintains personality     │     │
│  │  • ~200ms response time      │  │  • ~2s response time         │     │
│  └──────────────────────────────┘  └──────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Pipeline

### Catalog Construction

The recommendation catalog was assembled entirely from Mixpanel analytics exports, merged across multiple granularity levels:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         MIXPANEL EXPORTS                                │
│                                                                         │
│  ┌───────────────────────┐       ┌───────────────────────────────────┐  │
│  │   Album-Level Data    │       │       Track-Level Data            │  │
│  │   ─────────────────   │       │       ────────────────            │  │
│  │   • Playback pings    │       │   • Track titles                  │  │
│  │   • Unique users      │       │   • Artists per track             │  │
│  │   • Consumption time  │       │   • Genres                        │  │
│  │   • Album titles      │       │   • Epochs                        │  │
│  │   • Composers         │       │   • Instruments                   │  │
│  └───────────┬───────────┘       └─────────────────┬─────────────────┘  │
│              │                                     │                    │
│              │         Merge & Aggregate           │                    │
│              └──────────────┬──────────────────────┘                    │
│                             ▼                                           │
│              ┌──────────────────────────────┐                           │
│              │  Aggregated Album Records    │                           │
│              │  (track info rolled up)      │                           │
│              └──────────────┬───────────────┘                           │
└─────────────────────────────┼───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         WEB CRAWLER                                     │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  • Scraped Stage+ website for album URLs                        │    │
│  │  • Extracted UPCs (container_id) for join keys                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              │  Join on container_id (UPC)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         ENRICHMENT LAYER                                │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  • Calculate behavioral scores (poplite, sticky, hidden_gem)    │    │
│  │  • Generate mood tags (heuristic rules + LLM-assisted)          │    │
│  │  • Add use-case tags (focus, relaxation, sleep-friendly, etc.)  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    catalog.csv (1,723 albums)                           │
└─────────────────────────────────────────────────────────────────────────┘

```



!!!!!!  I M P O R T A N T !!!!!!

==> We could only get 1,723 albums via the crawling, as the "Popular now" slider - which we used as a basis - only has albums that created at least 1 playbback ping within the last 7 days. Those are probably the most relevant albums, but this can obviously be extended and improved. It might still be useful to have a short list with viewer albums to keep up the speed of the answers and only turn to the complete list, if the user request screams for it (eg a specific search).





### Catalog Schema

| Column | Source | Description |
|--------|--------|-------------|
| `album_url` | Web Crawler | Direct link to Stage+ album page |
| `container_id` | Web Crawler | UPC identifier for joins |
| `album_title` | Mixpanel (album-level) | Album display title |
| `composers` | Mixpanel (album-level) | Primary composer(s) |
| `artists` | Mixpanel (track-level, aggregated) | Performing artist(s) |
| `tracks` | Mixpanel (track-level, aggregated) | Track listing |
| `genres` | Mixpanel (track-level, aggregated) | Musical genres |
| `epochs` | Mixpanel (track-level, aggregated) | Historical period (Baroque, Romantic, etc.) |
| `conductors`, `groups`, `soloists` | Mixpanel (track-level, aggregated) | Personnel metadata |
| `primary_instrument`, `soloist_instruments` | Mixpanel (track-level, aggregated) | Instrumentation |
| `is_atmos` | Mixpanel | Dolby Atmos availability flag |
| `audio_badges` | Mixpanel | Audio quality indicators |

---

## Request Flow (Detailed)

### 1. User Sends Message

```json
POST /chat
{
  "message": "Bach, but something dark",
  "conversation_id": "optional-uuid"
}
```

### 2. Claude Haiku Decides Intent & Strategy

The backend sends the message to Claude Haiku with routing instructions. Haiku returns structured JSON:

```json
{
  "intent": "reco",
  "strategy": "vibe",
  "query": "Bach dark",
  "rank_by": "score_sticky",
  "filters": {}
}
```

| Pattern | Intent | Strategy | Rank By |
|---------|--------|----------|---------|
| "hello", "thanks" | `smalltalk` | — | — |
| "bach", "mozart" | `reco` | `performer_led` | score_poplite |
| "hidden gems" | `reco` | `deep_dive` | score_hidden_gem |
| "calm", "dark", "focus" | `reco` | `vibe` | score_sticky |
| "dolby atmos" | `reco` | `atmos` | score_poplite |

### 3. Backend Searches Catalog

```python
# Fuzzy text matching (RapidFuzz)
title_score = token_set_ratio(query, album_title)
blob_score = token_set_ratio(query, search_blob)  # all text fields concatenated
match_score = 0.7 * title_score + 0.3 * blob_score

# Final ranking combines relevance + behavioral score
final_score = 0.65 * match_score + 0.35 * normalized(rank_metric)
```

### 4. Claude Sonnet Narrates

Top 12 candidates are serialized as JSON and sent to Claude Sonnet:

```
System: You are the Stage+ Concierge — warm, opinionated, non-snobby.
        Only use albums from the provided JSON. Never invent albums.

User: User request: Bach, but something dark
      
      Candidate albums JSON:
      [{"album_title": "Bach: Mass in B Minor", "album_url": "...", ...}, ...]
      
      OUTPUT FORMAT:
      {one short mirroring sentence}
      1) **[Album — Artist](url)**
      {explanation}
      ...
```

### 5. Response with Rich Previews

```markdown
Looking for Bach with a darker edge — I've got you.

1) **[Bach: Mass in B Minor — Collegium Vocale Gent](https://stage-plus.com/...)**
   One of the most profound sacred works ever composed...
```

---

## Technology Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| **Frontend** | Lovable (React/TypeScript) | AI-assisted development platform |
| **Backend** | FastAPI (Python) | Workflow controller + catalog search |
| **Hosting** | Render | Auto-deploy from GitHub, free tier |
| **Brain (Router)** | Claude Haiku 4.5 | Intent classification, ~200ms |
| **Brain (Writer)** | Claude Sonnet 4.5 | Curation & narration, ~2s |
| **Search** | RapidFuzz | Token-based fuzzy string matching |
| **Data** | Pandas | In-memory catalog operations |

---

## Key Design Decisions

### Why This Architecture? (RAG vs Fine-Tuning)

| Approach | Pros | Cons |
|----------|------|------|
| **Fine-tuned model** | No retrieval latency | Stale knowledge, expensive retraining, hallucination risk |
| **RAG (our approach)** | Always current, auditable, no hallucinations | Retrieval quality dependent on catalog |

By giving Claude only pre-vetted candidates, we guarantee every recommendation exists and has a valid URL.

### Why Two Claude Calls?

| Model | Cost | Speed | Strength |
|-------|------|-------|----------|
| **Haiku** | $0.001/request | ~200ms | Fast analysis, structured output |
| **Sonnet** | $0.01/request | ~2s | Beautiful prose, nuanced curation |

Using Sonnet for routing would be 10x more expensive and slower. Using Haiku for writing would produce worse prose.

### Why Behavioral Scores?

Traditional metadata recommendations miss engagement signals:

- An album can be "popular" (many listeners) but not "sticky" (people skip quickly)
- Hidden gems have high engagement from few listeners
- Different scores serve different user intents

The scores transform raw Mixpanel data into actionable intelligence that Claude can leverage.

---

## Performance Characteristics

| Metric | Typical Value | Notes |
|--------|---------------|-------|
| **Cold start** | 8-15s | Render free tier spins down after 15min |
| **Warm response** | 2-3s | Haiku (~200ms) + Search (~50ms) + Sonnet (~2s) |
| **Catalog search** | 30-50ms | In-memory fuzzy matching |

---

## Cost Estimate (MVP Scale)

| Component | Cost Model | Estimate (1K requests/day) |
|-----------|------------|----------------------------|
| **Render** | Free tier | $0 |
| **Claude Sonnet** | $3/1M input, $15/1M output | ~$1.50/day |
| **Claude Haiku** | $0.25/1M input, $1.25/1M output | ~$0.10/day |

**Total: ~$50/month** at 1K requests/day.

---

## Future Enhancements

| Enhancement | Impact | Effort |
|-------------|--------|--------|
| **Semantic search (embeddings)** | Better "vibe" matching when keywords don't overlap | Medium |
| **Mood tags in search** | "calming piano" matches albums tagged `calm` | Low |
| **User preference memory** | "I don't like opera" persists across sessions | Medium |
| **Streaming responses** | Faster perceived latency | Low |

---

*Document version: 2.0*  
*Last updated: January 2026*
