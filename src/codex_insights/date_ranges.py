"""Calendar windows shared by indexed queries and summary image captions."""
from datetime import date, timedelta


def date_window(filters, today):
    """Return the inclusive start and exclusive end, in the display timezone."""
    selected = filters.get("range", "all")
    start, end = None, today + timedelta(days=1)
    if selected in {"today", "7", "30", "90"}:
        start = today - timedelta(days=(1 if selected == "today" else int(selected)) - 1)
    elif selected == "custom":
        start = date.fromisoformat(filters["start"])
        end = date.fromisoformat(filters["end"]) + timedelta(days=1)
        if start >= end:
            raise ValueError("Start date must not follow end date")
    return start, end
