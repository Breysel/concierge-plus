import os
import re
import tempfile
from functools import lru_cache
from typing import Dict, List, Any, Optional

import numpy as np
import pandas as pd
import requests
from rapidfuzz import fuzz, process

from backend.ranking import rank_metrics
from backend.genre_infer import infer_is_jazz, add_genre

DEFAULT_CATALOG_FILENAME = "catalog.csv"

TEXT_COLS = [
    "album_title",
    "composers",
    "artists",
    "tracks",
    "conductors",
    "groups",
    "soloists",
    "genres",
    "epochs",
    "primary_instrument",
    "soloist_instruments",
    "audio_badges",
]

NUM_COLS = [
    "unique_users",
    "consumption_time",
    "avg_time_per_user",
    "score_sticky",
    "score_poplite",
    "score_hidden_gem",
    "score_hidden_gem_strict",
]

MISSING_STRINGS = {"", "nan", "none", "null", "undefined"}


def _clean_text_series(series: pd.Series) -> pd.Series:
    series = series.fillna("").astype(str).str.strip()
    lower = series.str.lower()
    series = series.where(~lower.isin(MISSING_STRINGS), "")
    return series


@lru_cache(maxsize=2)
def load_catalog(local_path: str) -> pd.DataFrame:
    if not os.path.exists(local_path):
        raise FileNotFoundError(
            "Catalog CSV not found. Set CATALOG_CSV_PATH to a valid file path or URL."
        )
    try:
        df = pd.read_csv(local_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to parse catalog CSV at {local_path}.") from exc

    def apply_inferred_genres(frame: pd.DataFrame) -> pd.DataFrame:
        def _row(r: pd.Series) -> str:
            title = r.get("album_title")
            artists = r.get("artists")
            composers = r.get("composers")
            epochs = r.get("epochs")
            if infer_is_jazz(title, artists, composers, epochs):
                existing = r.get("genres")
                if pd.isna(existing):
                    existing = ""
                return add_genre(existing, "Jazz")
            return r.get("genres")

        frame["genres"] = frame.apply(_row, axis=1)
        return frame

    df = apply_inferred_genres(df)

    for col in TEXT_COLS:
        if col not in df.columns:
            df[col] = ""
        df[col] = _clean_text_series(df[col])

    for col in NUM_COLS:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "is_atmos" not in df.columns:
        df["is_atmos"] = ""
    df["is_atmos"] = _clean_text_series(df["is_atmos"])
    df["is_atmos_bool"] = df["is_atmos"].str.lower().isin(["true", "1", "yes", "y"])

    if "album_url" in df.columns:
        df["album_url"] = _clean_text_series(df["album_url"])
        df["album_url"] = df["album_url"].apply(_normalize_album_url)

    df["title_norm"] = df["album_title"].str.lower()

    blob = df[TEXT_COLS].fillna("").agg(" ".join, axis=1)
    df["search_blob"] = blob.str.lower()

    df["genres_norm"] = df["genres"].str.lower()
    df["epochs_norm"] = df["epochs"].str.lower()
    df["primary_instrument_norm"] = df["primary_instrument"].str.lower()
    df["soloist_instruments_norm"] = df["soloist_instruments"].str.lower()

    print(f"Catalog loaded with {len(df)} rows")
    return df


def _resolve_catalog_path() -> str:
    env_path = os.getenv("CATALOG_CSV_PATH")
    if env_path and (_is_url(env_path) or os.path.exists(env_path)):
        return env_path

    raise FileNotFoundError(
        "Catalog CSV not found. Set CATALOG_CSV_PATH to a valid file path."
    )


def ensure_catalog_downloaded(path: str) -> str:
    resolved = path or _resolve_catalog_path()
    if _is_url(resolved):
        destination = get_catalog_local_path(resolved)
        return _download_catalog(resolved, destination)
    return resolved


def is_catalog_loaded() -> bool:
    return load_catalog.cache_info().currsize > 0


__all__ = [
    "search",
    "load_catalog",
    "ensure_catalog_downloaded",
    "get_catalog_local_path",
    "is_catalog_loaded",
]


def _normalize_album_url(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    lower = value.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        value = value.replace("stageplus.com", "stage-plus.com")
        value = value.replace("www.stageplus.com", "www.stage-plus.com")
        return value
    if lower.startswith("stageplus.com") or lower.startswith("www.stageplus.com"):
        return f"https://{value.lstrip('/')}".replace(
            "stageplus.com", "stage-plus.com"
        )
    if lower.startswith("stage-plus.com") or lower.startswith("www.stage-plus.com"):
        return f"https://{value.lstrip('/')}"
    if value.startswith("/"):
        return f"https://www.stage-plus.com{value}"
    return f"https://www.stage-plus.com/{value}"


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _get_catalog_cache_dir() -> str:
    override = os.getenv("CATALOG_CACHE_DIR")
    if override:
        return override
    if os.path.isdir("/var/data"):
        return "/var/data"
    return "/tmp"


def get_catalog_local_path(path: Optional[str] = None) -> str:
    resolved = path or _resolve_catalog_path()
    if _is_url(resolved):
        cache_dir = _get_catalog_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, DEFAULT_CATALOG_FILENAME)
    return resolved


def _download_catalog(url: str, destination: str) -> str:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    force_refresh = os.getenv("CATALOG_FORCE_REFRESH") == "1"
    if (
        not force_refresh
        and os.path.exists(destination)
        and os.path.getsize(destination) > 0
    ):
        return destination
    try:
        with requests.get(url, timeout=30, stream=True) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(
                dir=os.path.dirname(destination), delete=False
            ) as temp_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        temp_file.write(chunk)
                temp_name = temp_file.name
        os.replace(temp_name, destination)
    except Exception as exc:
        raise RuntimeError(
            "Failed to download catalog CSV from URL. Check CATALOG_CSV_PATH."
        ) from exc
    print(f"Catalog downloaded from URL to {destination}")
    return destination


def _list_filter_mask(series: pd.Series, values: List[str]) -> pd.Series:
    if not values:
        return pd.Series(True, index=series.index)
    values = [v.strip().lower() for v in values if v and v.strip()]
    if not values:
        return pd.Series(True, index=series.index)
    pattern = "|".join(re.escape(v) for v in values)
    return series.str.contains(pattern, na=False)


def search(request: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = (request.get("query") or "").strip()
    mode = (request.get("mode") or "auto").strip().lower()
    filters = request.get("filters") or {}
    limit = int(request.get("limit") or 30)
    rank_by = (request.get("rank_by") or "").strip()
    min_match_score = request.get("min_match_score")

    resolved_path = _resolve_catalog_path()
    local_path = get_catalog_local_path(resolved_path)
    if _is_url(resolved_path):
        local_path = ensure_catalog_downloaded(resolved_path)
    df = load_catalog(local_path)

    deep_cuts_strict = bool(filters.get("deep_cuts_strict"))

    if mode == "atmos":
        filters = dict(filters)
        filters["is_atmos"] = True

    mask = pd.Series(True, index=df.index)

    if filters.get("epochs"):
        mask &= _list_filter_mask(df["epochs_norm"], filters.get("epochs"))
    if filters.get("genres"):
        mask &= _list_filter_mask(df["genres_norm"], filters.get("genres"))
    if filters.get("primary_instrument"):
        mask &= _list_filter_mask(df["primary_instrument_norm"], filters.get("primary_instrument"))
    if filters.get("soloist_instruments"):
        mask &= _list_filter_mask(df["soloist_instruments_norm"], filters.get("soloist_instruments"))

    if filters.get("exclude_genres"):
        mask &= ~_list_filter_mask(df["genres_norm"], filters.get("exclude_genres"))

    if filters.get("is_atmos") is True:
        mask &= df["is_atmos_bool"]
    if filters.get("is_atmos") is False:
        mask &= ~df["is_atmos_bool"]

    if filters.get("min_unique_users") is not None:
        try:
            min_users = int(filters.get("min_unique_users"))
            mask &= df["unique_users"] >= min_users
        except (TypeError, ValueError):
            pass

    filtered = df[mask].copy()

    if filtered.empty:
        return []

    query_norm = query.lower()
    if query_norm:
        title_scores = process.cdist(
            [query_norm],
            filtered["title_norm"].tolist(),
            scorer=fuzz.token_set_ratio,
            dtype=np.float32,
            workers=1,
        )[0] / 100.0
        blob_scores = process.cdist(
            [query_norm],
            filtered["search_blob"].tolist(),
            scorer=fuzz.token_set_ratio,
            dtype=np.float32,
            workers=1,
        )[0] / 100.0
        match_score = 0.7 * title_scores + 0.3 * blob_scores
    else:
        match_score = np.zeros(len(filtered), dtype=np.float32)

    filtered = filtered.assign(match_score=match_score)

    if query_norm and min_match_score is not None:
        try:
            min_score = float(min_match_score)
        except (TypeError, ValueError):
            min_score = None
        if min_score is not None:
            filtered = filtered[filtered["match_score"] >= min_score]
            if filtered.empty:
                return []

    if mode == "auto":
        k = min(10, len(filtered))
        indices = []
        if query_norm:
            indices += (
                filtered.sort_values("match_score", ascending=False)
                .head(k)
                .index.tolist()
            )
        indices += (
            filtered.sort_values("score_poplite", ascending=False)
            .head(k)
            .index.tolist()
        )
        indices += (
            filtered.sort_values("score_sticky", ascending=False)
            .head(k)
            .index.tolist()
        )
        hidden_pool = filtered[filtered["unique_users"] >= 30]
        if hidden_pool.empty:
            hidden_pool = filtered
        indices += (
            hidden_pool.sort_values("score_hidden_gem", ascending=False)
            .head(k)
            .index.tolist()
        )

        seen = set()
        unique_indices = []
        for idx in indices:
            if idx not in seen:
                seen.add(idx)
                unique_indices.append(idx)
        if not unique_indices:
            unique_indices = filtered.index.tolist()

        filtered = filtered.loc[unique_indices].copy()
        filtered["auto_rank"] = range(len(filtered))
        rank_values = filtered["score_poplite"].astype(float).to_numpy()
        if rank_values.size == 0:
            rank_norm = np.zeros_like(rank_values)
        else:
            vmin = np.min(rank_values)
            vmax = np.max(rank_values)
            if vmax - vmin < 1e-9:
                rank_norm = np.zeros_like(rank_values)
            else:
                rank_norm = (rank_values - vmin) / (vmax - vmin)

        if query_norm:
            final_score = 0.65 * filtered["match_score"].to_numpy() + 0.35 * rank_norm
        else:
            final_score = rank_norm
        filtered = filtered.assign(final_score=final_score)
        filtered = filtered.sort_values(by=["auto_rank"]).head(limit)
    else:
        if rank_by == "match_score":
            filtered = (
                filtered.sort_values(by=["match_score", "unique_users"], ascending=False)
                .head(limit)
                .copy()
            )
            filtered["final_score"] = filtered["match_score"]
        else:
            if rank_by in NUM_COLS and rank_by in filtered.columns:
                metric = rank_by
                secondary = (
                    "score_poplite" if metric != "score_poplite" else "unique_users"
                )
            else:
                metric, secondary = rank_metrics(mode, deep_cuts_strict)
            rank_values = filtered[metric].astype(float).to_numpy()
            if rank_values.size == 0:
                rank_norm = np.zeros_like(rank_values)
            else:
                vmin = np.min(rank_values)
                vmax = np.max(rank_values)
                if vmax - vmin < 1e-9:
                    rank_norm = np.zeros_like(rank_values)
                else:
                    rank_norm = (rank_values - vmin) / (vmax - vmin)

            if query_norm:
                final_score = 0.65 * match_score + 0.35 * rank_norm
            else:
                final_score = rank_norm

            filtered = filtered.assign(
                final_score=final_score,
            )

            filtered = filtered.sort_values(
                by=["final_score", secondary], ascending=False
            ).head(limit)

    # Return is_atmos as a proper boolean for downstream prompts/UI.
    filtered["is_atmos"] = filtered["is_atmos_bool"]
    if "final_score" not in filtered.columns:
        filtered["final_score"] = filtered.get("match_score", 0.0)

    fields = [
        "container_id",
        "album_title",
        "composers",
        "artists",
        "genres",
        "epochs",
        "primary_instrument",
        "soloist_instruments",
        "conductors",
        "groups",
        "is_atmos",
        "audio_badges",
        "unique_users",
        "avg_time_per_user",
        "score_sticky",
        "score_poplite",
        "score_hidden_gem",
        "score_hidden_gem_strict",
        "match_score",
        "final_score",
    ]

    if "album_url" in filtered.columns:
        fields.insert(1, "album_url")

    records = filtered[fields].to_dict(orient="records")
    if records:
        for record in records:
            assert "match_score" in record
            assert "final_score" in record
    return records
