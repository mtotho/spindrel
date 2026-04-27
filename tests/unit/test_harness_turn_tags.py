from app.services.turn_worker import _parse_harness_explicit_tags


def test_parse_harness_explicit_tags_extracts_unique_tools_and_skills():
    tools, skills = _parse_harness_explicit_tags(
        "Use @tool:web_search and @skill:widgets then @tool:web_search again."
    )

    assert tools == ("web_search",)
    assert skills == ("widgets",)


def test_parse_harness_explicit_tags_allows_path_style_skill_ids():
    tools, skills = _parse_harness_explicit_tags(
        "Review @skill:integrations/marp_slides/marp_slides with @tool:file."
    )

    assert tools == ("file",)
    assert skills == ("integrations/marp_slides/marp_slides",)


def test_parse_harness_explicit_tags_ignores_slack_mentions_and_email():
    tools, skills = _parse_harness_explicit_tags(
        "Ignore <@U123> and user@example.com but keep @tool:get_skill."
    )

    assert tools == ("get_skill",)
    assert skills == ()
