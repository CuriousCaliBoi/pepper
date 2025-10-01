import re
import unicodedata


def sanitize_text(raw_text: str) -> str:
    """
    Clean noisy characters often found in HTML-to-text outputs from emails/web pages.

    - Normalizes with NFKC
    - Removes CJK Compatibility Forms block (U+FE30–U+FE4F), including U+FE3F
    - Collapses long runs of repeated punctuation/symbols to at most 3
    """
    if not isinstance(raw_text, str):
        return raw_text

    text = unicodedata.normalize("NFKC", raw_text)
    # Remove CJK Compatibility Forms (includes U+FE3F)
    text = re.sub(r"[\uFE30-\uFE4F]+", "", text)
    # Collapse long runs of the same non-word, non-space characters
    text = re.sub(r"([^\w\s])\1{3,}", r"\1\1\1", text)
    # Trim excessive whitespace lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


