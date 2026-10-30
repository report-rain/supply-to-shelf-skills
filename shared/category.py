"""category_map.json loading and category-key resolution."""

import re

from .errors import fail


def normalize_path(value):
    text = value.strip().lower()
    text = text.replace("|", " > ").replace(">", " > ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_category_map(path):
    import json

    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail(
            "找不到类目映射文件：{}".format(path),
            code=2,
            missing=["config/category_map.json"],
        )
    except (OSError, ValueError) as exc:
        fail(
            "类目映射文件无法解析：{}（{}）".format(path, exc),
            code=2,
            missing=["config/category_map.json"],
        )


def resolve_category(map_data, raw):
    """Return (category_key, source, note) for a user supplied category string."""
    categories = map_data.get("categories", {})
    aliases = map_data.get("aliases", {})

    if raw in categories:
        return raw, "explicit", None

    if raw in aliases and aliases[raw] in categories:
        target = aliases[raw]
        return (
            target,
            "alias",
            "类目旧键 {} 已按别名映射为 category_key={}".format(raw, target),
        )

    wanted = normalize_path(raw)
    longest = 0
    matches = []
    for key, entry in categories.items():
        for prefix in entry.get("platform_paths", []) or []:
            normalized = normalize_path(prefix)
            if wanted == normalized or wanted.startswith(normalized + " >"):
                if len(normalized) > longest:
                    longest = len(normalized)
                    matches = [(key, normalized)]
                elif len(normalized) == longest:
                    matches.append((key, normalized))

    distinct = {key for key, _ in matches}
    if len(distinct) > 1:
        fail(
            "类目路径存在歧义：{}".format(raw),
            code=2,
            missing=["category_key"],
        )
    if distinct:
        key = matches[0][0]
        return (
            key,
            "platform_path",
            "[WARN] 收到平台类目路径，已映射为 category_key={}；建议 brief 直接写 category_key".format(key),
        )

    return None, None, None
