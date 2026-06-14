# this_file: vexy-lines-apy/src/vexy_lines_api/rename/vlm.py
"""LLM access for the renamer, plus name slugging.

The renamer makes two kinds of model call against a single OpenAI-compatible
``/v1`` endpoint:

* :func:`describe_region` — a *vision* call: given an inspection image, return a
  short telegraphic phrase for whatever the red rectangle frames. Uses the
  vision model.
* :func:`suggest_layer_name` — a *text* call: given the phrases of a layer's
  fills, return a short name for the layer. Uses the text model.

Configuration is read from the environment by :func:`default_config`, or passed
explicitly via :class:`VLMConfig`:

| Setting | Env variable | Override field |
|---|---|---|
| API base URL  | ``VEXY_LINES_LLM_API_URL``      | ``api_url`` |
| API key       | ``VEXY_LINES_LLM_API_KEY``      | ``api_key`` |
| Vision model  | ``VEXY_LINES_LLM_MODEL_VISION`` | ``model_vision`` |
| Text model    | ``VEXY_LINES_VLM_MODEL``        | ``model`` |

The ``openai``, ``pathvalidate`` and ``python-slugify`` dependencies are
imported lazily so importing this module never fails.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass

from loguru import logger

DESCRIBE_PROMPT = (
    "This image shows artwork with one element highlighted by a thick red "
    "rectangle. The rest of the artwork is faint. Describe telegraphically, in "
    "exactly 3 words, WHERE and WHAT is inside the red rectangle. Reply with "
    "only those 3 words, no punctuation, no explanation."
)

LAYER_PROMPT = (
    "A design layer contains these elements: {items}. Give a short name for "
    "this layer in 1 to 3 words. Reply with only the name, no punctuation."
)

_MAX_WORDS = 3
_DEFAULT_MODEL = "gemini-3.5-flash-low"


@dataclass
class VLMConfig:
    """Connection settings for the renamer's LLM endpoint.

    Attributes:
        api_url: Base URL of the OpenAI-compatible ``/v1`` endpoint. ``None``
            lets the ``openai`` client use its own default.
        api_key: API key for the endpoint. Local servers accept any value.
        model_vision: Model used for image description (:func:`describe_region`).
        model: Model used for text generation (:func:`suggest_layer_name`).
        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate per call.
        timeout: Per-request timeout in seconds.
    """

    api_url: str | None = None
    api_key: str = "not-needed"
    model_vision: str = _DEFAULT_MODEL
    model: str = _DEFAULT_MODEL
    temperature: float = 0.2
    max_tokens: int = 64
    timeout: float = 120.0


def default_config() -> VLMConfig:
    """Build a :class:`VLMConfig` from environment variables.

    Reads ``VEXY_LINES_LLM_API_URL``, ``VEXY_LINES_LLM_API_KEY``,
    ``VEXY_LINES_LLM_MODEL_VISION`` (vision) and ``VEXY_LINES_VLM_MODEL`` (text).
    Unset values fall back to the dataclass defaults.

    Returns:
        A populated :class:`VLMConfig`.
    """
    return VLMConfig(
        api_url=os.environ.get("VEXY_LINES_LLM_API_URL"),
        api_key=os.environ.get("VEXY_LINES_LLM_API_KEY") or "not-needed",
        model_vision=os.environ.get("VEXY_LINES_LLM_MODEL_VISION", _DEFAULT_MODEL),
        model=os.environ.get("VEXY_LINES_VLM_MODEL", _DEFAULT_MODEL),
    )


def config_with_overrides(
    *,
    base: VLMConfig | None = None,
    llm_api_url: str | None = None,
    llm_api_key: str | None = None,
    llm_model_vision: str | None = None,
    llm_model: str | None = None,
) -> VLMConfig:
    """Return *base* (or the env default) with any non-empty overrides applied.

    Shared by the CLI flags and GUI settings so both expose the same four knobs.

    Args:
        base: Starting config; :func:`default_config` when ``None``.
        llm_api_url: Override for ``api_url``.
        llm_api_key: Override for ``api_key``.
        llm_model_vision: Override for ``model_vision``.
        llm_model: Override for ``model``.

    Returns:
        A :class:`VLMConfig` with the overrides applied.
    """
    cfg = base or default_config()
    if llm_api_url:
        cfg.api_url = llm_api_url
    if llm_api_key:
        cfg.api_key = llm_api_key
    if llm_model_vision:
        cfg.model_vision = llm_model_vision
    if llm_model:
        cfg.model = llm_model
    return cfg


# ---------------------------------------------------------------------------
# Text post-processing
# ---------------------------------------------------------------------------


def first_words(text: str, count: int = _MAX_WORDS) -> str:
    """Return the first *count* words of *text*, stripped of stray punctuation."""
    cleaned = re.sub(r"[^\w\s-]", " ", text.strip())
    words = cleaned.split()
    return " ".join(words[:count])


def to_slug(text: str) -> str:
    """Convert a free-text description into a filesystem-safe slug.

    Uses ``pathvalidate.sanitize_filename`` then ``slugify`` (as specified in
    the feature brief). Falls back to a built-in slugifier when those optional
    packages are not installed, so this function always returns something
    usable.

    Args:
        text: Free-text name or description.

    Returns:
        A lower-case, hyphen-separated slug. ``"unnamed"`` if *text* is empty
        once sanitised.
    """
    text = (text or "").strip()
    if not text:
        return "unnamed"

    try:
        from pathvalidate import sanitize_filename  # noqa: PLC0415
        from slugify import slugify  # noqa: PLC0415

        slug = slugify(sanitize_filename(text))
    except ImportError:
        logger.debug("pathvalidate/slugify not installed; using fallback slugifier")
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

    return slug or "unnamed"


# ---------------------------------------------------------------------------
# OpenAI-compatible chat
# ---------------------------------------------------------------------------


def _data_uri(image_bytes: bytes, mime: str = "image/png") -> str:
    """Encode image bytes as a base64 ``data:`` URI for chat messages."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _chat(config: VLMConfig, model: str, text: str, image_bytes: bytes | None) -> str:
    """Run one OpenAI-compatible chat completion, optionally with an image.

    Raises:
        RuntimeError: If the ``openai`` package is not installed.
    """
    try:
        from openai import OpenAI  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised via fallback path
        msg = "The 'openai' package is required for AI rename. Install vexy-lines-apy[ai]."
        raise RuntimeError(msg) from exc

    client = OpenAI(base_url=config.api_url, api_key=config.api_key, timeout=config.timeout)

    content: list[dict[str, object]] = [{"type": "text", "text": text}]
    if image_bytes is not None:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(image_bytes)}})

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],  # type: ignore[arg-type]
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def describe_region(
    image_bytes: bytes,
    *,
    config: VLMConfig | None = None,
    prompt: str = DESCRIBE_PROMPT,
) -> str:
    """Describe what the red rectangle frames in an inspection image.

    Uses the vision model (:attr:`VLMConfig.model_vision`).

    Args:
        image_bytes: PNG bytes of the inspection image.
        config: LLM connection settings; :func:`default_config` when ``None``.
        prompt: Instruction sent to the model.

    Returns:
        A short telegraphic phrase (at most 3 words), or ``""`` if the model
        returned nothing usable.
    """
    config = config or default_config()
    raw = _chat(config, config.model_vision, prompt, image_bytes)
    description = first_words(raw)
    logger.debug("VLM described region as {!r} (raw {!r})", description, raw)
    return description


def suggest_layer_name(
    fill_descriptions: list[str],
    *,
    config: VLMConfig | None = None,
    prompt: str = LAYER_PROMPT,
) -> str:
    """Suggest a layer name from its fills' descriptions.

    Uses the text model (:attr:`VLMConfig.model`).

    Args:
        fill_descriptions: Per-fill descriptions for one layer.
        config: LLM connection settings; :func:`default_config` when ``None``.
        prompt: Instruction template containing an ``{items}`` placeholder.

    Returns:
        A short layer name (at most 3 words). Falls back to the joined
        descriptions when the model is unavailable or returns nothing.
    """
    items = ", ".join(d for d in fill_descriptions if d) or "various marks"
    config = config or default_config()
    try:
        raw = _chat(config, config.model, prompt.format(items=items), None)
    except Exception as exc:
        logger.warning("Layer-name suggestion failed ({}); falling back to fills", exc)
        raw = items
    name = first_words(raw)
    return name or first_words(items)
