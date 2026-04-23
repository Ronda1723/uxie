"""
normalize.py — Post-STT symbol normalization.

Converts spoken words to symbols for emails and URLs, applied to the raw
transcript BEFORE the grammar LLM sees it. Keeps prose untouched.

Pipeline position (in audio.py):
    raw_text = _consolidate_fragments(...)
    raw_text = normalize.apply(raw_text)   ← here
    raw_text = dictionary.apply(raw_text)
    raw_text = snippets.apply(raw_text)
"""

from __future__ import annotations

import re

# ── Spoken word → symbol maps ────────────────────────────────────────────────

_AT_WORDS = re.compile(
    r"\bat(?:\s+the\s+rate(?:\s+of)?|\s+sign)?\b",
    re.IGNORECASE,
)

_DOT_WORD = re.compile(r"\bdot\b", re.IGNORECASE)
_DASH_WORD = re.compile(r"\b(?:dash|hyphen)\b", re.IGNORECASE)
_UNDERSCORE_WORD = re.compile(r"\bunderscore\b", re.IGNORECASE)
_SLASH_WORD = re.compile(r"\bforward\s+slash\b|\bslash\b", re.IGNORECASE)

# Common TLDs — presence of these after "dot" strongly signals an email/URL
_TLDS = {"com", "org", "net", "io", "co", "ai", "app", "dev", "me", "us",
         "edu", "gov", "uk", "in", "de", "fr", "ca", "au"}

# Keyword anchors that raise confidence the next token is an email/address
_ANCHOR_RE = re.compile(
    r"\b(send\s+to|email\s+(?:is|to|address)|invite|cc|bcc|contact|reply\s+to|from)\b",
    re.IGNORECASE,
)

# Matches a word (letters/digits/hyphens) that could be part of an email local or domain
_WORD_PART = r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?"


# ── Core detection ────────────────────────────────────────────────────────────

def _looks_like_email_span(tokens: list[str]) -> bool:
    """True if tokens contain an @ signal AND a dot signal with a TLD."""
    text = " ".join(tokens).lower()
    has_at = bool(_AT_WORDS.search(text))
    dot_parts = _DOT_WORD.split(text)
    has_tld = any(p.strip().split()[-1] in _TLDS for p in dot_parts[1:] if p.strip())
    return has_at and has_tld


def _resolve_span(span: str) -> str:
    """Apply symbol substitutions inside a detected email/URL span."""
    s = _AT_WORDS.sub("@", span)
    # Resolve dot: only between word characters (not at sentence boundaries)
    s = re.sub(r"(?<=[a-zA-Z0-9])\s+dot\s+(?=[a-zA-Z0-9])", ".", s, flags=re.IGNORECASE)
    s = re.sub(r"\bdot\b", ".", s, flags=re.IGNORECASE)
    s = _UNDERSCORE_WORD.sub("_", s)
    s = _DASH_WORD.sub("-", s)
    s = _SLASH_WORD.sub("/", s)
    # Collapse spaces inside the resolved address
    s = re.sub(r"\s+(?=[@._/\-])|(?<=[@._/\-])\s+", "", s)
    return s.strip()


def _find_email_spans(text: str) -> list[tuple[int, int]]:
    """
    Return (start, end) character spans that look like dictated emails/URLs.
    Heuristic: look for an @ word, then expand left/right up to 8 words to
    capture the full address, provided a TLD is found in that window.
    """
    spans: list[tuple[int, int]] = []
    words = text.split()
    for i, word in enumerate(words):
        if not _AT_WORDS.fullmatch(word.strip(".,!?;")):
            continue
        # Window: up to 4 words left and 6 words right
        left = max(0, i - 4)
        right = min(len(words), i + 7)
        window = words[left:right]
        if _looks_like_email_span(window):
            # Map back to character offsets
            start_chars = len(" ".join(words[:left])) + (1 if left > 0 else 0)
            end_chars = len(" ".join(words[:right]))
            spans.append((start_chars, end_chars))
    return _merge_spans(spans)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


# ── Public API ────────────────────────────────────────────────────────────────

def apply(text: str) -> str:
    """
    Normalize spoken symbols in email/URL contexts. Prose is left untouched.

    Examples:
        "send to john at gmail dot com"  → "send to john@gmail.com"
        "invite sarah underscore k at acme dot io" → "invite sarah_k@acme.io"
        "I met John dot He was nice"    → "I met John dot He was nice"  (no change)
    """
    if not text:
        return text

    # Fast path: no AT word in text → nothing to normalize
    if not _AT_WORDS.search(text):
        return text

    spans = _find_email_spans(text)
    if not spans:
        return text

    # Replace spans from right to left so offsets stay valid
    result = text
    for start, end in reversed(spans):
        raw_span = result[start:end]
        resolved = _resolve_span(raw_span)
        result = result[:start] + resolved + result[end:]

    return result
