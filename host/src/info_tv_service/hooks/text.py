"""Bound agent-supplied labels for the display's UTF-8 text fields."""


def display_text(value: str, byte_limit: int) -> str:
    """Collapse controls and truncate text at a UTF-8 character boundary.

    Parameters
    ----------
    value : str
        Agent-supplied display text.
    byte_limit : int
        Maximum encoded field size.

    Returns
    -------
    str
        Printable single-line text within the byte limit.
    """
    printable = "".join(character if character.isprintable() else " " for character in value)
    return " ".join(printable.split()).encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore").strip()
