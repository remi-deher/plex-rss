"""Lecture normalisee unique des files Sonarr/Radarr."""

from ..models import ArrInstance
from . import radarr, sonarr


async def fetch_instance_queue(instance: ArrInstance) -> list[dict]:
    if instance.arr_type == "radarr":
        return await radarr.get_queue(instance.url, instance.api_key)
    if instance.arr_type == "sonarr":
        return await sonarr.get_queue(instance.url, instance.api_key)
    return []


async def fetch_queue_entity_ids(instance: ArrInstance) -> set[int]:
    records = await fetch_instance_queue(instance)
    return {
        int(record["arr_media_id"])
        for record in records
        if record.get("arr_media_id") is not None
    }
