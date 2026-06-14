# this_file: vexy-lines-apy/tests/test_rename_vlm.py
"""Tests for vexy_lines_api.rename.vlm."""

from __future__ import annotations

import pytest

from vexy_lines_api.rename import vlm

_LLM_ENV = (
    "VEXY_LINES_LLM_API_URL",
    "VEXY_LINES_LLM_API_KEY",
    "VEXY_LINES_LLM_MODEL_VISION",
    "VEXY_LINES_VLM_MODEL",
)


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    """Isolate tests from the developer's real VEXY_LINES_* environment."""
    for var in _LLM_ENV:
        monkeypatch.delenv(var, raising=False)


def test_first_words_truncates_to_three():
    assert vlm.first_words("top left blue circle pattern") == "top left blue"


def test_first_words_strips_punctuation():
    assert vlm.first_words("  Top-left, blue.  ") == "Top-left blue"


def test_first_words_custom_count():
    assert vlm.first_words("one two three four", count=2) == "one two"


def test_to_slug_basic():
    assert vlm.to_slug("Top Left Blue") == "top-left-blue"


def test_to_slug_handles_unsafe_chars():
    slug = vlm.to_slug("face / hair: dark!")
    assert "/" not in slug
    assert ":" not in slug
    assert slug == "face-hair-dark"


def test_to_slug_empty_returns_unnamed():
    assert vlm.to_slug("") == "unnamed"
    assert vlm.to_slug("   ") == "unnamed"


def test_default_config_reads_env(monkeypatch):
    monkeypatch.setenv("VEXY_LINES_LLM_API_URL", "http://example/v1")
    monkeypatch.setenv("VEXY_LINES_LLM_API_KEY", "abc")
    monkeypatch.setenv("VEXY_LINES_LLM_MODEL_VISION", "vision-model")
    monkeypatch.setenv("VEXY_LINES_VLM_MODEL", "text-model")
    cfg = vlm.default_config()
    assert cfg.api_url == "http://example/v1"
    assert cfg.api_key == "abc"
    assert cfg.model_vision == "vision-model"
    assert cfg.model == "text-model"


def test_default_config_defaults_when_unset():
    cfg = vlm.default_config()
    assert cfg.api_url is None
    assert cfg.api_key == "not-needed"
    assert cfg.model_vision == cfg.model  # both default to the same model


def test_config_with_overrides_applies_non_empty():
    base = vlm.VLMConfig(api_url="http://a/v1", api_key="k", model_vision="v", model="t")
    cfg = vlm.config_with_overrides(
        base=base,
        llm_api_url="http://b/v1",
        llm_model_vision="v2",
    )
    assert cfg.api_url == "http://b/v1"
    assert cfg.model_vision == "v2"
    assert cfg.api_key == "k"  # unchanged
    assert cfg.model == "t"  # unchanged


def test_config_with_overrides_ignores_empty():
    base = vlm.VLMConfig(api_url="http://a/v1", model="t")
    cfg = vlm.config_with_overrides(base=base, llm_api_url="", llm_model=None)
    assert cfg.api_url == "http://a/v1"
    assert cfg.model == "t"


def test_describe_region_uses_vision_model_and_truncates(monkeypatch):
    captured = {}

    def fake_chat(_config, model, text, image_bytes):  # noqa: ARG001
        captured["model"] = model
        captured["image"] = image_bytes
        return "bottom right red strokes everywhere"

    monkeypatch.setattr(vlm, "_chat", fake_chat)
    cfg = vlm.VLMConfig(api_url="http://x/v1", model_vision="vis", model="txt")
    result = vlm.describe_region(b"PNGDATA", config=cfg)
    assert result == "bottom right red"
    assert captured["image"] == b"PNGDATA"
    assert captured["model"] == "vis"  # vision model used


def test_suggest_layer_name_uses_text_model(monkeypatch):
    captured = {}

    def fake_chat(_config, model, text, image):  # noqa: ARG001
        captured["model"] = model
        captured["image"] = image
        return "Background Sky"

    monkeypatch.setattr(vlm, "_chat", fake_chat)
    cfg = vlm.VLMConfig(api_url="http://x/v1", model_vision="vis", model="txt")
    assert vlm.suggest_layer_name(["blue top", "white clouds"], config=cfg) == "Background Sky"
    assert captured["model"] == "txt"  # text model used
    assert captured["image"] is None  # no image for text call


def test_suggest_layer_name_falls_back_on_error(monkeypatch):
    def boom(_config, _model, _text, _image):
        msg = "no endpoint"
        raise RuntimeError(msg)

    monkeypatch.setattr(vlm, "_chat", boom)
    cfg = vlm.VLMConfig(api_url="http://x/v1")
    assert vlm.suggest_layer_name(["dark hair", "pale skin"], config=cfg) == "dark hair pale"


def test_suggest_layer_name_empty_descriptions(monkeypatch):
    monkeypatch.setattr(vlm, "_chat", lambda _config, _model, _text, _image: "")
    cfg = vlm.VLMConfig(api_url="http://x/v1")
    assert vlm.suggest_layer_name([], config=cfg) == "various marks"
