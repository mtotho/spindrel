"""Unit tests for app.agent.chunking_treesitter — tree-sitter code chunking."""
import sys
from unittest.mock import patch

import pytest

from app.agent.chunking import ChunkResult

# Import conditionally — tests that need tree-sitter skip if not installed
try:
    from app.agent.chunking_treesitter import chunk_code_treesitter, EXT_TO_LANGUAGE
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

needs_treesitter = pytest.mark.skipif(
    not TREE_SITTER_AVAILABLE,
    reason="tree-sitter not installed",
)


# ---------------------------------------------------------------------------
# TypeScript / JavaScript
# ---------------------------------------------------------------------------

@needs_treesitter
class TestTypeScriptChunking:
    def test_function_declaration(self):
        source = """
function greet(name: string): string {
    return `Hello, ${name}`;
}

function farewell(name: string): string {
    return `Goodbye, ${name}`;
}
""".strip()
        chunks = chunk_code_treesitter(source, "utils.ts", "typescript")
        assert chunks is not None
        assert len(chunks) == 2
        assert chunks[0].symbol == "greet"
        assert chunks[1].symbol == "farewell"
        assert all(c.language == "typescript" for c in chunks)

    def test_arrow_function_export(self):
        source = """
export const add = (a: number, b: number): number => {
    return a + b;
};

export const subtract = (a: number, b: number): number => {
    return a - b;
};
""".strip()
        chunks = chunk_code_treesitter(source, "math.ts", "typescript")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "add" in symbols
        assert "subtract" in symbols

    def test_interface_declaration(self):
        source = """
interface User {
    name: string;
    age: number;
}

interface Post {
    title: string;
    body: string;
}

function createUser(name: string): User {
    return { name, age: 0 };
}
""".strip()
        chunks = chunk_code_treesitter(source, "types.ts", "typescript")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "User" in symbols
        assert "Post" in symbols
        assert "createUser" in symbols

    def test_type_alias(self):
        source = """
type ID = string | number;

type UserMap = Map<string, User>;

function getUser(id: ID): void {}
""".strip()
        chunks = chunk_code_treesitter(source, "types.ts", "typescript")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "ID" in symbols

    def test_class_with_methods(self):
        source = """
class Calculator {
    add(a: number, b: number): number {
        return a + b;
    }

    subtract(a: number, b: number): number {
        return a - b;
    }
}

function standalone(): void {}
""".strip()
        chunks = chunk_code_treesitter(source, "calc.ts", "typescript")
        assert chunks is not None
        # Should extract methods with class context
        method_chunks = [c for c in chunks if c.context_prefix and "class Calculator" in c.context_prefix]
        assert len(method_chunks) >= 1

    def test_enum_declaration(self):
        source = """
enum Color {
    Red,
    Green,
    Blue,
}

enum Size {
    Small,
    Medium,
    Large,
}

function getColor(): Color { return Color.Red; }
""".strip()
        chunks = chunk_code_treesitter(source, "enums.ts", "typescript")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "Color" in symbols

    def test_line_numbers(self):
        source = """function a() {}

function b() {}

function c() {}
""".strip()
        chunks = chunk_code_treesitter(source, "test.ts", "typescript")
        assert chunks is not None
        for chunk in chunks:
            assert chunk.start_line is not None
            assert chunk.end_line is not None
            assert chunk.start_line <= chunk.end_line


@needs_treesitter
class TestJavaScriptChunking:
    def test_basic_functions(self):
        source = """
function hello() {
    console.log("hello");
}

function world() {
    console.log("world");
}
""".strip()
        chunks = chunk_code_treesitter(source, "app.js", "javascript")
        assert chunks is not None
        assert len(chunks) == 2


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

@needs_treesitter
class TestGoChunking:
    def test_function_declarations(self):
        source = """package main

func Add(a, b int) int {
    return a + b
}

func Subtract(a, b int) int {
    return a - b
}
""".strip()
        chunks = chunk_code_treesitter(source, "math.go", "go")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "Add" in symbols
        assert "Subtract" in symbols
        assert all(c.language == "go" for c in chunks)

    def test_method_with_receiver(self):
        source = """package main

type Calculator struct {
    value int
}

func (c *Calculator) Add(n int) {
    c.value += n
}

func (c *Calculator) Reset() {
    c.value = 0
}
""".strip()
        chunks = chunk_code_treesitter(source, "calc.go", "go")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "Add" in symbols
        assert "Reset" in symbols

    def test_type_declaration(self):
        source = """package main

type User struct {
    Name string
    Age  int
}

type UserList []User

func NewUser(name string) User {
    return User{Name: name}
}
""".strip()
        chunks = chunk_code_treesitter(source, "types.go", "go")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "NewUser" in symbols


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------

