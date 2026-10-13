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
    old_columns = {x[1] for x in db.execute("PRAGMA table_info(prompts)")}
    if old_columns and {"tags", "note", "source"} & old_columns:
        db.execute("""CREATE TABLE prompts_new (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
            subcategory TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, import_key TEXT UNIQUE)""")
        db.execute("""INSERT INTO prompts_new
            (id,title,category,subcategory,body,status,created_at,updated_at,import_key)
            SELECT id,title,category,subcategory,body,status,created_at,updated_at,import_key FROM prompts""")
        db.execute("DROP TABLE prompts")
        db.execute("ALTER TABLE prompts_new RENAME TO prompts")
        db.execute("CREATE TABLE IF NOT EXISTS md_state (id INTEGER PRIMARY KEY, digest TEXT NOT NULL)")
        db.execute("DELETE FROM md_state")
    db.execute("""CREATE TABLE IF NOT EXISTS prompts (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
        subcategory TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, import_key TEXT UNIQUE)""")
    db.commit()
    return db


def serialize(row):
    return dict(row)


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
    status = str(payload.get("status", "active"))
    if status not in ("active", "reference", "archived"):
        raise ValueError("无效状态")
    return title, category, subcategory, body, status


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
                canonical = md_store.render(item)
                if path.read_text(encoding="utf-8") != canonical:
                    md_store.atomic_write(path, canonical)
                continue
            if prior:
                db_item = serialize(prior)
                if baseline_row and md_store.digest(db_item) != baseline_row[0] and md_store.digest(db_item) != file_hash:
                    raise ValueError(f"{path.name} 与网页索引均已修改，请先核对")
                db.execute("""UPDATE prompts SET title=?,category=?,subcategory=?,body=?,status=?,created_at=?,updated_at=?,import_key=? WHERE id=?""",
                           (*values, item["created_at"], item["updated_at"], item["import_key"], item["id"]))
            else:
                db.execute("""INSERT INTO prompts (title,category,subcategory,body,status,created_at,updated_at,import_key,id)
                           VALUES (?,?,?,?,?,?,?,?,?)""", (*values, item["created_at"], item["updated_at"], item["import_key"], item["id"]))
            db.execute("INSERT OR REPLACE INTO md_state VALUES (?,?)", (item["id"], file_hash))
            canonical = md_store.render(item)
            if path.read_text(encoding="utf-8") != canonical:
                md_store.atomic_write(path, canonical)


def write_web_change(db, item):
    md_store.atomic_write(md_store.path_for(item["id"]), md_store.render(item))
    db.execute("CREATE TABLE IF NOT EXISTS md_state (id INTEGER PRIMARY KEY, digest TEXT NOT NULL)")
    db.execute("INSERT OR REPLACE INTO md_state VALUES (?,?)", (item["id"], md_store.digest(item)))


def category_name(value, limit, label):
    name = str(value or "").strip()
    if not name or len(name) > limit or any(ch in name for ch in "\r\n/\\"):
        raise ValueError(f"{label}名称需为1至{limit}字，不能包含换行或斜杠")
    return name


