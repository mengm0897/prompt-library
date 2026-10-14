"""Check a clean public copy with fictional examples and a saved prompt."""

import json
import sqlite3
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SOURCE = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, path, method="GET", body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    with urlopen(Request(base + path, data=data, method=method,
                         headers={"Content-Type": "application/json"}), timeout=3) as response:
        return json.load(response)


def start(root, port):
    process = subprocess.Popen(
        [sys.executable, "app/server.py", "--port", str(port)], cwd=root,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        if process.poll() is not None:
            raise AssertionError(process.stderr.read())
        try:
            request(base, "/api/prompts")
            return process, base
        except URLError:
            time.sleep(0.1)
    process.terminate()
    raise AssertionError("Service did not start")


with tempfile.TemporaryDirectory(prefix="prompt-clean-start-") as directory:
    root = Path(directory)
    (root / "app" / "web").mkdir(parents=True)
    for name in ("server.py", "md_store.py"):
        shutil.copy2(SOURCE / "app" / name, root / "app" / name)
    for path in (SOURCE / "app" / "web").iterdir():
        if path.is_file():
            shutil.copy2(path, root / "app" / "web" / path.name)
    shutil.copytree(SOURCE / "examples", root / "examples")
    assert not (root / "data").exists() and not (root / "prompts").exists()

    port = free_port()
    process, base = start(root, port)
    try:
        initial = request(base, "/api/prompts")
        assert len(initial["prompts"]) == 2
        assert all(set(item).isdisjoint({"tags", "note", "source"}) for item in initial["prompts"])
        assert set(initial["categories"]) == {"写作", "学习", "工作", "生活"}
        created = request(base, "/api/prompts", "POST", {
            "title": "虚构测试提示词", "category": initial["categories"][0],
            "subcategory": "", "body": "请写一句问候语。", "status": "active",
        })
        assert created["id"] == 3
        assert (root / "prompts" / "0003.md").is_file()
        renamed = request(base, "/api/taxonomy", "PATCH", {
            "level": "category", "category": "工作", "name": "工作事务"})
        assert renamed["moved"] == 1
        assert request(base, "/api/prompts/1")["category"] == "工作事务"
        renamed_sub = request(base, "/api/taxonomy", "PATCH", {
            "level": "subcategory", "category": "工作事务",
            "subcategory": "整理信息", "name": "事项整理"})
        assert renamed_sub["moved"] == 1
        assert request(base, "/api/prompts/1")["subcategory"] == "事项整理"
        try:
            request(base, "/api/taxonomy", "DELETE", {
                "level": "subcategory", "category": "工作事务", "subcategory": "事项整理"})
            raise AssertionError("Used subcategory was deleted without migration")
        except HTTPError as error:
            assert error.code == 400
        deleted_sub = request(base, "/api/taxonomy", "DELETE", {
            "level": "subcategory", "category": "工作事务",
            "subcategory": "事项整理", "target_category": "工作事务", "target_subcategory": ""})
        assert deleted_sub["moved"] == 1
        deleted_category = request(base, "/api/taxonomy", "DELETE", {
            "level": "category", "category": "工作事务",
            "target_category": "生活", "target_subcategory": ""})
        assert deleted_category["moved"] == 1
        assert request(base, "/api/prompts/1")["category"] == "生活"
        assert "工作事务" not in request(base, "/api/taxonomy")
        assert "category: \"生活\"" in (root / "prompts" / "0001.md").read_text()
        backup = request(base, "/api/backup")
        assert backup["format"] == "prompt-library-v1"
        assert len(backup["prompts"]) == 3
        assert request(base, "/api/backup", "POST", backup)["added"] == 0
        assert request(base, "/api/backup", "POST", {**backup, "format": "mengmeng-prompt-library-v1"})["added"] == 0
    finally:
        process.terminate()
        process.wait(timeout=5)

    # An older local library can still start; obsolete metadata disappears from
    # both Markdown and SQLite while the prompt body remains intact.
    legacy_file = root / "prompts" / "0003.md"
    legacy_text = legacy_file.read_text(encoding="utf-8")
    legacy_file.write_text(legacy_text.replace('status: "active"',
        'tags: ["旧标签"]\nsource: "本机旧路径"\nnote: "旧说明"\nstatus: "active"'), encoding="utf-8")
    with sqlite3.connect(root / "data" / "prompts.sqlite3") as db:
        db.execute("ALTER TABLE prompts ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        db.execute("ALTER TABLE prompts ADD COLUMN source TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE prompts ADD COLUMN note TEXT NOT NULL DEFAULT ''")

    process, base = start(root, port)
    try:
        restored = request(base, "/api/prompts")
        assert len(restored["prompts"]) == 3
        assert next(item for item in restored["prompts"] if item["id"] == 3)["body"] == "请写一句问候语。"
        assert (root / "data" / "prompts.sqlite3").is_file()
        assert "旧标签" not in legacy_file.read_text(encoding="utf-8")
        with sqlite3.connect(root / "data" / "prompts.sqlite3") as db:
            assert "tags" not in {row[1] for row in db.execute("PRAGMA table_info(prompts)")}
        untouched = (root / "prompts" / "0001.md").read_bytes()
        assert request(base, "/api/prompts/3", "DELETE") == {"deleted": 3}
        assert not legacy_file.exists()
        assert (root / "prompts" / "0001.md").read_bytes() == untouched
        assert len(request(base, "/api/prompts")["prompts"]) == 2
        assert len(request(base, "/api/backup")["prompts"]) == 2
        for method in ("GET", "DELETE"):
            try:
                request(base, "/api/prompts/3", method)
                raise AssertionError("Deleted prompt was still available")
            except HTTPError as error:
                assert error.code == 404
    finally:
        process.terminate()
        process.wait(timeout=5)

    process, base = start(root, port)
    try:
        assert len(request(base, "/api/prompts")["prompts"]) == 2
        assert not legacy_file.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)

print("通过：首次启动、分类迁移、备份、永久删除与重启读回均正常")
