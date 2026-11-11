"""Einfache Textähnlichkeit ohne Zusatzbibliotheken (Wortzählung + Kosinus, Shingles)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

_WORD = re.compile(r"[a-zäöüß]{3,}", re.I)
STOPWORDS = set("""
und oder aber der die das den dem des ein eine einer eines einem einen ist sind war waren wird werden
mit von für auf aus bei bis nach über unter vor zum zur zu im in an am als auch nicht noch nur schon
sie ihr ihre ihren ihrem ihres wir uns unser unsere sehr geehrte geehrter damen herren freundlichen grüßen
bitte dass diese dieser dieses wie was wenn sich sein seine hat haben hatte kann können wurde mehr
seite datum herr frau the and for you your
""".split())


def tokens(text: str) -> list[str]:
    return [w for w in (m.group(0).lower() for m in _WORD.finditer(text or "")) if w not in STOPWORDS]


def vector(text: str) -> dict[str, int]:
    return dict(Counter(tokens(text)).most_common(120))


def cosine(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def fingerprint(text: str, k: int = 5, keep: int = 128) -> list[int]:
    """MinHash-artiger Fingerabdruck aus Wort-Shingles (zum Erkennen erneut gescannter Dokumente)."""
    words = re.findall(r"\w+", (text or "").lower())
    if len(words) < k:
        return []
    hashes = {int(hashlib.blake2b(" ".join(words[i:i + k]).encode(), digest_size=8).hexdigest(), 16)
              for i in range(len(words) - k + 1)}
    return sorted(hashes)[:keep]


def fingerprint_similarity(a: list[int], b: list[int]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    # Bottom-k-Schätzung der Jaccard-Ähnlichkeit
    union_bottom = sorted(sa | sb)[: min(len(a), len(b))]
    hits = sum(1 for h in union_bottom if h in sa and h in sb)
    return hits / len(union_bottom) if union_bottom else 0.0
