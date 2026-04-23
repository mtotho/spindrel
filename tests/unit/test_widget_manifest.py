"""Unit tests for app.services.widget_manifest."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from app.services.widget_manifest import (
    ManifestError,
    WidgetManifest,
    parse_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, content: str, filename: str = "widget.yaml") -> Path:
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_minimal_manifest(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Test Widget
            version: 1.0.0
            description: A test
            """,
        )
        m = parse_manifest(p)
        assert isinstance(m, WidgetManifest)
        assert m.name == "Test Widget"
        assert m.version == "1.0.0"
        assert m.description == "A test"
        assert m.permissions.tools == []
        assert m.permissions.events == []
        assert m.cron == []
        assert m.events == []
        assert m.db is None
        assert m.source_path == p

    def test_panel_title_metadata_is_parsed(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Home control
            version: 1.0.0
            description: A test
            panel_title: Home Command Center
            show_panel_title: true
            """,
        )
        m = parse_manifest(p)
        assert m.panel_title == "Home Command Center"
        assert m.show_panel_title is True

    def test_presentation_family_is_parsed(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Quick toggle
            version: 1.0.0
            description: Compact control
            presentation_family: chip
            """,
        )
        m = parse_manifest(p)
        assert m.presentation_family == "chip"

    def test_config_schema_is_parsed(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Home control
            version: 1.0.0
            description: A test
            config_schema:
              type: object
              required: [entity_id]
              properties:
                entity_id:
                  type: string
                  title: Entity
            """,
        )
        m = parse_manifest(p)
        assert m.config_schema == {
            "type": "object",
            "required": ["entity_id"],
            "properties": {
                "entity_id": {
                    "type": "string",
                    "title": "Entity",
                },
            },
        }

    def test_full_manifest(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Cost Tracker
            version: 2.0.0
            description: Track spend
            permissions:
              tools: [send_push_notification]
              events: [turn_ended, tool_activity]
            cron:
              - name: daily_rollup
                schedule: "5 0 * * *"
                handler: daily_rollup
            events:
              - kind: turn_ended
                handler: on_turn_ended
              - kind: tool_activity
                handler: on_tool_activity
            db:
              schema_version: 2
              migrations:
                - from: 0
                  to: 1
                  sql: "create table t (id integer primary key);"
                - from: 1
                  to: 2
                  sql: "alter table t add column x integer default 0;"
            """,
        )
        m = parse_manifest(p)
        assert m.name == "Cost Tracker"
        assert m.permissions.tools == ["send_push_notification"]
        assert m.permissions.events == ["turn_ended", "tool_activity"]
        assert len(m.cron) == 1
        assert m.cron[0].name == "daily_rollup"
        assert m.cron[0].schedule == "5 0 * * *"
        assert m.cron[0].handler == "daily_rollup"
        assert len(m.events) == 2
        assert m.events[0].kind == "turn_ended"
        assert m.db is not None
        assert m.db.schema_version == 2
        assert len(m.db.migrations) == 2
        assert m.db.migrations[0].from_version == 0
        assert m.db.migrations[0].to_version == 1
        assert m.db.migrations[1].from_version == 1
        assert m.db.migrations[1].to_version == 2

    def test_db_shared_accepted(self, tmp_path):
        """`db.shared` on its own is valid — the suite manifest owns schema."""
        p = write_yaml(
            tmp_path,
            """\
            name: MC Timeline
            version: 1.0.0
            description: ""
            db:
              shared: mission-control
            """,
        )
        m = parse_manifest(p)
        assert m.db is not None
        assert m.db.shared == "mission-control"
        assert m.db.schema_version == 0
        assert m.db.migrations == []

    def test_db_shared_with_migrations_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: ""
            db:
              shared: mission-control
              migrations:
                - from: 0
                  to: 1
                  sql: "select 1;"
            """,
        )
        with pytest.raises(ManifestError, match="mutually exclusive"):
            parse_manifest(p)

    def test_db_shared_invalid_slug_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: ""
            db:
              shared: "BAD SLUG"
            """,
        )
        with pytest.raises(ManifestError, match="slug"):
            parse_manifest(p)


