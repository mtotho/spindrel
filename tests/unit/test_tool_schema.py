"""Unit tests for app.tools.tool — schema inference helpers."""
from typing import Annotated, Optional, Union

from app.tools.tool import (
    _annotated_description,
    _first_line_description,
    _infer_schema,
    _parse_google_arg_descriptions,
    _strip_annotated,
    _to_json_schema,
    _unwrap_optional,
)


# ---------------------------------------------------------------------------
# _unwrap_optional
# ---------------------------------------------------------------------------

class TestUnwrapOptional:
    def test_optional_str(self):
        assert _unwrap_optional(Optional[str]) is str

    def test_plain_str(self):
        assert _unwrap_optional(str) is str

    def test_union_unchanged(self):
        t = Union[str, int]
        assert _unwrap_optional(t) is t

    def test_pipe_none(self):
        # Python 3.10+ `str | None` creates a types.UnionType.
        # As of Python 3.14, get_origin() normalizes this to typing.Union,
        # so _unwrap_optional correctly unwraps it to str.
        t = str | None
        result = _unwrap_optional(t)
        assert result is str


# ---------------------------------------------------------------------------
# _strip_annotated
# ---------------------------------------------------------------------------

class TestStripAnnotated:
    def test_annotated(self):
        assert _strip_annotated(Annotated[str, "desc"]) is str

    def test_plain(self):
        assert _strip_annotated(str) is str


# ---------------------------------------------------------------------------
# _annotated_description
# ---------------------------------------------------------------------------

class TestAnnotatedDescription:
    def test_with_string_metadata(self):
        assert _annotated_description(Annotated[str, "A description"]) == "A description"

    def test_non_string_metadata(self):
        assert _annotated_description(Annotated[str, 42]) is None

    def test_non_annotated(self):
        assert _annotated_description(str) is None


# ---------------------------------------------------------------------------
# _to_json_schema
# ---------------------------------------------------------------------------

class TestToJsonSchema:
    def test_str(self):
        assert _to_json_schema(str) == {"type": "string"}

    def test_int(self):
        assert _to_json_schema(int) == {"type": "integer"}

    def test_float(self):
        assert _to_json_schema(float) == {"type": "number"}

    def test_bool(self):
        assert _to_json_schema(bool) == {"type": "boolean"}

    def test_list_str(self):
        assert _to_json_schema(list[str]) == {
            "type": "array", "items": {"type": "string"}
        }

    def test_dict(self):
        assert _to_json_schema(dict) == {"type": "object"}

    def test_unknown_fallback(self):
        assert _to_json_schema(bytes) == {"type": "string"}


# ---------------------------------------------------------------------------
# _first_line_description
# ---------------------------------------------------------------------------

class TestFirstLineDescription:
    def test_none(self):
        assert _first_line_description(None) == ""

    def test_single_line(self):
        assert _first_line_description("Hello world") == "Hello world"

    def test_multiline(self):
        assert _first_line_description("First line\nSecond line") == "First line"

    def test_skips_leading_blanks(self):
        assert _first_line_description("\n\n  Real first line\nrest") == "Real first line"


# ---------------------------------------------------------------------------
# _parse_google_arg_descriptions
# ---------------------------------------------------------------------------

class TestParseGoogleArgDescriptions:
    def test_no_args_section(self):
        assert _parse_google_arg_descriptions("Just a docstring.") == {}

    def test_none(self):
        assert _parse_google_arg_descriptions(None) == {}

    def test_parses_args(self):
        doc = "Do something.\n\nArgs:\n    name: The name.\n    count: How many."
        result = _parse_google_arg_descriptions(doc)
        assert result == {"name": "The name.", "count": "How many."}

    def test_stops_at_double_newline(self):
        doc = "Do something.\n\nArgs:\n    name: The name.\n\nReturns:\n    str"
        result = _parse_google_arg_descriptions(doc)
        assert result == {"name": "The name."}


# ---------------------------------------------------------------------------
# _infer_schema
# ---------------------------------------------------------------------------

class TestInferSchema:
    def test_basic_function(self):
        def my_tool(query: str, count: int = 5):
            """Search for things.

            Args:
                query: The search query.
                count: Number of results.
            """

        schema = _infer_schema(my_tool, None, None)
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "my_tool"
        assert fn["description"] == "Search for things."
        assert "query" in fn["parameters"]["properties"]
        assert fn["parameters"]["properties"]["query"]["type"] == "string"
        assert "query" in fn["parameters"]["required"]
        assert "count" not in fn["parameters"]["required"]

    def test_skips_self_cls(self):
        def my_method(self, data: str):
            """A method."""

        schema = _infer_schema(my_method, None, None)
        assert "self" not in schema["function"]["parameters"]["properties"]

    def test_name_override(self):
        def my_func():
            """Doc."""

        schema = _infer_schema(my_func, "custom_name", None)
        assert schema["function"]["name"] == "custom_name"

    def test_description_override(self):
        def my_func():
            """Doc."""

        schema = _infer_schema(my_func, None, "Custom desc.")
        assert schema["function"]["description"] == "Custom desc."

    def test_annotated_description(self):
        def my_func(query: Annotated[str, "The search query"]):
            """Search."""

        schema = _infer_schema(my_func, None, None)
        props = schema["function"]["parameters"]["properties"]
        assert props["query"]["description"] == "The search query"

    def test_no_docstring_fallback(self):
        def my_func():
            pass

        schema = _infer_schema(my_func, None, None)
        assert schema["function"]["description"] == "Tool my_func."
