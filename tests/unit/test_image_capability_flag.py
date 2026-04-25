"""Unit tests for ``ProviderModel.supports_image_generation`` plumbing.

Covers the in-memory cache exposed by ``app.services.providers``:

* ``supports_image_generation(model)`` reads the cached set.
* ``supports_image_generation_set()`` returns sorted contents.
* The cache module-level variable is the source of truth — tests scope
  their mutations so they don't leak into other tests.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def patched_image_gen_cache():
    """Replace ``_image_gen_models`` for the duration of one test."""
    from app.services import providers as p

    original = p._image_gen_models
    p._image_gen_models = set()
    yield p
    p._image_gen_models = original


def test_supports_image_generation_returns_false_for_unflagged(patched_image_gen_cache):
    p = patched_image_gen_cache
    p._image_gen_models = {"gpt-image-1"}
    assert p.supports_image_generation("gpt-image-1") is True
    assert p.supports_image_generation("gpt-4o") is False
    assert p.supports_image_generation("") is False


def test_supports_image_generation_set_returns_sorted(patched_image_gen_cache):
    p = patched_image_gen_cache
    p._image_gen_models = {
        "gemini/gemini-2.5-flash-image",
        "dall-e-3",
        "gpt-image-1",
    }
    assert p.supports_image_generation_set() == [
        "dall-e-3",
        "gemini/gemini-2.5-flash-image",
        "gpt-image-1",
    ]


def test_set_is_independent_copy(patched_image_gen_cache):
    """Callers must not be able to mutate the cache via the returned list."""
    p = patched_image_gen_cache
    p._image_gen_models = {"gpt-image-1"}
    snapshot = p.supports_image_generation_set()
    snapshot.append("invalid")
    assert "invalid" not in p._image_gen_models
    assert p.supports_image_generation_set() == ["gpt-image-1"]
