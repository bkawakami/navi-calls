from datetime import datetime, timezone

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")


def format_datetime(value, fmt="%d/%m/%Y %H:%M"):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone().strftime(fmt)
    return value or ""


def format_seconds(value):
    try:
        total = int(float(value))
    except (TypeError, ValueError):
        return "--:--"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


templates.env.filters["datetime"] = format_datetime
templates.env.filters["seconds"] = format_seconds
templates.env.globals["now"] = lambda: datetime.now(timezone.utc)


def get_templates():
    return templates
