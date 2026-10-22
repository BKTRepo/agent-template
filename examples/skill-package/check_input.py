"""演示资源：仅在调用方明确执行时检查输入；Skill 生成阶段不会执行。"""
import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="检查演示 JSON 的 requirement 字段。")
    parser.add_argument("input_file", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.input_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(json.dumps({"valid": False, "error": "输入文件无法读取或不是有效 UTF-8 JSON。"}, ensure_ascii=False))
        return 1
    valid = isinstance(data, dict) and isinstance(data.get("requirement"), str) and bool(data["requirement"].strip())
    print(json.dumps({"valid": valid, "error": "" if valid else "请提供非空 requirement 字符串。"}, ensure_ascii=False))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
