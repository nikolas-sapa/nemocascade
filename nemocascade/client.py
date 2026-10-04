"""Nebius Token Factory chat client (OpenAI-compatible endpoint).

Zero third-party dependencies: everything goes through urllib against
https://api.tokenfactory.nebius.com/v1/ with Bearer auth.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"

# Keyword used to map a catalog model id to a cascade tier, in escalation order.
TIER_ORDER: tuple[str, ...] = ("nano", "super", "ultra")


class TokenFactoryError(RuntimeError):
    """Base error for Token Factory client failures."""


class APIError(TokenFactoryError):
    """The Token Factory endpoint returned a non-2xx HTTP status."""


@dataclass
class Tier:
    """One rung of the escalation ladder."""

    tier: str
    model: str
    price_in_per_1m: float | None = None
    price_out_per_1m: float | None = None

    def cost(self, tokens_in: int, tokens_out: int) -> float | None:
        if self.price_in_per_1m is None or self.price_out_per_1m is None:
            return None
        return (
            tokens_in * self.price_in_per_1m + tokens_out * self.price_out_per_1m
        ) / 1_000_000


def classify_tier(model_id: str) -> str | None:
    """Return 'nano' | 'super' | 'ultra' for Nemotron catalog ids, else None.

    Fast variants carry a '-fast' suffix; callers can filter on that separately.
    """
    lowered = model_id.lower()
    if "nemotron" not in lowered:
        return None
    for tier in TIER_ORDER:
        if tier in lowered:
            return tier
    return None


def is_fast_variant(model_id: str) -> bool:
    return model_id.lower().endswith("-fast")


class TokenFactoryClient:
    """Minimal OpenAI-compatible chat client for Nebius Token Factory."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ):
        self.base_url = (
            base_url or os.environ.get("NEBIUS_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY") or ""
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise APIError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TokenFactoryError(f"{method} {path} failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise TokenFactoryError(f"{method} {path} returned invalid JSON") from exc

    def list_models(self) -> list[dict]:
        """Return the raw catalog entries from GET /models."""
        body = self._request("GET", "/models")
        return body.get("data", [])

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> dict:
        """POST /chat/completions and return the full response body."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return self._request("POST", "/chat/completions", payload)


def discover_ladder(
    client: TokenFactoryClient,
    tiers: tuple[str, ...] = TIER_ORDER,
    prices: dict[str, tuple[float | None, float | None]] | None = None,
) -> list[Tier]:
    """Build a cost-ordered ladder from the live catalog.

    For each tier (nano -> super -> ultra) the first non-fast Nemotron model
    matching the tier keyword is used. Catalog ids are resolved at runtime so
    the ladder follows whatever Nemotron generations Token Factory serves.
    """
    prices = prices or {}
    catalog = client.list_models()
    by_tier: dict[str, list[str]] = {tier: [] for tier in tiers}
    for entry in catalog:
        model_id = entry.get("id", "")
        tier = classify_tier(model_id)
        if tier in by_tier and not is_fast_variant(model_id):
            by_tier[tier].append(model_id)

    ladder: list[Tier] = []
    for tier in tiers:
        if not by_tier[tier]:
            raise TokenFactoryError(
                f"No '{tier}' Nemotron model found in the catalog at {client.base_url}. "
                "Pass an explicit model via --config to override discovery."
            )
        price_in, price_out = prices.get(tier, (None, None))
        ladder.append(
            Tier(
                tier=tier,
                model=min(by_tier[tier]),
                price_in_per_1m=price_in,
                price_out_per_1m=price_out,
            )
        )
    return ladder


def resolve_ladder(client: TokenFactoryClient, config: dict | None) -> list[Tier]:
    """Resolve the escalation ladder from an optional explicit config.

    Config shape:
      {"ladder": ["nano", "super", "ultra"],
       "tiers": {"nano": {"model": null,                    // null -> discover
                          "price_in_per_1m": 0.04,
                          "price_out_per_1m": 0.16},
                 "super": {"model": "nvidia/nemotron-3-super-49b-instruct", ...}}}

    With no config the ladder is fully discovered from the live catalog.
    Tiers with an explicit model bypass discovery; tiers with "model": null
    (or no model) are resolved from GET /models. Prices are optional and only
    feed cost estimates in reports.
    """
    if not config:
        return discover_ladder(client)

    tiers_cfg = config.get("tiers") or {}
    order = config.get("ladder") or list(tiers_cfg)
    if not order:
        return discover_ladder(client)

    needs_catalog = [
        tier for tier in order if not (tiers_cfg.get(tier) or {}).get("model")
    ]
    catalog = client.list_models() if needs_catalog else []
    by_tier: dict[str, list[str]] = {tier: [] for tier in needs_catalog}
    for entry in catalog:
        model_id = entry.get("id", "")
        tier = classify_tier(model_id)
        if tier in by_tier and not is_fast_variant(model_id):
            by_tier[tier].append(model_id)

    ladder: list[Tier] = []
    for tier in order:
        entry = tiers_cfg.get(tier) or {}
        price_in = entry.get("price_in_per_1m")
        price_out = entry.get("price_out_per_1m")
        model = entry.get("model")
        if not model:
            if not by_tier.get(tier):
                raise TokenFactoryError(
                    f"No '{tier}' Nemotron model found in the catalog at "
                    f"{client.base_url}; set tiers.{tier}.model in the config."
                )
            model = min(by_tier[tier])
        ladder.append(
            Tier(tier=tier, model=model, price_in_per_1m=price_in, price_out_per_1m=price_out)
        )
    return ladder
