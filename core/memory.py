import time
import uuid

import boto3
from boto3.dynamodb.conditions import Attr

from core.config import AGENT_MEMORY_TABLE_NAME


def _get_table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(AGENT_MEMORY_TABLE_NAME)


def get_active_memories() -> list[dict]:
    """Return all memory items with active=True."""
    if not AGENT_MEMORY_TABLE_NAME:
        return []
    table = _get_table()
    response = table.scan(FilterExpression=Attr("active").eq(True))
    return response.get("Items", [])


def save_memory(fact: str) -> dict:
    """Persist a new memory fact. Returns the saved item."""
    if not AGENT_MEMORY_TABLE_NAME:
        raise ValueError("AGENT_MEMORY_TABLE_NAME is not set")
    table = _get_table()
    memory_id = str(uuid.uuid4())
    item = {
        "id": memory_id,
        "fact": fact,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "active": True,
    }
    table.put_item(Item=item)
    return item


def delete_memory(memory_id: str) -> None:
    """Mark a memory as inactive (soft delete)."""
    if not AGENT_MEMORY_TABLE_NAME:
        raise ValueError("AGENT_MEMORY_TABLE_NAME is not set")
    table = _get_table()
    table.update_item(
        Key={"id": memory_id},
        UpdateExpression="SET active = :false",
        ExpressionAttributeValues={":false": False},
    )
