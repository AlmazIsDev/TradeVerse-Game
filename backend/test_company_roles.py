from company import MIN_INVITE_CAPITAL, ROLE_MIN_CAPITAL, capital_is_available, role_is_available


def test_role_thresholds_for_candidate_capital():
    assert role_is_available("intern", 0)
    assert role_is_available("worker", 0)
    assert not role_is_available("manager", ROLE_MIN_CAPITAL["manager"] - 0.01)
    assert role_is_available("manager", ROLE_MIN_CAPITAL["manager"])
    assert not role_is_available("engineer", ROLE_MIN_CAPITAL["engineer"] - 0.01)
    assert role_is_available("engineer", ROLE_MIN_CAPITAL["engineer"])
    assert not role_is_available("director", ROLE_MIN_CAPITAL["director"] - 0.01)
    assert role_is_available("director", ROLE_MIN_CAPITAL["director"])


def test_invites_require_300k_total_capital():
    assert not capital_is_available(MIN_INVITE_CAPITAL - 0.01)
    assert capital_is_available(MIN_INVITE_CAPITAL)
    assert capital_is_available(MIN_INVITE_CAPITAL + 1)


if __name__ == "__main__":
    test_role_thresholds_for_candidate_capital()
    test_invites_require_300k_total_capital()
    print("OK")


