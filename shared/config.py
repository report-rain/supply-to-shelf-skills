"""Reading JSON data files without assuming a byte-order mark policy."""

import json

from .errors import fail


def load_json(path, missing_label):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        fail("找不到配置文件：{}".format(path), code=2, missing=[missing_label])
    except (OSError, ValueError) as exc:
        fail(
            "配置文件无法解析：{}（{}）".format(path, exc),
            code=2,
            missing=[missing_label],
        )
