from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "pools.example.yaml"


def _parse_scalar(value: str) -> Any:
    value = value.strip()

    if value == "{}":
        return {}

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _strip_comment(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return ""
    return line.rstrip()


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    """
    Small fallback for this project's simple pools.example.yaml shape when PyYAML is
    unavailable in the local py launcher environment.
    """
    lines = []
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line)
        if line.strip():
            lines.append(line)

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return {}, index

        if _line_indent(lines[index]) != indent:
            raise ValueError(
                f"Unexpected indentation near line {index + 1}: {lines[index]!r}"
            )

        if lines[index].lstrip().startswith("- "):
            items = []
            while index < len(lines) and _line_indent(lines[index]) == indent:
                stripped = lines[index].strip()
                if not stripped.startswith("- "):
                    break

                item_text = stripped[2:].strip()
                index += 1

                if not item_text:
                    item, index = parse_block(index, indent + 2)
                    items.append(item)
                    continue

                if ":" in item_text:
                    key, raw_value = item_text.split(":", 1)
                    item = {}
                    if raw_value.strip():
                        item[key.strip()] = _parse_scalar(raw_value.strip())
                    else:
                        nested, index = parse_block(index, indent + 2)
                        item[key.strip()] = nested

                    if index < len(lines) and _line_indent(lines[index]) == indent + 2:
                        extra, index = parse_block(index, indent + 2)
                        if not isinstance(extra, dict):
                            raise ValueError(
                                f"Expected mapping after list item near line {index + 1}."
                            )
                        item.update(extra)

                    items.append(item)
                else:
                    items.append(_parse_scalar(item_text))

            return items, index

        mapping = {}
        while index < len(lines) and _line_indent(lines[index]) == indent:
            stripped = lines[index].strip()
            if stripped.startswith("- "):
                break
            if ":" not in stripped:
                raise ValueError(f"Expected key/value near line {index + 1}: {stripped!r}")

            key, raw_value = stripped.split(":", 1)
            index += 1

            if raw_value.strip():
                mapping[key.strip()] = _parse_scalar(raw_value.strip())
            else:
                value, index = parse_block(index, indent + 2)
                mapping[key.strip()] = value

        return mapping, index

    parsed, next_index = parse_block(0, 0)
    if next_index != len(lines):
        raise ValueError(f"Could not parse pools.example.yaml near line {next_index + 1}.")
    if not isinstance(parsed, dict):
        raise ValueError("pools.example.yaml must parse to a mapping/object.")
    return parsed


def _read_pool_config_file(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Pool config file not found: {path}. "
            "Expected config/pools.example.yaml relative to the project root."
        )

    text = path.read_text(encoding="utf-8")

    try:
        if yaml is not None:
            data = yaml.safe_load(text)
        else:
            data = _minimal_yaml_load(text)
    except Exception as exc:
        raise ValueError(f"Pool config file is malformed YAML: {path}. Details: {exc}") from exc

    if data is None:
        raise ValueError(f"Pool config file is empty: {path}")

    if not isinstance(data, dict):
        raise ValueError(
            f"Pool config root must be a mapping/object in {path}; got {type(data).__name__}."
        )

    pools = data.get("pools")
    if not isinstance(pools, list):
        raise ValueError(f"Pool config must contain a 'pools' list: {path}")

    for index, pool in enumerate(pools):
        if not isinstance(pool, dict):
            raise ValueError(
                f"Pool entry at index {index} must be a mapping/object in {path}; "
                f"got {type(pool).__name__}."
            )
        if not pool.get("pool_id"):
            raise ValueError(f"Pool entry at index {index} is missing required field 'pool_id'.")

    return data


def _pool_index(active_only: bool = False) -> dict[str, dict[str, Any]]:
    data = _read_pool_config_file()
    pools = {}

    for pool in data["pools"]:
        if active_only and not bool(pool.get("active", False)):
            continue

        pool_id = str(pool["pool_id"])
        if pool_id in pools:
            raise ValueError(f"Duplicate pool_id in pool config: {pool_id}")

        pools[pool_id] = pool

    return pools


def load_pool_config(pool_id: str) -> dict[str, Any]:
    pools = _pool_index(active_only=False)

    if pool_id not in pools:
        available = ", ".join(sorted(pools)) or "none"
        raise ValueError(f"Unknown pool_id '{pool_id}'. Available pool IDs: {available}")

    pool = dict(pools[pool_id])
    pool["pool_id"] = pool_id
    return pool


def list_available_pools(active_only: bool = False) -> list[str]:
    return sorted(_pool_index(active_only=active_only))



