from __future__ import annotations

from datetime import datetime, timezone


def audit_payload(action: str, actor: dict, *, target_id: str | None = None,
                  target_username: str | None = None, changes: dict | None = None) -> dict:
    return {
        "action": action,
        "actorId": str(actor.get("_id") or actor.get("id") or ""),
        "actorUsername": actor.get("username", ""),
        "targetId": target_id,
        "targetUsername": target_username,
        "changes": changes or {},
        "createdAt": datetime.now(timezone.utc),
    }


async def record_admin_action(db, action: str, actor: dict, *, target_id: str | None = None,
                              target_username: str | None = None, changes: dict | None = None) -> None:
    await db.admin_action_logs.insert_one(audit_payload(
        action, actor, target_id=target_id, target_username=target_username, changes=changes,
    ))


def changed_fields(before: dict, after: dict) -> dict:
    return {key: {"from": before.get(key), "to": value} for key, value in after.items()
            if before.get(key) != value}
