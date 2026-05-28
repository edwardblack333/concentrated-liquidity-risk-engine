from scripts.core.pool_config import list_available_pools, load_pool_config


def main() -> None:
    pool = load_pool_config("eth_usdc_005")

    print("Loaded pool config")
    print(f"pool_id: {pool['pool_id']}")
    print(f"display_name: {pool['display_name']}")
    print(f"pool_address: {pool['pool_address']}")
    print(f"fee_tier_bps: {pool['fee_tier_bps']}")
    print(f"bands: {pool['bands']}")
    print(f"price_symbol: {pool['price_source']['symbol']}")
    print(f"active_pools: {list_available_pools(active_only=True)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"Pool config loader test failed: {exc}") from exc


