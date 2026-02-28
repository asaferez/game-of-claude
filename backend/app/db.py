import os
import logging
import hashlib
from functools import lru_cache
from supabase import create_client, Client

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def make_source_key(session_id: str, tool_call_id: str) -> str:
    raw = f"{session_id}:{tool_call_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def is_already_processed(db: Client, source_key: str) -> bool:
    try:
        db.table("processed_events").insert({"source_key": source_key}).execute()
        return False
    except Exception as e:
        # A unique-constraint violation means the event was already processed —
        # any other exception is unexpected and should be visible in logs.
        err_str = str(e).lower()
        if "duplicate" in err_str or "unique" in err_str or "23505" in err_str:
            return True
        logger.error("Unexpected deduplication error for key=%s: %s", source_key, e)
        return True  # treat as duplicate to avoid double-XP on transient errors


def get_device(db: Client, device_id: str) -> dict | None:
    res = db.table("devices").select("*").eq("device_id", device_id).execute()
    return res.data[0] if res.data else None


def get_stats(db: Client, device_id: str) -> dict:
    res = db.table("user_stats").select("*").eq("device_id", device_id).execute()
    return res.data[0] if res.data else {}


def get_quest_progress(db: Client, device_id: str) -> dict[str, dict]:
    res = db.table("quest_progress").select("*").eq("device_id", device_id).execute()
    return {row["quest_id"]: row for row in (res.data or [])}


def award_xp(db: Client, device_id: str, source: str, amount: int) -> None:
    db.table("xp_log").insert({"device_id": device_id, "source": source, "amount": amount}).execute()


def upsert_stats(db: Client, device_id: str, updates: dict) -> None:
    db.table("user_stats").upsert({"device_id": device_id, **updates}).execute()


def upsert_quest_progress(db: Client, device_id: str, quest_id: str, updates: dict) -> None:
    db.table("quest_progress").upsert({"device_id": device_id, "quest_id": quest_id, **updates}).execute()


def log_raw_event(db: Client, device_id: str, session_id: str | None, event_type: str, data: dict) -> None:
    db.table("events").insert({"device_id": device_id, "session_id": session_id, "event_type": event_type, "data": data}).execute()
