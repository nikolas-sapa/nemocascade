import pytest

from nemocascade.client import (
    APIError,
    Tier,
    TokenFactoryClient,
    TokenFactoryError,
    classify_tier,
    discover_ladder,
    is_fast_variant,
    resolve_ladder,
)


def test_classify_tier():
    assert classify_tier("nvidia/nemotron-3-nano-4b-instruct") == "nano"
    assert classify_tier("nvidia/nemotron-3-super-49b-instruct") == "super"
    assert classify_tier("nvidia/nemotron-3-ultra-253b-instruct") == "ultra"
    assert classify_tier("deepseek-ai/DeepSeek-R1-0528") is None
    assert classify_tier("nvidia/other-model") is None


def test_is_fast_variant():
    assert is_fast_variant("nvidia/nemotron-3-nano-4b-instruct-fast")
    assert not is_fast_variant("nvidia/nemotron-3-nano-4b-instruct")


def test_tier_cost():
    tier = Tier(tier="nano", model="m", price_in_per_1m=0.04, price_out_per_1m=0.16)
    assert tier.cost(1_000_000, 1_000_000) == pytest.approx(0.20)
    assert Tier(tier="nano", model="m").cost(10, 10) is None


def test_list_models_requires_auth(mock_base_url):
    base, _state = mock_base_url
    client = TokenFactoryClient(base_url=f"{base}/v1", api_key="")
    with pytest.raises(APIError):
        client.list_models()


def test_list_models(mock_base_url):
    base, _state = mock_base_url
    client = TokenFactoryClient(base_url=f"{base}/v1", api_key="test-key")
    models = client.list_models()
    assert len(models) == 5
    assert any(m["id"].endswith("-fast") for m in models)
    assert any("nemotron" not in m["id"] for m in models)


def test_discover_ladder_filters_catalog(mock_base_url):
    base, _state = mock_base_url
    client = TokenFactoryClient(base_url=f"{base}/v1", api_key="test-key")
    ladder = discover_ladder(client, prices={"nano": (0.04, 0.16)})
    assert [t.tier for t in ladder] == ["nano", "super", "ultra"]
    assert ladder[0].model == "nvidia/nemotron-3-nano-4b-instruct"  # -fast filtered
    assert ladder[1].model == "nvidia/nemotron-3-super-49b-instruct"
    assert ladder[2].model == "nvidia/nemotron-3-ultra-253b-instruct"
    assert ladder[0].price_in_per_1m == 0.04
    assert ladder[1].price_in_per_1m is None


def test_discover_ladder_missing_tier_raises():
    class EmptyCatalog(TokenFactoryClient):
        def list_models(self):
            return [{"id": "deepseek-ai/DeepSeek-R1-0528"}]

    with pytest.raises(TokenFactoryError):
        discover_ladder(EmptyCatalog(base_url="http://127.0.0.1:1", api_key="k"))


def test_resolve_ladder_mixed_explicit_and_discovery(mock_base_url):
    base, _state = mock_base_url
    client = TokenFactoryClient(base_url=f"{base}/v1", api_key="test-key")
    config = {
        "ladder": ["nano", "ultra"],
        "tiers": {
            "nano": {"model": "nvidia/nemotron-3-nano-4b-instruct-fast",
                     "price_in_per_1m": 0.01, "price_out_per_1m": 0.02},
            "ultra": {"model": None, "price_in_per_1m": 2.0, "price_out_per_1m": 8.0},
        },
    }
    ladder = resolve_ladder(client, config)
    assert ladder[0].model == "nvidia/nemotron-3-nano-4b-instruct-fast"  # explicit wins
    assert ladder[1].model == "nvidia/nemotron-3-ultra-253b-instruct"  # discovered
    assert ladder[1].price_out_per_1m == 8.0


def test_resolve_ladder_no_config_discovers(mock_base_url):
    base, _state = mock_base_url
    client = TokenFactoryClient(base_url=f"{base}/v1", api_key="test-key")
    ladder = resolve_ladder(client, None)
    assert len(ladder) == 3


def test_chat_round_trip(mock_base_url):
    base, state = mock_base_url
    client = TokenFactoryClient(base_url=f"{base}/v1", api_key="test-key")
    response = client.chat("nvidia/nemotron-3-nano-4b-instruct", [
        {"role": "user", "content": "keyword total_value please"}
    ])
    assert response["choices"][0]["message"]["content"].startswith("```python")
    assert response["usage"]["prompt_tokens"] == 240
    assert state.chat_calls[0]["model"].endswith("nano-4b-instruct")