@needs_treesitter
class TestRustChunking:
    def test_function_items(self):
        source = """
fn add(a: i32, b: i32) -> i32 {
    a + b
}

fn subtract(a: i32, b: i32) -> i32 {
    a - b
}
""".strip()
        chunks = chunk_code_treesitter(source, "math.rs", "rust")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "add" in symbols
        assert "subtract" in symbols
        assert all(c.language == "rust" for c in chunks)

    def test_pub_crate_fn(self):
        source = """
pub(crate) fn internal_helper() -> bool {
    true
}

pub fn public_fn() -> bool {
    false
}
""".strip()
        chunks = chunk_code_treesitter(source, "lib.rs", "rust")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "internal_helper" in symbols
        assert "public_fn" in symbols

    def test_async_and_const_fn(self):
        source = """
async fn fetch_data() -> Result<(), Error> {
    Ok(())
}

const fn max_size() -> usize {
    1024
}
""".strip()
        chunks = chunk_code_treesitter(source, "utils.rs", "rust")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "fetch_data" in symbols
        assert "max_size" in symbols

    def test_impl_block_context(self):
        source = """
struct Point {
    x: f64,
    y: f64,
}

impl Point {
    fn new(x: f64, y: f64) -> Self {
        Point { x, y }
    }

    fn distance(&self, other: &Point) -> f64 {
        ((self.x - other.x).powi(2) + (self.y - other.y).powi(2)).sqrt()
    }
}
""".strip()
        chunks = chunk_code_treesitter(source, "point.rs", "rust")
        assert chunks is not None
        # Methods from impl block should have context_prefix
        impl_chunks = [c for c in chunks if c.context_prefix and "impl Point" in c.context_prefix]
        assert len(impl_chunks) >= 1

    def test_trait_item(self):
        source = """
trait Drawable {
    fn draw(&self);
    fn area(&self) -> f64;
}

fn render() {}
""".strip()
        chunks = chunk_code_treesitter(source, "traits.rs", "rust")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "Drawable" in symbols

    def test_enum_item(self):
        source = """
enum Color {
    Red,
    Green,
    Blue,
}

enum Shape {
    Circle(f64),
    Rectangle(f64, f64),
}
""".strip()
        chunks = chunk_code_treesitter(source, "types.rs", "rust")
        assert chunks is not None
        symbols = [c.symbol for c in chunks]
        assert "Color" in symbols


# ---------------------------------------------------------------------------
# Fallback behavior
# ---------------------------------------------------------------------------

@needs_treesitter
class TestFallback:
    def test_returns_none_on_too_few_symbols(self):
        source = "fn only_one() {}"
        result = chunk_code_treesitter(source, "single.rs", "rust")
        assert result is None  # < 2 symbols → caller should fall back

    def test_malformed_source_still_attempts(self):
        # Incomplete code — tree-sitter is error-tolerant
        source = """
fn broken( {
    let x =
}

fn another() {}
""".strip()
        result = chunk_code_treesitter(source, "broken.rs", "rust")
        # May return None or partial results, shouldn't raise
        assert result is None or isinstance(result, list)


class TestGracefulDegradation:
    def test_import_error_propagates(self):
        """When tree-sitter is not installed, ImportError should propagate."""
        with patch.dict(sys.modules, {"tree_sitter": None}):
            # Clear parser cache to force re-import
            from app.agent import chunking_treesitter
            old_cache = chunking_treesitter._parser_cache.copy()
            chunking_treesitter._parser_cache.clear()
            try:
                with pytest.raises((ImportError, ModuleNotFoundError)):
                    chunking_treesitter._get_parser("typescript")
            finally:
                chunking_treesitter._parser_cache.update(old_cache)


@needs_treesitter
class TestOversizedSymbol:
    def test_oversized_symbol_sub_chunked(self):
        # Create a function with a very large body
        body_lines = "\n".join(f"    let x{i} = {i};" for i in range(200))
        source = f"""
fn small() -> i32 {{ 1 }}

fn huge() {{
{body_lines}
}}
""".strip()
        chunks = chunk_code_treesitter(source, "big.rs", "rust", max_chunk=500)
        assert chunks is not None
        # The huge function should be sub-chunked
        assert len(chunks) > 2
