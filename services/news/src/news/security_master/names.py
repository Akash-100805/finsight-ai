"""Name helpers: slug, alias normalization, legal-suffix stripping (guide 6.2)."""
import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_STATE_SUFFIX = re.compile(r"\s*/[a-z]{2,4}/?\s*$")
# Fixed suffix list (guide 6.2), applied repeatedly from the end of the name.
_SUFFIX = re.compile(
    r"(?:\s*,\s*|\s+)(?:limited|ltd\.?|inc\.?|corp\.?|corporation|co\.?|plc)\s*$"
    r"|\s*\(india\)\s*$"
    r"|\s+india\s+ltd\.?\s*$",
    re.IGNORECASE,
)


def slugify(label: str) -> str:
    """Sector id from a label: lowercase, '&' -> 'and', other non-alphanumeric runs -> '_', trimmed."""
    text = label.casefold().replace("&", " and ")
    return _NON_ALNUM.sub("_", text).strip("_")


def normalize(text: str) -> str:
    """alias_norm: casefold, '&' -> ' and ', drop '.' and apostrophes, drop SEC state suffix like /DE/,
    collapse other non-alphanumeric runs to one space, trim."""
    text = text.casefold().replace("&", " and ")
    text = text.replace(".", "").replace("'", "").replace("\u2019", "")
    text = _STATE_SUFFIX.sub("", text)
    return _NON_ALNUM.sub(" ", text).strip()


def strip_suffixes(name: str) -> str:
    """Remove legal suffixes repeatedly from the end. Never strips the name down to nothing."""
    current = name.strip().rstrip(",").strip()
    while True:
        stripped = _SUFFIX.sub("", current).strip().rstrip(",").strip()
        if stripped == current or not stripped:
            return current
        current = stripped