from admin_audit import audit_payload, changed_fields


def test_changed_fields_returns_only_differences():
    assert changed_fields({"a": 1, "b": 2}, {"a": 1, "b": 3}) == {"b": {"from": 2, "to": 3}}


def test_audit_payload_keeps_actor_target_and_timestamp():
    payload = audit_payload(
        "user.update",
        {"username": "admin", "id": "admin-id"},
        target_id="target-id",
        target_username="player",
        changes={"balance": {"from": 1, "to": 2}},
    )
    assert payload["action"] == "user.update"
    assert payload["actorUsername"] == "admin"
    assert payload["targetId"] == "target-id"
    assert payload["changes"]["balance"]["to"] == 2
    assert payload["createdAt"]


if __name__ == "__main__":
    test_changed_fields_returns_only_differences()
    test_audit_payload_keeps_actor_target_and_timestamp()
    print("OK")
