"""Groq API client wrapper with rate-limiting and retry logic."""

import time
from typing import Any, Dict, List, Optional
import groq
from groq import Groq

from src.config import Config, load_config


class AIInvestigationError(Exception):
    """Exception raised when AI analysis fails or cannot proceed."""
    pass


class GroqClientWrapper:
    """Wrapper around Groq API enforcing rate limits, retries, and error handling."""

    def __init__(self, config: Optional[Config] = None, max_retries: int = 3):
        if config is None:
            config = load_config()
        self.config = config
        self.max_retries = max_retries
        self.client: Optional[Groq] = None
        self._init_client()

    def _init_client(self) -> None:
        if self.config.groq_api_key and not self.config.groq_api_key.startswith("mock_"):
            try:
                self.client = Groq(api_key=self.config.groq_api_key)
            except Exception as e:
                self.client = None
        else:
            self.client = None

    @property
    def is_configured(self) -> bool:
        """Return True if a live Groq client is configured."""
        return self.client is not None

    def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        temperature: float = 0.2,
    ) -> Any:
        """Call Groq chat completion with automatic exponential/provider backoff on rate limits."""
        if not self.is_configured:
            raise AIInvestigationError("Groq client is not configured with a valid API key.")

        retries = 0
        while retries <= self.max_retries:
            try:
                kwargs: Dict[str, Any] = {
                    "model": self.config.groq_model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                if tool_choice:
                    kwargs["tool_choice"] = tool_choice

                response = self.client.chat.completions.create(**kwargs)
                return response
            except groq.RateLimitError as rle:
                retries += 1
                if retries > self.max_retries:
                    raise AIInvestigationError(f"Groq rate limit exceeded after {self.max_retries} retries: {rle}")

                # Check if provider returned a specific retry-after duration
                retry_after = 2.0 * retries
                if hasattr(rle, "response") and rle.response and "retry-after" in rle.response.headers:
                    try:
                        retry_after = float(rle.response.headers["retry-after"])
                    except (ValueError, TypeError):
                        pass

                print(f"  [AI NOTICE] Rate limit hit. Waiting {retry_after:.1f}s before retry ({retries}/{self.max_retries})...")
                time.sleep(retry_after)
            except groq.APIConnectionError as ace:
                retries += 1
                if retries > self.max_retries:
                    raise AIInvestigationError(f"Groq API connection error: {ace}")
                time.sleep(1.0 * retries)
            except groq.APIStatusError as ase:
                raise AIInvestigationError(f"Groq API status error ({ase.status_code}): {ase.message}")
            except Exception as e:
                raise AIInvestigationError(f"Unexpected Groq API error: {e}")

