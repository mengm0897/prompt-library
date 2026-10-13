"""Check a clean public copy with fictional examples and a saved prompt."""

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
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
        assert all(item["source"] == "内置虚构示例" for item in initial["prompts"])
        assert set(initial["categories"]) == {"写作", "学习", "工作", "生活"}
        created = request(base, "/api/prompts", "POST", {
            "title": "虚构测试提示词", "category": initial["categories"][0],
            "subcategory": "", "tags": ["测试"], "body": "请写一句问候语。",
            "note": "", "source": "测试", "status": "active",
        })
        assert created["id"] == 3
        assert (root / "prompts" / "0003.md").is_file()
        backup = request(base, "/api/backup")
        assert backup["format"] == "prompt-library-v1"
        assert len(backup["prompts"]) == 3
        assert request(base, "/api/backup", "POST", backup)["added"] == 0
        assert request(base, "/api/backup", "POST", {**backup, "format": "mengmeng-prompt-library-v1"})["added"] == 0
    finally:
        process.terminate()
        process.wait(timeout=5)

    process, base = start(root, port)
    try:
        restored = request(base, "/api/prompts")
        assert len(restored["prompts"]) == 3
        assert next(item for item in restored["prompts"] if item["id"] == 3)["body"] == "请写一句问候语。"
        assert (root / "data" / "prompts.sqlite3").is_file()
    finally:
        process.terminate()
        process.wait(timeout=5)

print("通过：公开代码与两条虚构示例可启动，新增后重启可读回 Markdown 和 SQLite 索引")
