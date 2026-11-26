"""Thin wrapper around the Google Gemini API (google-genai SDK).

* The API key is read from the GEMINI_API_KEY environment variable (.env file).
* The model is configurable through GEMINI_MODEL or the sidebar.
* Demo mode never calls the network; callers must check ``AIService.live``.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

try:  # The import is guarded so the UI can still start and explain what is missing.
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - depends on the user's environment
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]

DEFAULT_MODEL = "gemini-2.5-flash"
RETRYABLE_CODES = {429, 500, 502, 503, 504}


class AIServiceError(Exception):
    """Raised for any user-presentable problem talking to Gemini."""


def get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip()


def get_default_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def _friendly_error(exc: Exception | None) -> str:
    if exc is None:
        return "Unknown error while contacting Gemini."
    code = _status_code(exc)
    msg = str(exc)
    if code in (401, 403) or "API key" in msg or "API_KEY_INVALID" in msg:
        return "Gemini rejected the API key. Check GEMINI_API_KEY in your .env file."
    if code == 404:
        return "The selected Gemini model was not found. Change GEMINI_MODEL or the model in the sidebar."
    if code == 429:
        return "Gemini quota or rate limit reached. Wait a minute and retry, or switch model / use demo mode."
    if code in (500, 502, 503, 504):
        return "Gemini is temporarily overloaded or unavailable. Please retry shortly."
    if any(word in msg.lower() for word in ("connect", "timeout", "resolve", "network")):
        return "Could not reach the Gemini service. Check your internet connection."
    return "Gemini request failed. Check model configuration and service availability."


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse a JSON object from a model reply (tolerates code fences / chatter)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in the model reply.")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("Model reply was not a JSON object.")
    return data


class AIService:
    """Gemini client plus the demo-mode switch."""

    def __init__(self, model: str | None = None, demo_mode: bool = False,
                 api_key: str | None = None, request_guard=None) -> None:
        self.model = (model or get_default_model()).strip()
        self.demo_mode = demo_mode
        self._api_key = get_api_key() if api_key is None else api_key.strip()
        self._client: Any = None
        self._request_guard = request_guard

    # ------------------------------------------------------------------ status
    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    @property
    def sdk_available(self) -> bool:
        return genai is not None

    @property
    def live(self) -> bool:
        """True when real Gemini calls will be made."""
        return (not self.demo_mode) and self.has_key and self.sdk_available

    @property
    def mode_label(self) -> str:
        return f"Gemini ({self.model})" if self.live else "SIMULATED demo mode"

    # ------------------------------------------------------------------ internals
    def _get_client(self) -> Any:
        if genai is None:
            raise AIServiceError("The 'google-genai' package is not installed. Run: pip install google-genai")
        if not self._api_key:
            raise AIServiceError("GEMINI_API_KEY is missing. Add it to your .env file or use demo mode.")
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _call(self, contents: Any, system_instruction: str, temperature: float,
              json_mode: bool, max_retries: int = 3) -> str:
        if self._request_guard:
            try: self._request_guard()
            except (ValueError, PermissionError) as exc: raise AIServiceError(str(exc)) from exc
        client = self._get_client()
        kwargs: dict[str, Any] = {"system_instruction": system_instruction, "temperature": temperature}
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**kwargs)

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config)
                text = response.text
                if not text:
                    raise AIServiceError(
                        "Gemini returned an empty response (it may have been blocked by safety filters).")
                return text
            except AIServiceError:
                raise
            except Exception as exc:  # noqa: BLE001 - SDK raises many exception types
                last_exc = exc
                if _status_code(exc) in RETRYABLE_CODES and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                break
        raise AIServiceError(_friendly_error(last_exc)) from last_exc

    # ------------------------------------------------------------------ public API
    def generate_text(self, system_instruction: str, history: list[dict[str, str]],
                      user_message: str, temperature: float = 0.6) -> str:
        """Chat-style call. ``history`` items look like {"role": "user"|"assistant", "content": str}."""
        contents = []
        for item in history:
            role = "model" if item["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=item["content"])]))
        if contents and contents[0].role == "model":
            contents.insert(0, types.Content(role="user", parts=[types.Part.from_text(text="Hello.")]))
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))
        return self._call(contents, system_instruction, temperature, json_mode=False)

    def generate_json(self, system_instruction: str, prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        """Single-shot call that must return a JSON object (one automatic repair retry)."""
        last_error: Exception | None = None
        current_prompt = prompt
        for _ in range(2):
            text = self._call(current_prompt, system_instruction, temperature, json_mode=True)
            try:
                return parse_json_response(text)
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                current_prompt = prompt + "\n\nIMPORTANT: Reply with ONE valid JSON object only. No markdown, no commentary."
        raise AIServiceError(f"Gemini did not return valid JSON ({last_error}). Please try again.")
