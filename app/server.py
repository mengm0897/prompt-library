#!/usr/bin/env python3
"""Local-only Prompt library. No third-party packages or network calls."""

import hashlib
import json
import mimetypes
import re
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
import md_store


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB = DATA / "prompts.sqlite3"
WEB = ROOT / "app" / "web"
MAX_BODY = 2_000_000
SYNC_LOCK = threading.RLock()


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect():
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS prompts (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
        subcategory TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]', body TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, import_key TEXT UNIQUE)""")
    if "subcategory" not in {x[1] for x in db.execute("PRAGMA table_info(prompts)")}:
        db.execute("ALTER TABLE prompts ADD COLUMN subcategory TEXT NOT NULL DEFAULT ''")
    db.commit()
    return db


def serialize(row):
    item = dict(row)
    item["tags"] = json.loads(item["tags"])
    return item


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("请输入有效的提示词内容")
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", ""))
    category = str(payload.get("category", next(iter(md_store.taxonomy()))))
    subcategory = str(payload.get("subcategory", "")).strip()
    if not title or len(title) > 180:
        raise ValueError("标题需要填写，且不能超过180字")
    if not body.strip() or len(body) > MAX_BODY:
        raise ValueError("正文需要填写，且不能超过200万字")
    md_store.check_selection({"category": category, "subcategory": subcategory})
    if len(subcategory) > 80:
        raise ValueError("子类不能超过80字")
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 20:
        raise ValueError("标签最多20个")
    tags = list(dict.fromkeys(str(t).strip()[:50] for t in tags if str(t).strip()))
    note = str(payload.get("note", ""))[:5000]
    source = str(payload.get("source", "手动新增"))[:500]
    status = str(payload.get("status", "active"))
    if status not in ("active", "reference", "archived"):
        raise ValueError("无效状态")
    return title, category, subcategory, json.dumps(tags, ensure_ascii=False), body, note, source, status


def ensure_taxonomy():
    """Create a default category list only for a new user."""
    if not md_store.TAXONOMY.exists():
        md_store.atomic_write(md_store.TAXONOMY, json.dumps(md_store.DEFAULT, ensure_ascii=False, indent=2) + "\n")


def install_examples_for_new_user():
    """Copy public examples once, without touching an existing user's data."""
    if DB.exists() or any(md_store.PROMPTS.glob("*.md")):
        return
    for example in sorted((ROOT / "examples").glob("*.md")):
        md_store.atomic_write(md_store.PROMPTS / example.name, example.read_text(encoding="utf-8"))