class TestExtraCspValidation:
    """Sidecar ``widget.yaml`` can declare CSP allowances so cross-dashboard
    re-pinning keeps cross-origin loads (Google Maps, Mapbox, …) working
    without re-invoking ``emit_html_widget``."""

    def test_extra_csp_accepted(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Map
            version: 1.0.0
            description: ""
            extra_csp:
              script_src:
                - "https://maps.googleapis.com"
              connect_src:
                - "https://maps.googleapis.com"
            """,
        )
        m = parse_manifest(p)
        assert m.extra_csp is not None
        assert m.extra_csp["script_src"] == ["https://maps.googleapis.com"]
        assert m.extra_csp["connect_src"] == ["https://maps.googleapis.com"]

    def test_extra_csp_missing_defaults_none(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: ""
            """,
        )
        m = parse_manifest(p)
        assert m.extra_csp is None

    def test_extra_csp_http_origin_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: ""
            extra_csp:
              script_src:
                - "http://insecure.example.com"
            """,
        )
        with pytest.raises(ManifestError, match="extra_csp"):
            parse_manifest(p)

    def test_db_no_migrations(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: ""
            db:
              schema_version: 1
            """,
        )
        m = parse_manifest(p)
        assert m.db is not None
        assert m.db.schema_version == 1
        assert m.db.migrations == []

    def test_version_defaults(self, tmp_path):
        p = write_yaml(tmp_path, "name: W\ndescription: ''\n")
        m = parse_manifest(p)
        assert m.version == "0.0.0"
        assert m.panel_title is None
        assert m.show_panel_title is None

    def test_config_schema_rejects_non_object_type(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            description: ""
            config_schema:
              type: array
            """,
        )
        with pytest.raises(ManifestError, match="config_schema.type"):
            parse_manifest(p)


# ---------------------------------------------------------------------------
# Validation — name
# ---------------------------------------------------------------------------


class TestNameValidation:
    def test_missing_name_raises(self, tmp_path):
        p = write_yaml(tmp_path, "version: 1.0.0\ndescription: x\n")
        with pytest.raises(ManifestError, match="name"):
            parse_manifest(p)


class TestPanelTitleValidation:
    def test_non_string_panel_title_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            panel_title: 123
            """,
        )
        with pytest.raises(ManifestError, match="panel_title"):
            parse_manifest(p)

    def test_non_bool_show_panel_title_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            show_panel_title: "yes"
            """,
        )
        with pytest.raises(ManifestError, match="show_panel_title"):
            parse_manifest(p)

    def test_empty_name_raises(self, tmp_path):
        p = write_yaml(tmp_path, "name: ''\nversion: 1.0.0\ndescription: x\n")
        with pytest.raises(ManifestError, match="name"):
            parse_manifest(p)

    def test_whitespace_only_name_raises(self, tmp_path):
        p = write_yaml(tmp_path, "name: '   '\nversion: 1.0.0\ndescription: x\n")
        with pytest.raises(ManifestError, match="name"):
            parse_manifest(p)


# ---------------------------------------------------------------------------
# Validation — cron
# ---------------------------------------------------------------------------


class TestCronValidation:
    def test_invalid_cron_expr_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            cron:
              - name: tick
                schedule: "not a cron"
                handler: tick
            """,
        )
        with pytest.raises(ManifestError, match="cron"):
            parse_manifest(p)

    def test_cron_non_list_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            "name: W\nversion: 1.0.0\ndescription: x\ncron: not-a-list\n",
        )
        with pytest.raises(ManifestError, match="cron"):
            parse_manifest(p)

    def test_missing_handler_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            cron:
              - name: tick
                schedule: "* * * * *"
            """,
        )
        with pytest.raises(ManifestError, match="handler"):
            parse_manifest(p)

    def test_valid_cron_passes(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            cron:
              - name: tick
                schedule: "*/5 * * * *"
                handler: my_handler
            """,
        )
        m = parse_manifest(p)
        assert m.cron[0].schedule == "*/5 * * * *"


# ---------------------------------------------------------------------------
# Validation — events
# ---------------------------------------------------------------------------


class TestEventsValidation:
    def test_invalid_event_kind_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            events:
              - kind: not_a_real_kind
                handler: h
            """,
        )
        with pytest.raises(ManifestError, match="not_a_real_kind"):
            parse_manifest(p)

    def test_valid_event_kind_passes(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            events:
              - kind: new_message
                handler: on_msg
            """,
        )
        m = parse_manifest(p)
        assert m.events[0].kind == "new_message"

    def test_permissions_events_invalid_kind_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            permissions:
              events: [nope]
            """,
        )
        with pytest.raises(ManifestError, match="nope"):
            parse_manifest(p)

    def test_permissions_events_valid_passes(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            permissions:
              events: [turn_ended, tool_activity]
            """,
        )
        m = parse_manifest(p)
        assert m.permissions.events == ["turn_ended", "tool_activity"]


# ---------------------------------------------------------------------------
# Validation — db
# ---------------------------------------------------------------------------


