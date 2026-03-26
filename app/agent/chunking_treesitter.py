"""Tree-sitter based code chunking for TS/JS, Go, and Rust.

Falls back gracefully to regex chunking when tree-sitter is not installed or
when parsing fails.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.agent.chunking import ChunkResult, chunk_sliding_window

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Lazy-initialized parser cache: language_name -> (Language, Parser)
_parser_cache: dict[str, tuple] = {}

# Map file extensions to tree-sitter language names
EXT_TO_LANGUAGE: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
}

# Node types we extract as top-level symbols, per language
_SYMBOL_TYPES: dict[str, set[str]] = {
    "typescript": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "export_statement",
    },
    "tsx": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "export_statement",
    },
    "javascript": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "export_statement",
    },
    "go": {
        "function_declaration",
        "method_declaration",
        "type_declaration",
    },
    "rust": {
        "function_item",
        "impl_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "type_item",
    },
}

# Node types that contain child symbols (methods/functions)
_CONTAINER_TYPES: dict[str, set[str]] = {
    "typescript": {"class_declaration", "class_body"},
    "tsx": {"class_declaration", "class_body"},
    "javascript": {"class_declaration", "class_body"},
    "go": set(),
    "rust": {"impl_item"},
}

# Node types that are child symbols within containers
_CHILD_SYMBOL_TYPES: dict[str, set[str]] = {
    "typescript": {"method_definition", "public_field_definition"},
    "tsx": {"method_definition", "public_field_definition"},
    "javascript": {"method_definition"},
    "go": set(),
    "rust": {"function_item"},
}


def _get_parser(language: str):
    """Lazily initialize and cache a tree-sitter parser for the given language.

    Raises ImportError if tree-sitter or the language grammar is not installed.
    """
    if language in _parser_cache:
        return _parser_cache[language]

    import tree_sitter

    lang_obj = _load_language(language)
    parser = tree_sitter.Parser(lang_obj)
    _parser_cache[language] = (lang_obj, parser)
    return lang_obj, parser


def _load_language(language: str):
    """Load a tree-sitter Language object for the given language name.

    Language grammars return PyCapsule pointers that must be wrapped in
    ``tree_sitter.Language()`` for the parser to accept them.
    """
    import tree_sitter

    if language in ("typescript", "tsx"):
        import tree_sitter_typescript
        ptr = tree_sitter_typescript.language_tsx() if language == "tsx" else tree_sitter_typescript.language_typescript()
    elif language == "javascript":
        import tree_sitter_javascript
        ptr = tree_sitter_javascript.language()
    elif language == "go":
        import tree_sitter_go
        ptr = tree_sitter_go.language()
    elif language == "rust":
        import tree_sitter_rust
        ptr = tree_sitter_rust.language()
    else:
        raise ValueError(f"Unsupported tree-sitter language: {language}")

    return tree_sitter.Language(ptr)


def _node_name(node, source_bytes: bytes, language: str) -> str | None:
    """Extract the symbol name from a tree-sitter node."""
    # For export_statement, dig into the child declaration
    if node.type == "export_statement":
        for child in node.children:
            if child.type in _SYMBOL_TYPES.get(language, set()):
                return _node_name(child, source_bytes, language)
            # Arrow function: export const foo = () => ...
            if child.type == "lexical_declaration":
                for decl_child in child.children:
                    if decl_child.type == "variable_declarator":
                        name_node = decl_child.child_by_field_name("name")
                        if name_node:
                            return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
        return None

    # Standard name field
    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")

    # Rust impl: get the type name
    if node.type == "impl_item":
        type_node = node.child_by_field_name("type")
        if type_node:
            return source_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace")

    # Go type_declaration: dig into type_spec
    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                n = child.child_by_field_name("name")
                if n:
                    return source_bytes[n.start_byte:n.end_byte].decode("utf-8", errors="replace")

    return None


def _container_name(node, source_bytes: bytes, language: str) -> str | None:
    """Get the container name for a node (class/impl block)."""
    if node.type in ("class_declaration",):
        name_node = node.child_by_field_name("name")
        if name_node:
            return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
    if node.type == "impl_item":
        type_node = node.child_by_field_name("type")
        if type_node:
            return source_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace")
    return None


def chunk_code_treesitter(
    source: str,
    rel_path: str,
    language: str,
    max_chunk: int = 2000,
) -> list[ChunkResult] | None:
    """Parse source with tree-sitter and extract symbol-level chunks.

    Returns None if tree-sitter is not available or parsing produces fewer
    than 2 symbols (caller should fall back to regex chunking).

    Raises ImportError if tree-sitter packages are not installed.
    """
    source_bytes = source.encode("utf-8")
    _lang_obj, parser = _get_parser(language)
    tree = parser.parse(source_bytes)

    if tree.root_node.has_error:
        # Tree has parse errors — still usable, but note it
        logger.debug("Tree-sitter parse errors in %s, attempting extraction anyway", rel_path)

    symbol_types = _SYMBOL_TYPES.get(language, set())
    container_types = _CONTAINER_TYPES.get(language, set())
    child_symbol_types = _CHILD_SYMBOL_TYPES.get(language, set())

    chunks: list[ChunkResult] = []
    lines = source.splitlines(keepends=True)

    # Walk top-level children
    for node in tree.root_node.children:
        if node.type in symbol_types:
            # Check if this is a container (class/impl) with child symbols
            if node.type in container_types and _has_extractable_children(node, child_symbol_types):
                # Extract child methods individually with container context
                container_label = _container_name(node, source_bytes, language)
                _extract_container_children(
                    node, source_bytes, lines, rel_path, language,
                    container_label, child_symbol_types, symbol_types,
                    chunks, max_chunk,
                )
            else:
                # Single top-level symbol
                _add_symbol_chunk(
                    node, source_bytes, lines, rel_path, language,
                    "", chunks, max_chunk,
                )

    if len(chunks) < 2:
        return None  # Too few symbols, caller should fall back

    return chunks


def _has_extractable_children(node, child_types: set[str]) -> bool:
    """Check if a container node has extractable child symbols."""
    for child in node.children:
        if child.type in child_types:
            return True
        # Check one level deeper (e.g. class_body -> method_definition)
        for grandchild in child.children:
            if grandchild.type in child_types:
                return True
    return False


def _extract_container_children(
    container_node,
    source_bytes: bytes,
    lines: list[str],
    rel_path: str,
    language: str,
    container_label: str | None,
    child_symbol_types: set[str],
    top_symbol_types: set[str],
    chunks: list[ChunkResult],
    max_chunk: int,
) -> None:
    """Extract child symbols from a container node (class/impl)."""
    context = f"class {container_label}" if container_label and language in ("typescript", "tsx", "javascript") else \
              f"impl {container_label}" if container_label and language == "rust" else \
              container_label or ""

    found_children = False
    for child in container_node.children:
        if child.type in child_symbol_types:
            _add_symbol_chunk(
                child, source_bytes, lines, rel_path, language,
                context, chunks, max_chunk,
            )
            found_children = True
        # Check one level deeper (class_body)
        for grandchild in child.children:
            if grandchild.type in child_symbol_types:
                _add_symbol_chunk(
                    grandchild, source_bytes, lines, rel_path, language,
                    context, chunks, max_chunk,
                )
                found_children = True

    # If no extractable children found, chunk the whole container
    if not found_children:
        _add_symbol_chunk(
            container_node, source_bytes, lines, rel_path, language,
            "", chunks, max_chunk,
        )


def _add_symbol_chunk(
    node,
    source_bytes: bytes,
    lines: list[str],
    rel_path: str,
    language: str,
    context_prefix: str,
    chunks: list[ChunkResult],
    max_chunk: int,
) -> None:
    """Create a ChunkResult from a tree-sitter node."""
    start_line = node.start_point[0] + 1  # 1-indexed
    end_line = node.end_point[0] + 1

    body = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    name = _node_name(node, source_bytes, language)

    # For display, use the comment char appropriate to the language
    comment_prefix = "//" if language in ("typescript", "tsx", "javascript", "go", "rust") else "#"
    chunk_content = f"{comment_prefix} {rel_path}\n{body}"

    if len(chunk_content) > max_chunk * 2:
        # Oversized symbol — sub-chunk with sliding window
        sub_chunks = chunk_sliding_window(
            body,
            source_label=rel_path,
            window=max_chunk,
            overlap=200,
            language=language,
        )
        for sc in sub_chunks:
            sc.symbol = name
            sc.start_line = start_line
            sc.end_line = end_line
            sc.context_prefix = context_prefix
            sc.content = f"{comment_prefix} {rel_path}\n{sc.content}"
        chunks.extend(sub_chunks)
    else:
        chunks.append(ChunkResult(
            content=chunk_content,
            context_prefix=context_prefix,
            symbol=name,
            start_line=start_line,
            end_line=end_line,
            language=language,
        ))
