"""Markdown files are canonical; SQLite is a searchable local index."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"
TAXONOMY = ROOT / "data" / "taxonomy.json"
DEFAULT = {
    "写作": ["改写"],
    "学习": ["理解概念"],
    "工作": ["整理信息"],
    "生活": [],
}
FIELDS = ("id", "title", "category", "subcategory", "status", "created_at", "updated_at", "import_key")
LEGACY_FIELDS = {"tags", "source", "note"}


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".prompt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def taxonomy():
    data = json.loads(TAXONOMY.read_text(encoding="utf-8")) if TAXONOMY.exists() else DEFAULT
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v) for k, v in data.items()):
        raise ValueError("分类词表格式不正确")
    return data


def check_selection(item, terms=None):
    terms = terms or taxonomy()
    category = item.get("category", "")
    subcategory = item.get("subcategory", "")
    if category not in terms:
        raise ValueError(f"未收录的大类：{category}；请先在分类管理中添加")
    if subcategory and subcategory not in terms[category]:
        raise ValueError(f"{category} 下未收录的子类：{subcategory}；请先在分类管理中添加")


def path_for(item_id):
    return PROMPTS / f"{int(item_id):04d}.md"


def render(item, terms=None):
    terms = terms or taxonomy()
    check_selection(item, terms)
    lines = ["---", "# 可选大类：" + " / ".join(terms)]
    for key in FIELDS:
        if key == "subcategory":
            lines.append("# 当前大类的可选子类：" + (" / ".join(terms[item["category"]]) or "暂无；可在网页分类管理中新增"))
        lines.append(f"{key}: {json.dumps(item.get(key, ''), ensure_ascii=False)}")
    return "\n".join(lines) + "\n---\n\n" + item["body"]


def parse(path):
    content = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n\r?\n", content, re.S)
    if not match:
        raise ValueError(f"{path.name}：缺少完整元数据区（---）")
    item = {}
    for line in match.group(1).splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, raw = line.partition(": ")
        if not sep or key not in (*FIELDS, *LEGACY_FIELDS) or key in item:
            raise ValueError(f"{path.name}：元数据行无效：{line[:80]}")
        try:
            item[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}：{key} 需要 JSON 值（中文请加双引号）") from exc
    missing = [key for key in FIELDS if key not in item]
    if missing:
        raise ValueError(f"{path.name}：缺少字段 {', '.join(missing)}")
    item["body"] = content[match.end():]
    if not isinstance(item["id"], int) or path != path_for(item["id"]):
        raise ValueError(f"{path.name}：文件名和 id 不一致")
    for key in LEGACY_FIELDS:
        item.pop(key, None)
    check_selection(item)
    return item


def digest(item):
    return hashlib.sha256(json.dumps({k: item.get(k) for k in (*FIELDS, "body")}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def refresh_hints(terms=None):
    terms = terms or taxonomy()
    for path in sorted(PROMPTS.glob("*.md")):
        item = parse(path)
        content = render(item, terms)
        if path.read_text(encoding="utf-8") != content:
            atomic_write(path, content)