class TestDbValidation:
    def test_schema_version_less_than_1_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            db:
              schema_version: 0
            """,
        )
        with pytest.raises(ManifestError, match="schema_version"):
            parse_manifest(p)

    def test_gap_in_migrations_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            db:
              schema_version: 3
              migrations:
                - from: 1
                  to: 2
                  sql: "select 1"
                - from: 3
                  to: 4
                  sql: "select 2"
            """,
        )
        with pytest.raises(ManifestError):
            parse_manifest(p)

    def test_non_sequential_to_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            db:
              schema_version: 2
              migrations:
                - from: 1
                  to: 3
                  sql: "select 1"
            """,
        )
        with pytest.raises(ManifestError, match="to"):
            parse_manifest(p)

    def test_migration_schema_version_mismatch_raises(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: W
            version: 1.0.0
            description: x
            db:
              schema_version: 3
              migrations:
                - from: 0
                  to: 1
                  sql: "select 1"
            """,
        )
        with pytest.raises(ManifestError, match="schema_version"):
            parse_manifest(p)

    def test_downgrade_would_be_caught_at_schema_version(self, tmp_path):
        """schema_version < 1 is invalid regardless."""
        p = write_yaml(
            tmp_path,
            "name: W\nversion: 1.0.0\ndescription: x\ndb:\n  schema_version: -1\n",
        )
        with pytest.raises(ManifestError, match="schema_version"):
            parse_manifest(p)


# ---------------------------------------------------------------------------
# Top-level structure errors
# ---------------------------------------------------------------------------


class TestStructureErrors:
    def test_not_a_mapping_raises(self, tmp_path):
        p = tmp_path / "widget.yaml"
        p.write_text("- just a list\n", encoding="utf-8")
        with pytest.raises(ManifestError):
            parse_manifest(p)

    def test_invalid_yaml_raises(self, tmp_path):
        p = tmp_path / "widget.yaml"
        p.write_text("name: [unclosed\n", encoding="utf-8")
        with pytest.raises(Exception):  # yaml.YAMLError
            parse_manifest(p)


# ---------------------------------------------------------------------------
# layout_hints
# ---------------------------------------------------------------------------


class TestLayoutHints:
    def test_absent_layout_hints_is_none(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: NoHints
            version: 1.0.0
            """,
        )
        m = parse_manifest(p)
        assert m.layout_hints is None

    def test_chip_hints_round_trip(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Chippy
            version: 1.0.0
            layout_hints:
              preferred_zone: chip
              min_cells: {w: 2, h: 1}
              max_cells: {w: 4, h: 1}
            """,
        )
        m = parse_manifest(p)
        assert m.layout_hints is not None
        assert m.layout_hints.preferred_zone == "chip"
        assert m.layout_hints.min_cells == {"w": 2, "h": 1}
        assert m.layout_hints.max_cells == {"w": 4, "h": 1}

    def test_preferred_zone_only(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Gridly
            version: 1.0.0
            layout_hints:
              preferred_zone: grid
            """,
        )
        m = parse_manifest(p)
        assert m.layout_hints.preferred_zone == "grid"
        assert m.layout_hints.min_cells is None
        assert m.layout_hints.max_cells is None

    def test_invalid_preferred_zone_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            layout_hints:
              preferred_zone: sidebar
            """,
        )
        with pytest.raises(ManifestError, match="preferred_zone"):
            parse_manifest(p)

    def test_non_integer_min_cells_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            layout_hints:
              min_cells: {w: two, h: 1}
            """,
        )
        with pytest.raises(ManifestError, match="min_cells.w"):
            parse_manifest(p)

    def test_zero_cells_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            layout_hints:
              max_cells: {w: 0, h: 1}
            """,
        )
        with pytest.raises(ManifestError, match="max_cells.w"):
            parse_manifest(p)

    def test_unknown_cell_key_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            layout_hints:
              min_cells: {w: 2, h: 1, x: 3}
            """,
        )
        with pytest.raises(ManifestError, match="unknown keys"):
            parse_manifest(p)

    def test_min_exceeds_max_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            layout_hints:
              min_cells: {w: 5, h: 1}
              max_cells: {w: 4, h: 1}
            """,
        )
        with pytest.raises(ManifestError, match="exceeds"):
            parse_manifest(p)

    def test_non_mapping_layout_hints_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            layout_hints: chip
            """,
        )
        with pytest.raises(ManifestError, match="layout_hints"):
            parse_manifest(p)


# ---------------------------------------------------------------------------
# HandlerSpec (bot-callable @on_action declarations)
# ---------------------------------------------------------------------------


class TestHandlerSpec:
    def test_absent_handlers_defaults_to_empty_list(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: No Handlers
            version: 1.0.0
            """,
        )
        m = parse_manifest(p)
        assert m.handlers == []

    def test_full_handler_round_trip(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Todo
            version: 1.0.0
            description: Todo list
            handlers:
              - name: add_todo
                description: Add a new todo item.
                triggers: [add todo, new task, remember to]
                args:
                  title:
                    type: string
                    description: Task text
                returns:
                  type: object
                  properties:
                    id: {type: string}
                bot_callable: true
                safety_tier: mutating
              - name: list_todos
                description: List all todos.
                bot_callable: true
                safety_tier: readonly
            """,
        )
        m = parse_manifest(p)
        assert len(m.handlers) == 2

        add = m.handlers[0]
        assert add.name == "add_todo"
        assert add.description.startswith("Add a new todo")
        assert add.triggers == ["add todo", "new task", "remember to"]
        assert add.args is not None and "title" in add.args
        assert add.returns is not None and add.returns["type"] == "object"
        assert add.bot_callable is True
        assert add.safety_tier == "mutating"

        lst = m.handlers[1]
        assert lst.name == "list_todos"
        assert lst.bot_callable is True
        assert lst.safety_tier == "readonly"
        assert lst.args is None
        assert lst.triggers == []

    def test_bot_callable_defaults_false(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Internal
            version: 1.0.0
            handlers:
              - name: internal_only
                description: Not exposed to bots.
            """,
        )
        m = parse_manifest(p)
        assert m.handlers[0].bot_callable is False
        assert m.handlers[0].safety_tier == "mutating"  # default

    def test_invalid_handler_name_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            handlers:
              - name: BadName!
                description: x
            """,
        )
        with pytest.raises(ManifestError, match="handlers\\[0\\].name"):
            parse_manifest(p)

    def test_duplicate_handler_name_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            handlers:
              - name: do_thing
                description: first
              - name: do_thing
                description: second
            """,
        )
        with pytest.raises(ManifestError, match="duplicates"):
            parse_manifest(p)

    def test_invalid_safety_tier_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            handlers:
              - name: do_thing
                description: x
                safety_tier: control_plane
            """,
        )
        with pytest.raises(ManifestError, match="safety_tier"):
            parse_manifest(p)

    def test_bot_callable_without_description_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            handlers:
              - name: do_thing
                bot_callable: true
            """,
        )
        with pytest.raises(ManifestError, match="description is required"):
            parse_manifest(p)

    def test_non_list_handlers_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            handlers: not-a-list
            """,
        )
        with pytest.raises(ManifestError, match="handlers must be a list"):
            parse_manifest(p)

    def test_non_mapping_args_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            handlers:
              - name: do_thing
                description: x
                args: not-a-mapping
            """,
        )
        with pytest.raises(ManifestError, match="args must be a mapping"):
            parse_manifest(p)

    def test_non_boolean_bot_callable_rejected(self, tmp_path):
        p = write_yaml(
            tmp_path,
            """\
            name: Bad
            version: 1.0.0
            handlers:
              - name: do_thing
                description: x
                bot_callable: "yes"
            """,
        )
        with pytest.raises(ManifestError, match="bot_callable"):
            parse_manifest(p)


