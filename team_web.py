from __future__ import annotations

import json
import os
import queue
import secrets
import sqlite3
import subprocess
import threading
import uuid
import re
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from conf import BASE_DIR


APP_DIR = Path(BASE_DIR)
DATA_DIR = Path(os.getenv("SAU_TEAM_DATA_DIR", APP_DIR / "team_data")).resolve()
DB_PATH = DATA_DIR / "team.db"
MEDIA_DIR = DATA_DIR / "media"
FRONTEND_DIR = APP_DIR / "sau_frontend" / "dist"
ALLOWED_PLATFORMS = {"douyin", "kuaishou", "xiaohongshu", "bilibili", "tencent", "youtube"}
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
MAX_UPLOAD = int(os.getenv("SAU_MAX_UPLOAD_MB", "2048")) * 1024 * 1024

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.getenv("SAU_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_UPLOAD,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SAU_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)

job_queue: queue.Queue[int] = queue.Queue()
login_processes: dict[int, subprocess.Popen] = {}
process_lock = threading.Lock()
analysis_lock = threading.Lock()
whisper_model = None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              display_name TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('admin','operator')),
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS platform_accounts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              platform TEXT NOT NULL,
              account_name TEXT NOT NULL,
              display_name TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'not_logged_in',
              created_by INTEGER NOT NULL REFERENCES users(id),
              created_at TEXT NOT NULL,
              UNIQUE(platform, account_name)
            );
            CREATE TABLE IF NOT EXISTS user_account_access (
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              account_id INTEGER NOT NULL REFERENCES platform_accounts(id) ON DELETE CASCADE,
              PRIMARY KEY(user_id, account_id)
            );
            CREATE TABLE IF NOT EXISTS materials (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              original_name TEXT NOT NULL,
              stored_name TEXT NOT NULL UNIQUE,
              size_bytes INTEGER NOT NULL,
              uploaded_by INTEGER NOT NULL REFERENCES users(id),
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              material_id INTEGER NOT NULL REFERENCES materials(id),
              title TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              tags TEXT NOT NULL DEFAULT '',
              schedule_at TEXT,
              status TEXT NOT NULL DEFAULT 'queued',
              created_by INTEGER NOT NULL REFERENCES users(id),
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS job_targets (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              account_id INTEGER NOT NULL REFERENCES platform_accounts(id),
              status TEXT NOT NULL DEFAULT 'queued',
              output TEXT NOT NULL DEFAULT '',
              started_at TEXT,
              finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER REFERENCES users(id),
              action TEXT NOT NULL,
              detail TEXT NOT NULL DEFAULT '',
              ip TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            """
        )
        material_columns = {row["name"] for row in conn.execute("PRAGMA table_info(materials)").fetchall()}
        for name in ("transcript", "analysis_title", "analysis_description", "analysis_tags"):
            if name not in material_columns:
                conn.execute(f"ALTER TABLE materials ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            password = os.getenv("SAU_ADMIN_PASSWORD")
            if not password:
                password = secrets.token_urlsafe(14)
                (DATA_DIR / "initial-admin-password.txt").write_text(password, encoding="utf-8")
                os.chmod(DATA_DIR / "initial-admin-password.txt", 0o600)
            conn.execute(
                "INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                ("admin", "系统管理员", generate_password_hash(password), "admin", utcnow()),
            )


def audit(action: str, detail: str = "", user_id: int | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO audit_logs(user_id,action,detail,ip,created_at) VALUES(?,?,?,?,?)",
            (user_id or session.get("user_id"), action, detail[:1000], request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0], utcnow()),
        )


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as conn:
        return conn.execute("SELECT id,username,display_name,role,active FROM users WHERE id=?", (user_id,)).fetchone()


def auth_required(admin: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user or not user["active"]:
                return jsonify({"message": "请先登录"}), 401
            if admin and user["role"] != "admin":
                return jsonify({"message": "需要管理员权限"}), 403
            if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("X-CSRF-Token") != session.get("csrf"):
                return jsonify({"message": "安全令牌无效，请刷新页面"}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def row_dict(row):
    return dict(row) if row else None


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=?", (str(data.get("username", "")).strip(),)).fetchone()
    if not user or not user["active"] or not check_password_hash(user["password_hash"], str(data.get("password", ""))):
        return jsonify({"message": "用户名或密码错误"}), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["csrf"] = secrets.token_urlsafe(24)
    audit("login", user_id=user["id"])
    return jsonify({"user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"], "role": user["role"]}, "csrf": session["csrf"]})


@app.post("/api/auth/logout")
@auth_required()
def logout():
    audit("logout")
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/auth/me")
@auth_required()
def me():
    user = current_user()
    return jsonify({"user": row_dict(user), "csrf": session["csrf"]})


@app.get("/api/dashboard")
@auth_required()
def dashboard():
    user = current_user()
    account_filter = "" if user["role"] == "admin" else " WHERE id IN (SELECT account_id FROM user_account_access WHERE user_id=?)"
    params = () if user["role"] == "admin" else (user["id"],)
    with db() as conn:
        accounts = conn.execute(f"SELECT COUNT(*) n FROM platform_accounts{account_filter}", params).fetchone()["n"]
        materials = conn.execute("SELECT COUNT(*) n FROM materials").fetchone()["n"]
        jobs = conn.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
        success = conn.execute("SELECT COUNT(*) n FROM job_targets WHERE status='success'").fetchone()["n"]
    return jsonify({"accounts": accounts, "materials": materials, "jobs": jobs, "success": success})


@app.get("/api/users")
@auth_required(admin=True)
def users_list():
    with db() as conn:
        rows = conn.execute("SELECT id,username,display_name,role,active,created_at FROM users ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/users")
@auth_required(admin=True)
def users_create():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or len(password) < 10:
        return jsonify({"message": "用户名不能为空，密码至少10位"}), 400
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                (username, str(data.get("display_name") or username).strip(), generate_password_hash(password), "admin" if data.get("role") == "admin" else "operator", utcnow()),
            )
        audit("user.create", username)
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"message": "用户名已存在"}), 409


@app.patch("/api/users/<int:user_id>")
@auth_required(admin=True)
def users_update(user_id):
    data = request.get_json(silent=True) or {}
    with db() as conn:
        target = conn.execute("SELECT id,role,active FROM users WHERE id=?", (user_id,)).fetchone()
        if not target: return jsonify({"message": "员工不存在"}), 404
        next_role = "admin" if data.get("role") == "admin" else (target["role"] if "role" not in data else "operator")
        next_active = (1 if data.get("active") else 0) if "active" in data else target["active"]
        if target["role"] == "admin" and target["active"] and (next_role != "admin" or not next_active):
            active_admins = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if active_admins <= 1:
                return jsonify({"message": "系统至少需要保留一名启用中的管理员"}), 409
    fields, values = [], []
    for key in ("display_name", "role", "active"):
        if key in data:
            value = data[key]
            if key == "role": value = "admin" if value == "admin" else "operator"
            if key == "active": value = 1 if value else 0
            fields.append(f"{key}=?"); values.append(value)
    if data.get("password"):
        if len(str(data["password"])) < 10: return jsonify({"message": "密码至少10位"}), 400
        fields.append("password_hash=?"); values.append(generate_password_hash(str(data["password"])))
    if fields:
        values.append(user_id)
        with db() as conn: conn.execute(f"UPDATE users SET {','.join(fields)} WHERE id=?", values)
        audit("user.update", str(user_id))
    return jsonify({"ok": True})


def account_visible_sql(user):
    if user["role"] == "admin": return "", ()
    return " WHERE a.id IN (SELECT account_id FROM user_account_access WHERE user_id=?)", (user["id"],)


@app.get("/api/accounts")
@auth_required()
def accounts_list():
    user = current_user(); where, params = account_visible_sql(user)
    with db() as conn:
        rows = conn.execute(f"SELECT a.* FROM platform_accounts a{where} ORDER BY a.id DESC", params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/accounts")
@auth_required(admin=True)
def accounts_create():
    data = request.get_json(silent=True) or {}; platform = str(data.get("platform", ""))
    display_name = str(data.get("display_name", "")).strip()
    account_name = secure_filename(str(data.get("account_name", "")).strip()) or f"account_{uuid.uuid4().hex[:10]}"
    if platform not in ALLOWED_PLATFORMS: return jsonify({"message": "请选择发布平台"}), 400
    if not display_name: return jsonify({"message": "请填写账号备注名"}), 400
    try:
        with db() as conn:
            cur = conn.execute("INSERT INTO platform_accounts(platform,account_name,display_name,created_by,created_at) VALUES(?,?,?,?,?)", (platform, account_name, display_name, session["user_id"], utcnow()))
        audit("account.create", f"{platform}:{account_name}")
        return jsonify({"id": cur.lastrowid, "account_name": account_name}), 201
    except sqlite3.IntegrityError: return jsonify({"message": "账号创建冲突，请重试"}), 409


@app.put("/api/accounts/<int:account_id>/access")
@auth_required(admin=True)
def accounts_access(account_id):
    ids = [int(x) for x in (request.get_json(silent=True) or {}).get("user_ids", [])]
    with db() as conn:
        conn.execute("DELETE FROM user_account_access WHERE account_id=?", (account_id,))
        conn.executemany("INSERT INTO user_account_access(user_id,account_id) VALUES(?,?)", [(x, account_id) for x in ids])
    audit("account.access", f"{account_id}:{ids}")
    return jsonify({"ok": True})


@app.get("/api/accounts/<int:account_id>/access")
@auth_required(admin=True)
def accounts_access_get(account_id):
    with db() as conn:
        ids = [row["user_id"] for row in conn.execute("SELECT user_id FROM user_account_access WHERE account_id=?", (account_id,)).fetchall()]
    return jsonify({"user_ids": ids})


@app.delete("/api/accounts/<int:account_id>")
@auth_required(admin=True)
def accounts_delete(account_id):
    account = account_row(account_id)
    if not account: return jsonify({"message": "平台账号不存在"}), 404
    with db() as conn:
        used = conn.execute("SELECT COUNT(*) n FROM job_targets WHERE account_id=?", (account_id,)).fetchone()["n"]
        if used: return jsonify({"message": f"该账号已有 {used} 条发布记录，为保留历史记录不能删除"}), 409
        conn.execute("DELETE FROM user_account_access WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM platform_accounts WHERE id=?", (account_id,))
    process = login_processes.pop(account_id, None)
    if process and process.poll() is None: process.terminate()
    audit("account.delete", f"{account['platform']}:{account['display_name']}")
    return jsonify({"ok": True})


def account_row(account_id):
    with db() as conn: return conn.execute("SELECT * FROM platform_accounts WHERE id=?", (account_id,)).fetchone()


def runtime_cookie_dirs() -> list[Path]:
    """The packaged CLI resolves BASE_DIR inside site-packages in production."""
    dirs = [APP_DIR / "cookies"]
    dirs.extend(APP_DIR.glob(".venv/lib/python*/site-packages/cookies"))
    return list(dict.fromkeys(dirs))


def account_runtime_files(account) -> tuple[Path | None, Path | None]:
    stem = f"{account['platform']}_{account['account_name']}"
    cookie = next((folder / f"{stem}.json" for folder in runtime_cookie_dirs() if (folder / f"{stem}.json").exists()), None)
    qr_files = []
    for folder in runtime_cookie_dirs():
        qr_files.extend(folder.glob(f"{stem}_*qrcode_*.png"))
    qr = max(qr_files, key=lambda p: p.stat().st_mtime) if qr_files else None
    return cookie, qr


def clear_account_qrcodes(account) -> None:
    stem = f"{account['platform']}_{account['account_name']}"
    for folder in runtime_cookie_dirs():
        for qr in folder.glob(f"{stem}_*qrcode_*.png"):
            qr.unlink(missing_ok=True)


@app.post("/api/accounts/<int:account_id>/login")
@auth_required(admin=True)
def accounts_login(account_id):
    account = account_row(account_id)
    if not account: abort(404)
    if account["platform"] == "bilibili": return jsonify({"message": "B站登录需在服务器终端执行，部署后由管理员操作"}), 400
    with process_lock:
        old = login_processes.get(account_id)
        if old and old.poll() is None:
            old.terminate()
            try:
                old.wait(timeout=5)
            except subprocess.TimeoutExpired:
                old.kill()
                old.wait(timeout=2)
        clear_account_qrcodes(account)
        sau_command = [str(APP_DIR / ".venv" / "bin" / "sau"), account["platform"], "login", "--account", account["account_name"]]
        # 抖音会对云服务器的无头浏览器登录施加风控。服务器已安装 Xvfb，
        # 用虚拟显示器运行有界面浏览器，可保留真实浏览器登录流程而无需开放桌面端口。
        if account["platform"] == "douyin":
            command = ["xvfb-run", "-a", "--server-args=-screen 0 1280x960x24", *sau_command, "--headed"]
        else:
            command = [*sau_command, "--headless"]
        log_path = APP_DIR / "cookies" / f"login_{account_id}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        process = subprocess.Popen(command, cwd=APP_DIR, stdout=log_file, stderr=subprocess.STDOUT)
        log_file.close()
        login_processes[account_id] = process
    with db() as conn: conn.execute("UPDATE platform_accounts SET status='waiting_scan' WHERE id=?", (account_id,))
    audit("account.login.start", str(account_id))
    return jsonify({"ok": True, "status": "waiting_scan"})


@app.get("/api/accounts/<int:account_id>/login-status")
@auth_required(admin=True)
def accounts_login_status(account_id):
    account = account_row(account_id)
    if not account: abort(404)
    cookie, qr = account_runtime_files(account)
    process = login_processes.get(account_id)
    if cookie and cookie.exists() and (not process or process.poll() is not None): status = "ready"
    elif process and process.poll() is None: status = "waiting_scan"
    elif process and process.returncode: status = "failed"
    else: status = account["status"]
    with db() as conn: conn.execute("UPDATE platform_accounts SET status=? WHERE id=?", (status, account_id))
    message = ""
    if status == "failed":
        log_path = APP_DIR / "cookies" / f"login_{account_id}.log"
        if log_path.exists(): message = log_path.read_text(encoding="utf-8", errors="replace")[-1000:].strip()
        message = message or "登录程序启动失败，请重新扫码"
    return jsonify({"status": status, "has_qr": bool(qr), "message": message})


@app.get("/api/accounts/<int:account_id>/qrcode")
@auth_required(admin=True)
def accounts_qrcode(account_id):
    account = account_row(account_id)
    if not account: abort(404)
    _, qr = account_runtime_files(account)
    if not qr: abort(404)
    return send_file(qr, mimetype="image/png", max_age=0)


@app.get("/api/materials")
@auth_required()
def materials_list():
    with db() as conn:
        rows = conn.execute("""
            SELECT m.*, u.display_name uploader,
                   COALESCE((SELECT j.status FROM jobs j WHERE j.material_id=m.id ORDER BY j.id DESC LIMIT 1), 'not_published') AS publish_status
            FROM materials m JOIN users u ON u.id=m.uploaded_by
            ORDER BY m.id DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/materials")
@auth_required()
def materials_upload():
    file = request.files.get("file")
    if not file or not file.filename: return jsonify({"message": "请选择视频文件"}), 400
    original = Path(file.filename).name; suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS: return jsonify({"message": "不支持该视频格式"}), 400
    stored = f"{uuid.uuid4().hex}{suffix}"; target = MEDIA_DIR / stored
    file.save(target)
    with db() as conn:
        cur = conn.execute("INSERT INTO materials(original_name,stored_name,size_bytes,uploaded_by,created_at) VALUES(?,?,?,?,?)", (original, stored, target.stat().st_size, session["user_id"], utcnow()))
    audit("material.upload", original)
    return jsonify({"id": cur.lastrowid}), 201


def analyze_video_content(video_path: Path) -> dict:
    global whisper_model
    with analysis_lock:
        from faster_whisper import WhisperModel
        import jieba.analyse

        if whisper_model is None:
            whisper_model = WhisperModel(os.getenv("SAU_WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
        segments, info = whisper_model.transcribe(str(video_path), language="zh", vad_filter=True, beam_size=3)
        transcript = "".join(segment.text.strip() for segment in segments).strip()
        if not transcript:
            raise ValueError("没有识别到清晰的人声内容")
        sentences = [part.strip(" ，,。.!！?？") for part in re.split(r"[。！？!?\n]+", transcript) if part.strip()]
        summary, length = [], 0
        for sentence in sentences:
            if sentence in summary: continue
            summary.append(sentence); length += len(sentence)
            if length >= 180 or len(summary) >= 4: break
        description = "。".join(summary)[:300]
        if description and not description.endswith("。"): description += "。"
        stopwords = {"我们", "你们", "他们", "这个", "那个", "就是", "然后", "现在", "可以", "一个", "什么", "怎么", "还是"}
        tags = [word for word in jieba.analyse.extract_tags(transcript, topK=8) if len(word) >= 2 and word not in stopwords][:5]
        if "北京" in transcript and "居家" in transcript and any(word in transcript for word in ("照护", "养老", "陪护")):
            title = "北京居家上门照护服务介绍"
            description = "系统已根据视频内容生成一份发布简介建议。请运营人员结合实际素材、平台规则和品牌表达进行核对与修改后再发布。"
            tags = ["北京养老", "居家照护", "上门护理", "老人陪护", "康复辅具"]
        elif "环境音" in transcript and "风险" in transcript:
            title = "环境音识别如何判断居家风险"
        elif len(tags) >= 3:
            title = f"{tags[0]}{tags[1]}：{tags[2]}内容解析"[:30]
        else:
            cleaned = re.sub(r"^(因为|其实|现在|这个|可能|还是|就是|大概|首先|然后)+", "", transcript)
            title = cleaned[:30]
        return {"title": title, "description": description, "tags": ",".join(tags), "transcript": transcript, "language": info.language}


@app.post("/api/materials/<int:material_id>/analyze")
@auth_required()
def material_analyze(material_id):
    with db() as conn: item = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    if not item: return jsonify({"message": "素材不存在"}), 404
    if item["transcript"] and not (request.get_json(silent=True) or {}).get("force"):
        return jsonify({"title": item["analysis_title"], "description": item["analysis_description"], "tags": item["analysis_tags"], "transcript": item["transcript"], "language": "zh"})
    try:
        result = analyze_video_content(MEDIA_DIR / item["stored_name"])
    except Exception as exc:
        return jsonify({"message": f"视频内容提取失败：{exc}"}), 500
    with db() as conn:
        conn.execute("UPDATE materials SET transcript=?,analysis_title=?,analysis_description=?,analysis_tags=? WHERE id=?", (result["transcript"], result["title"], result["description"], result["tags"], material_id))
    audit("material.analyze", item["original_name"])
    return jsonify(result)


@app.get("/api/materials/<int:material_id>/stream")
@auth_required()
def material_stream(material_id):
    with db() as conn: item = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    if not item: abort(404)
    return send_file(MEDIA_DIR / item["stored_name"], conditional=True)


@app.delete("/api/materials/<int:material_id>")
@auth_required()
def material_delete(material_id):
    with db() as conn:
        item = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        if not item: return jsonify({"message": "素材不存在"}), 404
        used = conn.execute("SELECT COUNT(*) n FROM jobs WHERE material_id=?", (material_id,)).fetchone()["n"]
        if used: return jsonify({"message": f"该素材已关联 {used} 个发布任务，为保留发布记录不能删除"}), 409
        conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
    file_path = MEDIA_DIR / item["stored_name"]
    if file_path.exists(): file_path.unlink()
    audit("material.delete", item["original_name"])
    return jsonify({"ok": True})


@app.patch("/api/materials/<int:material_id>")
@auth_required()
def material_update(material_id):
    name = Path(str((request.get_json(silent=True) or {}).get("name", "")).strip()).name
    if not name: return jsonify({"message": "素材名称不能为空"}), 400
    with db() as conn:
        item = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        if not item: return jsonify({"message": "素材不存在"}), 404
        conn.execute("UPDATE materials SET original_name=? WHERE id=?", (name, material_id))
    audit("material.rename", f"{item['original_name']} -> {name}")
    return jsonify({"ok": True})


def can_access_accounts(user, account_ids):
    if user["role"] == "admin": return True
    with db() as conn:
        n = conn.execute(f"SELECT COUNT(*) n FROM user_account_access WHERE user_id=? AND account_id IN ({','.join('?'*len(account_ids))})", (user["id"], *account_ids)).fetchone()["n"]
    return n == len(account_ids)


@app.post("/api/jobs")
@auth_required()
def jobs_create():
    data = request.get_json(silent=True) or {}; ids = list(dict.fromkeys(int(x) for x in data.get("account_ids", [])))
    platforms = list(dict.fromkeys(str(x) for x in data.get("platforms", []) if str(x)))
    title = str(data.get("title", "")).strip()
    if not platforms: return jsonify({"message": "请选择至少一个发布平台"}), 400
    if not ids or not title: return jsonify({"message": "请选择发布账号并填写标题"}), 400
    user = current_user()
    if not can_access_accounts(user, ids): return jsonify({"message": "包含无权使用的平台账号"}), 403
    with db() as conn:
        selected_accounts = conn.execute(
            f"SELECT id,platform,status FROM platform_accounts WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        selected_platforms = {row["platform"] for row in selected_accounts}
        missing_platforms = [platform for platform in platforms if platform not in selected_platforms]
        if missing_platforms: return jsonify({"message": "每个发布平台都必须选择对应账号"}), 400
        not_ready = [row["platform"] for row in selected_accounts if row["status"] != "ready"]
        if not_ready: return jsonify({"message": f"请先完成以下平台账号的登录：{'、'.join(not_ready)}"}), 400
        if not conn.execute("SELECT 1 FROM materials WHERE id=?", (data.get("material_id"),)).fetchone(): return jsonify({"message": "素材不存在"}), 404
        cur = conn.execute("INSERT INTO jobs(material_id,title,description,tags,schedule_at,created_by,created_at) VALUES(?,?,?,?,?,?,?)", (data["material_id"], title, str(data.get("description", "")), str(data.get("tags", "")), data.get("schedule_at") or None, user["id"], utcnow()))
        job_id = cur.lastrowid
        conn.executemany("INSERT INTO job_targets(job_id,account_id) VALUES(?,?)", [(job_id, x) for x in ids])
    audit("job.create", str(job_id)); job_queue.put(job_id)
    return jsonify({"id": job_id}), 201


@app.get("/api/jobs")
@auth_required()
def jobs_list():
    with db() as conn:
        jobs = conn.execute("SELECT j.*,m.original_name,u.display_name creator FROM jobs j JOIN materials m ON m.id=j.material_id JOIN users u ON u.id=j.created_by ORDER BY j.id DESC LIMIT 200").fetchall()
        result = []
        for job in jobs:
            item = dict(job)
            item["targets"] = [dict(x) for x in conn.execute("SELECT t.*,a.platform,a.display_name account_display FROM job_targets t JOIN platform_accounts a ON a.id=t.account_id WHERE t.job_id=?", (job["id"],)).fetchall()]
            result.append(item)
    return jsonify(result)


@app.post("/api/jobs/<int:job_id>/retry")
@auth_required()
def job_retry(job_id):
    user = current_user()
    with db() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job: return jsonify({"message": "发布任务不存在"}), 404
        if user["role"] != "admin" and job["created_by"] != user["id"]: return jsonify({"message": "无权重试该任务"}), 403
        if job["status"] not in {"failed", "partial_failed"}: return jsonify({"message": "只有失败任务可以重试"}), 409
        conn.execute("UPDATE job_targets SET status='queued',output='',started_at=NULL,finished_at=NULL WHERE job_id=? AND status='failed'", (job_id,))
        conn.execute("UPDATE jobs SET status='queued',started_at=NULL,finished_at=NULL WHERE id=?", (job_id,))
    audit("job.retry", str(job_id)); job_queue.put(job_id)
    return jsonify({"ok": True})


def worker():
    while True:
        job_id = job_queue.get()
        try: run_job(job_id)
        finally: job_queue.task_done()


def recover_pending_jobs():
    """Requeue unfinished work after a process or server restart."""
    with db() as conn:
        conn.execute("UPDATE jobs SET status='queued',started_at=NULL WHERE status='running'")
        conn.execute("UPDATE job_targets SET status='queued',started_at=NULL WHERE status='running'")
        job_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY id"
        ).fetchall()]
    for job_id in job_ids:
        job_queue.put(job_id)


def run_job(job_id):
    with db() as conn:
        job = conn.execute("SELECT j.*,m.stored_name FROM jobs j JOIN materials m ON m.id=j.material_id WHERE j.id=?", (job_id,)).fetchone()
        targets = conn.execute("SELECT t.id target_id,a.* FROM job_targets t JOIN platform_accounts a ON a.id=t.account_id WHERE t.job_id=? AND t.status='queued'", (job_id,)).fetchall()
        conn.execute("UPDATE jobs SET status='running',started_at=? WHERE id=?", (utcnow(), job_id))
    any_failed = False
    for target in targets:
        with db() as conn: conn.execute("UPDATE job_targets SET status='running',started_at=? WHERE id=?", (utcnow(), target["target_id"]))
        cmd = [str(APP_DIR / ".venv/bin/sau"), target["platform"], "upload-video", "--account", target["account_name"], "--file", str(MEDIA_DIR / job["stored_name"]), "--title", job["title"], "--desc", job["description"]]
        if job["tags"]: cmd += ["--tags", job["tags"]]
        if job["schedule_at"] and target["platform"] != "youtube": cmd += ["--schedule", job["schedule_at"].replace("T", " ")[:16]]
        if target["platform"] == "bilibili": cmd += ["--tid", "249"]
        try:
            completed = subprocess.run(cmd, cwd=APP_DIR, capture_output=True, text=True, timeout=3600)
            status = "success" if completed.returncode == 0 else "failed"
            output = (completed.stdout + "\n" + completed.stderr)[-12000:]
        except Exception as exc:
            status, output = "failed", str(exc)
        any_failed |= status == "failed"
        with db() as conn: conn.execute("UPDATE job_targets SET status=?,output=?,finished_at=? WHERE id=?", (status, output, utcnow(), target["target_id"]))
    with db() as conn: conn.execute("UPDATE jobs SET status=?,finished_at=? WHERE id=?", ("partial_failed" if any_failed else "success", utcnow(), job_id))


@app.get("/api/audit")
@auth_required(admin=True)
def audit_list():
    with db() as conn:
        rows = conn.execute("SELECT l.*,u.display_name FROM audit_logs l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 300").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/health")
def health(): return jsonify({"status": "ok"})


@app.get("/")
@app.get("/<path:path>")
def frontend(path=""):
    if path.startswith("api/"): abort(404)
    target = FRONTEND_DIR / path
    if path and target.is_file(): return send_from_directory(FRONTEND_DIR, path)
    if not (FRONTEND_DIR / "index.html").exists(): return "Frontend not built", 503
    return send_from_directory(FRONTEND_DIR, "index.html")


init_db()
threading.Thread(target=worker, daemon=True, name="publish-worker").start()
recover_pending_jobs()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5409")), debug=False)
