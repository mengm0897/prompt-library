"""Run with: python3 tests/md_smoke.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import md_store

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    md_store.PROMPTS = root / "prompts"
    md_store.TAXONOMY = root / "taxonomy.json"
    terms = {"内容创作": ["PPT风格"], "生活助手": []}
    md_store.atomic_write(md_store.TAXONOMY, json.dumps(terms, ensure_ascii=False))
    item = {
        "id": 1, "title": "测试", "category": "内容创作", "subcategory": "PPT风格",
        "status": "active",
        "created_at": "2026-10-11", "updated_at": "2026-10-11", "import_key": None,
        "body": "# 很长的正文\n\n原样保留。\n",
    }
    path = md_store.path_for(1)
    md_store.atomic_write(path, md_store.render(item))
    assert md_store.parse(path) == item
    terms["内容创作"].append("小红书标题")
    md_store.atomic_write(md_store.TAXONOMY, json.dumps(terms, ensure_ascii=False))
    md_store.refresh_hints()
    assert "小红书标题" in path.read_text(encoding="utf-8")
    assert md_store.parse(path) == item
    try:
        md_store.check_selection({"category": "内容创作", "subcategory": "自创子类"})
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown subcategory was accepted")
print("Markdown round-trip, taxonomy hint refresh, and unknown-category rejection: OK")