# ---------------------------------------------------------------------------
# Scanner cache invalidation on yaml_mtime
# ---------------------------------------------------------------------------


class TestScannerCacheInvalidation:
    def test_yaml_mtime_bump_invalidates_cache(self, tmp_path):
        """Modifying widget.yaml triggers a re-parse even if index.html is unchanged."""
        import time

        from app.services.html_widget_scanner import (
            _SCAN_CACHE,
            _scan_metadata_for,
        )

        # Write a channel-workspace-like directory with a widget in a `widgets/` subdir.
        widget_dir = tmp_path / "widgets" / "proj"
        widget_dir.mkdir(parents=True)
        html_file = widget_dir / "index.html"
        yaml_file = widget_dir / "widget.yaml"

        html_file.write_text(
            "<!-- ---\nname: Proj\ndescription: d\n--- -->\nwindow.spindrel.bus",
            encoding="utf-8",
        )
        yaml_file.write_text("name: Proj\nversion: 1.0.0\ndescription: from yaml\n", encoding="utf-8")

        html_mtime = html_file.stat().st_mtime
        channel_id = "chan-cache-test"
        rel_path = "widgets/proj/index.html"

        # First call populates cache.
        meta1 = _scan_metadata_for(channel_id, rel_path, str(html_file), html_mtime)
        assert meta1 is not None
        assert meta1.get("__has_manifest") is True
        assert meta1.get("name") == "Proj"

        # Simulate yaml mtime bump without touching html.
        time.sleep(0.01)
        yaml_file.write_text("name: Updated\nversion: 2.0.0\ndescription: changed\n", encoding="utf-8")
        new_yaml_mtime = yaml_file.stat().st_mtime

        # Second call: html mtime same, yaml mtime different → re-parse.
        meta2 = _scan_metadata_for(channel_id, rel_path, str(html_file), html_mtime)
        assert meta2 is not None
        assert meta2.get("name") == "Updated"

        # Cleanup: remove test entries from global cache.
        _SCAN_CACHE.pop((channel_id, rel_path), None)