def change_taxonomy(payload, action):
    """Change the vocabulary and every affected Markdown/SQLite record together."""
    if not isinstance(payload, dict):
        raise ValueError("分类操作内容无效")
    level = payload.get("level")
    if level not in ("category", "subcategory"):
        raise ValueError("请选择大类或子类")
    with SYNC_LOCK:
        sync_from_markdown()
        terms = md_store.taxonomy()
        category = category_name(payload.get("category"), 40, "大类")
        if category not in terms:
            raise ValueError("原大类不存在，请刷新页面")
        subcategory = ""
        if level == "subcategory":
            subcategory = category_name(payload.get("subcategory"), 80, "子类")
            if subcategory not in terms[category]:
                raise ValueError("原子类不存在，请刷新页面")
        target_category = target_subcategory = ""
        if action == "rename":
            name = category_name(payload.get("name"), 40 if level == "category" else 80, "新分类")
            if level == "category":
                if name in terms:
                    raise ValueError("这个大类已存在")
                terms = {name if key == category else key: subs for key, subs in terms.items()}
            else:
                if name in terms[category]:
                    raise ValueError("这个子类已存在")
                terms[category] = [name if value == subcategory else value for value in terms[category]]
        elif action == "delete":
            if level == "category" and len(terms) == 1:
                raise ValueError("至少保留一个大类")
            target_category = str(payload.get("target_category", "")).strip()
            target_subcategory = str(payload.get("target_subcategory", "")).strip()
            if target_category and (target_category not in terms or target_category == category and level == "category"):
                raise ValueError("迁移目标大类无效")
            if target_subcategory and (not target_category or target_subcategory not in terms[target_category]):
                raise ValueError("迁移目标子类无效")
            if level == "subcategory" and target_category and target_category != category:
                raise ValueError("删除子类时只能迁到同一大类")
            if level == "subcategory" and target_subcategory == subcategory:
                raise ValueError("不能迁移到要删除的子类")
        else:
            raise ValueError("分类操作无效")

        paths = sorted(md_store.PROMPTS.glob("*.md"))
        items = [(path, md_store.parse(path)) for path in paths]
        affected = [(path, item) for path, item in items if item["category"] == category and (level == "category" or item["subcategory"] == subcategory)]
        if action == "delete" and affected and not target_category:
            raise ValueError(f"有 {len(affected)} 条提示词使用此分类，请先选择迁移目标")
        if action == "delete":
            if level == "category":
                del terms[category]
            else:
                terms[category].remove(subcategory)

        original_taxonomy = md_store.TAXONOMY.read_text(encoding="utf-8")
        original_files = {path: path.read_text(encoding="utf-8") for path, _ in items}
        changed = []
        for path, item in items:
            next_item = item.copy()
            if (path, item) in affected:
                if action == "rename":
                    if level == "category":
                        next_item["category"] = name
                    else:
                        next_item["subcategory"] = name
                else:
                    next_item["category"] = target_category
                    next_item["subcategory"] = target_subcategory
                next_item["updated_at"] = now()
                changed.append(next_item)
            item["_next"] = next_item
        try:
            with connect() as db:
                for path, item in items:
                    new_content = md_store.render(item["_next"], terms)
                    if original_files[path] != new_content:
                        md_store.atomic_write(path, new_content)
                md_store.atomic_write(md_store.TAXONOMY, json.dumps(terms, ensure_ascii=False, indent=2) + "\n")
                for item in changed:
                    db.execute("UPDATE prompts SET category=?,subcategory=?,updated_at=? WHERE id=?",
                               (item["category"], item["subcategory"], item["updated_at"], item["id"]))
                    db.execute("INSERT OR REPLACE INTO md_state VALUES (?,?)", (item["id"], md_store.digest(item)))
        except Exception:
            for path, content in original_files.items():
                if path.read_text(encoding="utf-8") != content:
                    md_store.atomic_write(path, content)
            md_store.atomic_write(md_store.TAXONOMY, original_taxonomy)
            raise
        return {"taxonomy": terms, "moved": len(affected)}


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
                category = category_name(payload.get("category"), 40, "大类")
                subcategory = str(payload.get("subcategory", "")).strip()
                if subcategory:
                    subcategory = category_name(subcategory, 80, "子类")
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
                            (title,category,subcategory,body,status,created_at,updated_at)
                            VALUES (?,?,?,?,?,?,?)""", (*values, now(), now()))
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
                            body_hash = hashlib.sha256(values[3].encode()).hexdigest()
                            if db.execute("SELECT 1 FROM prompts WHERE title=? AND body=?", (values[0], values[3])).fetchone():
                                continue
                            cur = db.execute("""INSERT INTO prompts
                                (title,category,subcategory,body,status,created_at,updated_at,import_key)
                                VALUES (?,?,?,?,?,?,?,?)""", (*values, now(), now(), str(key) if key else f"restore:{body_hash}"))
                            item = serialize(db.execute("SELECT * FROM prompts WHERE id=?", (cur.lastrowid,)).fetchone())
                            changes.append({"item": item})
                            added += 1
                        for change in changes:
                            write_web_change(db, change["item"])
                return self.json({"added": added})
        except (ValueError, TypeError, json.JSONDecodeError, sqlite3.IntegrityError) as exc:
            return self.json({"error": str(exc)}, 400)
        self.send_error(404)

    def do_PATCH(self):
        route, _ = self.route()
        if route != "taxonomy":
            return self.send_error(404)
        try:
            return self.json(change_taxonomy(self.payload(), "rename"))
        except (ValueError, TypeError, json.JSONDecodeError, sqlite3.Error) as exc:
            return self.json({"error": str(exc)}, 400)

    def do_DELETE(self):
        route, _ = self.route()
        if route != "taxonomy":
            return self.send_error(404)
        try:
            return self.json(change_taxonomy(self.payload(), "delete"))
        except (ValueError, TypeError, json.JSONDecodeError, sqlite3.Error) as exc:
            return self.json({"error": str(exc)}, 400)

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
                    cur = db.execute("""UPDATE prompts SET title=?,category=?,subcategory=?,body=?,status=?,updated_at=? WHERE id=?""", (*values, now(), item_id))
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
