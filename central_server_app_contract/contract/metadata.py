"""Optional, language-independent metadata shared by CLI and HTTP discovery."""
import re


def normalize_descriptions(value):
    """Accept language tags mapped to nonempty plain strings; ignore bad entries."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for language, text in value.items():
        if not isinstance(language, str) or not isinstance(text, str):
            continue
        tag = language.strip().replace("_", "-").lower()
        if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", tag) and text.strip():
            result[tag] = text.strip()
    return result
