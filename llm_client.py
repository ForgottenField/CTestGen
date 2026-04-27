#!/usr/bin/env python3
"""
llm_client.py — Unified LLM client for multiple providers.

Supported providers:
  - anthropic  (Claude models, e.g. claude-sonnet-4-6)
  - openai     (GPT models,   e.g. gpt-4o)

Configuration (config.ini, highest-priority fields shown first):

  [llm]
  provider = anthropic          # or: openai
  default_model = claude-sonnet-4-6

  [anthropic]
  api_key = sk-ant-...

  [openai]
  api_key = sk-...
  # base_url = https://api.openai.com/v1   # optional override

Environment variable overrides (take priority over config.ini):
  ANTHROPIC_API_KEY
  OPENAI_API_KEY

Usage:
  from llm_client import LLMClient
  client = LLMClient()                          # reads config.ini automatically
  client = LLMClient(provider="openai",         # explicit override
                     model="gpt-4o",
                     api_key="sk-...")

  text = client.chat(system="...", user="...")   # returns str
"""

import configparser
import os
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.ini"

# Default models per provider
_PROVIDER_DEFAULTS = {
    "anthropic": "claude-sonnet-4-6",
    "openai":    "gpt-4o",
}


def _read_config():
    """Return a ConfigParser loaded from config.ini (or empty if absent)."""
    cfg = configparser.ConfigParser()
    if _CONFIG_PATH.exists():
        cfg.read(_CONFIG_PATH)
    return cfg


def _cfg_get(cfg, section, key, fallback=""):
    return cfg.get(section, key, fallback=fallback).strip().strip('"').strip("'")


class LLMClient:
    """
    Provider-agnostic LLM chat client.

    Parameters
    ----------
    provider : str, optional
        "anthropic" or "openai".  Defaults to config.ini [llm] provider,
        falling back to "anthropic".
    model : str, optional
        Model ID.  Defaults to config.ini [llm] default_model, then
        the provider's built-in default.
    api_key : str, optional
        Explicit key.  Overrides env var and config.ini.
    base_url : str, optional
        Custom endpoint (useful for OpenAI-compatible proxies / local servers).
    max_tokens : int
        Maximum tokens in the response (default 1024).
    timeout : float
        HTTP timeout in seconds (default 60).
    """

    def __init__(
        self,
        *,
        provider=None,
        model=None,
        api_key=None,
        base_url=None,
        max_tokens=1024,
        timeout=60.0,
    ):
        cfg = _read_config()

        # --- provider ---
        self.provider = (
            provider
            or _cfg_get(cfg, "llm", "provider")
            or "anthropic"
        ).lower()

        if self.provider not in _PROVIDER_DEFAULTS:
            raise ValueError(
                f"Unsupported provider '{self.provider}'. "
                f"Choose from: {list(_PROVIDER_DEFAULTS)}"
            )

        # --- model ---
        self.model = (
            model
            or _cfg_get(cfg, "llm", "default_model")
            or _PROVIDER_DEFAULTS[self.provider]
        )

        # --- api_key ---
        if api_key:
            self._api_key = api_key
        else:
            self._api_key = self._resolve_api_key(cfg)

        # --- misc ---
        self._base_url  = base_url or _cfg_get(cfg, self.provider, "base_url") or None
        self.max_tokens = max_tokens
        self.timeout    = timeout
        self._client    = None  # lazy-init

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, *, user: str, system: str = "") -> str:
        """
        Send a chat request and return the assistant's text response.

        Parameters
        ----------
        user   : user message content
        system : system prompt (empty string = no system prompt)

        Returns
        -------
        str — the model's text reply

        Raises
        ------
        RuntimeError  on API errors or missing dependencies
        """
        client = self._get_client()
        return self._chat_mock(client, system, user)
        
        # if self.provider == "anthropic":
        #     return self._chat_anthropic(client, system, user)
        # if self.provider == "openai":
        #     return self._chat_openai(client, system, user)
        # raise RuntimeError(f"Provider '{self.provider}' not implemented")

    def __repr__(self):
        return (
            f"LLMClient(provider={self.provider!r}, model={self.model!r}, "
            f"max_tokens={self.max_tokens})"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_api_key(self, cfg):
        """
        Resolve API key for the current provider.
        Priority: env var > config.ini section key.
        """
        env_vars = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai":    "OPENAI_API_KEY",
        }
        env_key = os.environ.get(env_vars.get(self.provider, ""), "").strip()
        if env_key:
            return env_key

        cfg_key = _cfg_get(cfg, self.provider, "api_key")
        if cfg_key and cfg_key != "YOUR_API_KEY_HERE":
            return cfg_key

        return None

    def _get_client(self):
        """Lazy-initialise the underlying SDK client."""
        if self._client is not None:
            return self._client

        if not self._api_key:
            env_vars = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
            raise RuntimeError(
                f"No API key found for provider '{self.provider}'.\n"
                f"  Option 1: set the {env_vars.get(self.provider, 'API_KEY')} "
                f"environment variable.\n"
                f"  Option 2: edit {_CONFIG_PATH} and set "
                f"api_key under [{self.provider}]."
            )

        if self.provider == "anthropic":
            self._client = self._init_anthropic()
        elif self.provider == "openai":
            self._client = self._init_openai()

        return self._client

    def _init_anthropic(self):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        kwargs = {"api_key": self._api_key, "timeout": self.timeout}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return anthropic.Anthropic(**kwargs)

    def _init_openai(self):
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )
        kwargs = {"api_key": self._api_key, "timeout": self.timeout}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return openai.OpenAI(**kwargs)

    def _chat_anthropic(self, client, system, user):
        kwargs = {
            "model":      self.model,
            "max_tokens": self.max_tokens,
            "messages":   [{"role": "user", "content": user}],
        }
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        for block in msg.content:
            if hasattr(block, "text") and block.type == "text":
                return block.text.strip()
        return " ".join(
            b.text for b in msg.content if hasattr(b, "text")
        ).strip()

    def _chat_openai(self, client, system, user):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=messages,
        )
        return resp.choices[0].message.content.strip()
    
    def _chat_mock(self, client, system, user):
        from openai import OpenAI
        client = OpenAI(
            base_url="https://api2.aigcbest.top/v1",
            api_key='sk-Buy7r01fdQCnNKhZUdvMkqZmYlSj9hioSdGI8Sxe2tpqYNt9'
        )

        response = client.chat.completions.create(
          model="claude-sonnet-4-6",
          messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
          ]
        )
        return response.choices[0].message.content.strip()
