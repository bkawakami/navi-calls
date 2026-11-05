from .event import Event
from .meeting import Meeting
from .minutes import Minutes
from .note import Note
from .transcript_segment import TranscriptSegment


async def ensure_indexes(db):
    for cls in (Meeting, TranscriptSegment, Note, Event, Minutes):
        await cls(db).ensure_indexes()


__all__ = ["Meeting", "TranscriptSegment", "Note", "Event", "Minutes", "ensure_indexes"]
