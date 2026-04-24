from sqlalchemy import text


async def test_db_session_fixture_sees_seeded_default_dashboard(db_session):
    result = await db_session.execute(
        text("SELECT name FROM widget_dashboards WHERE slug = 'default'")
    )

    assert result.scalar_one() == "Default"