def sync_from_markdown():
    """Synchronize Markdown source files into the local SQLite search index."""
    with SYNC_LOCK, connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS md_state (id INTEGER PRIMARY KEY, digest TEXT NOT NULL)")
        for path in sorted(md_store.PROMPTS.glob("*.md")):
            item = md_store.parse(path)
            values = validate(item)
            prior = db.execute("SELECT * FROM prompts WHERE id=?", (item["id"],)).fetchone()
            baseline_row = db.execute("SELECT digest FROM md_state WHERE id=?", (item["id"],)).fetchone()
            file_hash = md_store.digest(item)
            if baseline_row and file_hash == baseline_row[0]:
                continue
            if prior:
                db_item = serialize(prior)
                if baseline_row and md_store.digest(db_item) != baseline_row[0] and md_store.digest(db_item) != file_hash:
                    raise ValueError(f"{path.name} 与网页索引均已修改，请先核对")
                db.execute("""UPDATE prompts SET title=?,category=?,subcategory=?,tags=?,body=?,note=?,source=?,status=?,created_at=?,updated_at=?,import_key=? WHERE id=?""",
                           (*values, item["created_at"], item["updated_at"], item["import_key"], item["id"]))
            else:
                db.execute("""INSERT INTO prompts (title,category,subcategory,tags,body,note,source,status,created_at,updated_at,import_key,id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (*values, item["created_at"], item["updated_at"], item["import_key"], item["id"]))
            db.execute("INSERT OR REPLACE INTO md_state VALUES (?,?)", (item["id"], file_hash))


def write_web_change(db, item):
    md_store.atomic_write(md_store.path_for(item["id"]), md_store.render(item))
    db.execute("CREATE TABLE IF NOT EXISTS md_state (id INTEGER PRIMARY KEY, digest TEXT NOT NULL)")
    db.execute("INSERT OR REPLACE INTO md_state VALUES (?,?)", (item["id"], md_store.digest(item)))


class Handler(BaseHTTPRequestHandler):
    def json(self, value, code=200):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def payload(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > MAX_BODY * 3:
            raise ValueError("上传内容为空或过大")
        return json.loads(self.rfile.read(size))

    def route(self):
        path = urlparse(self.path).path
        if path == "/api/taxonomy":
            return "taxonomy", None
        if path == "/api/prompts":
            return "collection", None
        if path == "/api/backup":
            return "backup", None
        m = re.fullmatch(r"/api/prompts/(\d+)", path)
        if m:
            return "item", int(m.group(1))
        return None, None

    def do_GET(self):
        route, item_id = self.route()
        if route == "taxonomy":
            return self.json(md_store.taxonomy())
        if route == "collection":
            try:
                sync_from_markdown()
            except Exception as exc:
                return self.json({"error": f"Markdown 同步失败：{exc}"}, 409)
            with connect() as db:
                rows = db.execute("SELECT * FROM prompts ORDER BY updated_at DESC, id DESC").fetchall()
            terms = md_store.taxonomy()
            return self.json({"categories": list(terms), "taxonomy": terms, "prompts": [serialize(x) for x in rows]})
        if route == "backup":
            try:
                sync_from_markdown()
            except Exception as exc:
                return self.json({"error": f"Markdown 同步失败：{exc}"}, 409)
            with connect() as db:
                rows = [serialize(x) for x in db.execute("SELECT * FROM prompts ORDER BY id")]
            data = json.dumps({"format": "prompt-library-v1", "exported_at": now(), "prompts": rows}, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="prompt-library-backup.json"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if route == "item":
            try:
                sync_from_markdown()
            except Exception as exc:
                return self.json({"error": f"Markdown 同步失败：{exc}"}, 409)
            with connect() as db:
                row = db.execute("SELECT * FROM prompts WHERE id=?", (item_id,)).fetchone()
            return self.json(serialize(row) if row else {"error": "未找到提示词"}, 200 if row else 404)
        path = urlparse(self.path).path
        if path.startswith("/attachments/"):
            filename = unquote(path[len("/attachments/"):])
            if not filename or filename != Path(filename).name:
                return self.send_error(404)
            attachment = ROOT / "图片和附件" / filename
            if not attachment.is_file():
                return self.send_error(404)
            content = attachment.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return self.wfile.write(content)
        target = {"/": "index.html", "/index.html": "index.html", "/style.css": "style.css", "/attachments.css": "attachments.css", "/taxonomy.css": "taxonomy.css", "/reader.css": "reader.css", "/markdown.js": "markdown.js", "/app.js": "app.js"}.get(path)
        if not target:
            return self.send_error(404)
        content = (WEB / target).read_bytes()
        mime = "text/html" if target.endswith("html") else "text/css" if target.endswith("css") else "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        route, _ = self.route()
        try:
            if route == "taxonomy":
                payload = self.payload()
                category = str(payload.get("category", "")).strip()
                subcategory = str(payload.get("subcategory", "")).strip()
                if not category or len(category) > 40 or any(ch in category for ch in "\r\n/\\"):
                    raise ValueError("大类名称需为1至40字，不能包含换行或斜杠")
                if len(subcategory) > 80 or any(ch in subcategory for ch in "\r\n/\\"):
                    raise ValueError("子类名称不能超过80字或包含换行、斜杠")
                with SYNC_LOCK:
                    sync_from_markdown()
                    terms = md_store.taxonomy()
                    if subcategory:
                        if category not in terms:
                            raise ValueError("请先添加大类，再添加子类")
                        if subcategory in terms[category]:
                            raise ValueError("这个子类已存在")
                        terms[category].append(subcategory)
                    else:
                        if category in terms:
                            raise ValueError("这个大类已存在")
                        terms[category] = []
                    md_store.atomic_write(md_store.TAXONOMY, json.dumps(terms, ensure_ascii=False, indent=2) + "\n")
                    md_store.refresh_hints(terms)
                return self.json(terms, 201)
            if route == "collection":
                payload = self.payload()
                with SYNC_LOCK:
                    sync_from_markdown()
                    values = validate(payload)
                    with connect() as db:
                        cur = db.execute("""INSERT INTO prompts
                            (title,category,subcategory,tags,body,note,source,status,created_at,updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""", (*values, now(), now()))
                        row = db.execute("SELECT * FROM prompts WHERE id=?", (cur.lastrowid,)).fetchone()
                        write_web_change(db, serialize(row))
                return self.json(serialize(row), 201)
            if route == "backup":
                payload = self.payload()
                if payload.get("format") not in ("prompt-library-v1", "mengmeng-prompt-library-v1") or not isinstance(payload.get("prompts"), list):
                    raise ValueError("这不是本工具导出的备份文件")
                rows = payload["prompts"]
                if len(rows) > 10000:
                    raise ValueError("备份条目过多")
                checked = [(validate(row), row.get("import_key")) for row in rows]
                added = 0
                with SYNC_LOCK:
                    sync_from_markdown()
                    with connect() as db:
                        changes = []
                        for values, key in checked:
                            if key and db.execute("SELECT 1 FROM prompts WHERE import_key=?", (str(key),)).fetchone():
                                continue
                            body_hash = hashlib.sha256(values[4].encode()).hexdigest()
                            if db.execute("SELECT 1 FROM prompts WHERE title=? AND body=?", (values[0], values[4])).fetchone():
                                continue
                            cur = db.execute("""INSERT INTO prompts
                                (title,category,subcategory,tags,body,note,source,status,created_at,updated_at,import_key)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (*values, now(), now(), str(key) if key else f"restore:{body_hash}"))
                            item = serialize(db.execute("SELECT * FROM prompts WHERE id=?", (cur.lastrowid,)).fetchone())
                            changes.append({"item": item})
                            added += 1
                        for change in changes:
                            write_web_change(db, change["item"])
                return self.json({"added": added})
        except (ValueError, TypeError, json.JSONDecodeError, sqlite3.IntegrityError) as exc:
            return self.json({"error": str(exc)}, 400)
        self.send_error(404)

    def do_PUT(self):
        route, item_id = self.route()
        if route != "item":
            return self.send_error(404)
        try:
            payload = self.payload()
            with SYNC_LOCK:
                sync_from_markdown()
                values = validate(payload)
                with connect() as db:
                    cur = db.execute("""UPDATE prompts SET title=?,category=?,subcategory=?,tags=?,body=?,note=?,source=?,status=?,updated_at=? WHERE id=?""", (*values, now(), item_id))
                    if not cur.rowcount:
                        return self.json({"error": "未找到提示词"}, 404)
                    row = db.execute("SELECT * FROM prompts WHERE id=?", (item_id,)).fetchone()
                    write_web_change(db, serialize(row))
            return self.json(serialize(row))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.json({"error": str(exc)}, 400)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ensure_taxonomy()
    install_examples_for_new_user()
    sync_from_markdown()
    with connect() as db:
        count = db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Prompt 库： http://127.0.0.1:{server.server_port}  （{count}条）", flush=True)
    server.serve_forever()
