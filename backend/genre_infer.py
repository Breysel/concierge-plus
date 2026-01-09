import re

JAZZ_PATTERNS = [
    re.compile(r"\bjazz\b", re.I),
    re.compile(r"\bswing\b", re.I),
    re.compile(r"\bbebop\b", re.I),
    re.compile(r"\bbig\s+band\b", re.I),
    re.compile(r"\bblue\s+note\b", re.I),
    re.compile(r"\bfusion\b", re.I),
]

CLASSICAL_ANCHORS = [
    "bach",
    "mozart",
    "beethoven",
    "chopin",
    "mahler",
    "haydn",
    "vivaldi",
    "handel",
    "schubert",
    "brahms",
    "tchaikovsky",
    "debussy",
    "ravel",
    "stravinsky",
    "prokofiev",
    "shostakovich",
    "verdi",
    "wagner",
    "puccini",
]

JAZZ_ARTISTS = [
    "miles davis",
    "john coltrane",
    "thelonious monk",
    "bill evans",
    "oscar peterson",
    "ella fitzgerald",
    "louis armstrong",
    "duke ellington",
    "charles mingus",
    "dizzy gillespie",
    "count basie",
    "benny goodman",
    "wynton marsalis",
    "chick corea",
    "herbie hancock",
    "keith jarrett",
    "pat metheny",
    "brad mehldau",
    "stan getz",
]


def infer_is_jazz(album_title: str, artists: str, composers: str, epochs: str) -> bool:
    title = album_title or ""
    art = artists or ""
    comp = composers or ""
    blob = f"{title} {art} {comp}".strip()

    if any(p.search(blob) for p in JAZZ_PATTERNS):
        return True

    blob_l = blob.lower()
    has_classical_anchor = any(a in blob_l for a in CLASSICAL_ANCHORS)
    if has_classical_anchor:
        return False

    if any(name in blob_l for name in JAZZ_ARTISTS):
        return True

    return False


def add_genre(existing: str, new_genre: str) -> str:
    if not existing:
        return new_genre
    parts = [p.strip() for p in str(existing).split("|") if p.strip()]
    if new_genre not in parts:
        parts.append(new_genre)
    return " | ".join(parts)


__all__ = ["infer_is_jazz", "add_genre"]
