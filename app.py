"""
Joshemve Modpack Archive — Flask API Backend
This gets run on pythonanywhere to host the backend
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
import secrets

app = Flask(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "thiswork"   # ← change this
SECRET_KEY     = "your_secret_key_here" # ← set a fixed random string

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(BASE_DIR, "modpack_archive.db")
ANALYTICS_PATH = os.path.join(BASE_DIR, "analytics.db")

ALLOWED_ORIGINS = [
    "https://joshemve-modpack-archive.github.io",
    "http://localhost:8080",
    "http://127.0.0.1:5500",
    "null",
]
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=True)

active_tokens = {}

# ── DATABASE ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS packs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL,
                video_url    TEXT,
                desc         TEXT,
                mc_ver       TEXT    NOT NULL,
                pack_ver     TEXT,
                mods         INTEGER DEFAULT 0,
                status       TEXT    DEFAULT 'active',
                display_order INTEGER DEFAULT 0,
                year         INTEGER,
                tags         TEXT    DEFAULT '[]',
                colors       TEXT    DEFAULT '[]',
                thumb        TEXT,
                download_url TEXT,
                created_at   TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pack_files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_id     INTEGER NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
                url         TEXT    NOT NULL,
                orig_name   TEXT    NOT NULL,
                size        INTEGER NOT NULL,
                mime_type   TEXT,
                label       TEXT,
                uploaded_at TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pack_gallery (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_id     INTEGER NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
                image_data  TEXT    NOT NULL,
                caption     TEXT,
                sort_order  INTEGER DEFAULT 0,
                created_at  TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()


def get_analytics_db():
    conn = sqlite3.connect(ANALYTICS_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_analytics_db():
    with get_analytics_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                page       TEXT,
                pack_id    INTEGER,
                visitor_id TEXT,
                ts         TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_id    INTEGER NOT NULL,
                visitor_id TEXT    NOT NULL,
                ts         TEXT    DEFAULT (datetime('now')),
                UNIQUE(pack_id, visitor_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_likes_pack ON likes(pack_id)")
        conn.commit()

def get_setting(key, default=None):
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default
    except Exception:
        return default

def set_setting(key, value):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
        conn.commit()

def get_pack_gallery(conn, pack_id):
    rows = conn.execute(
        "SELECT id, image_data, caption, sort_order FROM pack_gallery WHERE pack_id=? ORDER BY sort_order ASC",
        (pack_id,)
    ).fetchall()
    return [{"id": r["id"], "image": r["image_data"], "caption": r["caption"] or ""} for r in rows]

def get_pack_files(conn, pack_id):
    rows = conn.execute(
        "SELECT orig_name AS name, size, mime_type, url, label FROM pack_files WHERE pack_id=?",
        (pack_id,)
    ).fetchall()
    return [{"name": r["name"], "size": r["size"], "url": r["url"], "label": r["label"] or ""} for r in rows]

def row_to_pack(row, files=None):
    d = dict(row)
    d["tags"]         = json.loads(d.get("tags")    or "[]")
    d["colors"]       = json.loads(d.get("colors")  or "[]")
    d["mcVer"]        = d.pop("mc_ver",        "")
    d["packVer"]      = d.pop("pack_ver",      "")
    d["videoUrl"]     = d.pop("video_url",     "")
    d["downloadUrl"]  = d.pop("download_url",  "")
    d.pop("created_at", None)
    if files is not None:
        d["files"] = files
    return d

# ── AUTH ──────────────────────────────────────────────────────────────────────
def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        expiry = active_tokens.get(token)
        if not expiry or datetime.utcnow() > expiry:
            active_tokens.pop(token, None)
            return jsonify({"error": "Unauthorized"}), 401
        active_tokens[token] = datetime.utcnow() + timedelta(hours=8)
        return f(*args, **kwargs)
    return decorated

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    if (data.get("username") == ADMIN_USERNAME and
            data.get("password") == ADMIN_PASSWORD):
        token = secrets.token_hex(32)
        active_tokens[token] = datetime.utcnow() + timedelta(hours=8)
        return jsonify({"token": token})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/logout", methods=["POST"])
def logout():
    active_tokens.pop(request.headers.get("X-Admin-Token", ""), None)
    return jsonify({"ok": True})

# ── SETTINGS ──────────────────────────────────────────────────────────────────
@app.route("/api/settings/featured", methods=["GET"])
def get_featured():
    val = get_setting("featured_id")
    return jsonify({"featured_id": int(val) if val else None})

@app.route("/api/settings/featured", methods=["PUT"])
@require_admin
def set_featured():
    data = request.get_json(silent=True) or {}
    pack_id = data.get("featured_id")
    if pack_id is not None:
        with get_db() as conn:
            if not conn.execute("SELECT id FROM packs WHERE id=?", (pack_id,)).fetchone():
                abort(404)
        set_setting("featured_id", pack_id)
    else:
        set_setting("featured_id", "")
    return jsonify({"featured_id": pack_id})

# ── PACKS ─────────────────────────────────────────────────────────────────────
def get_visitor_id():
    """Hash the real client IP + UA into a short anonymous ID.
    Respects X-Forwarded-For set by PythonAnywhere's reverse proxy."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "")
    ua = request.headers.get("User-Agent") or ""
    return hashlib.sha256((ip + ua).encode()).hexdigest()[:16]


@app.route("/api/packs", methods=["GET"])
def list_packs():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM packs ORDER BY display_order ASC, id ASC").fetchall()
        result = []
        for row in rows:
            files   = get_pack_files(conn, row["id"])
            gallery = get_pack_gallery(conn, row["id"])
            p = row_to_pack(row, files)
            p["gallery"] = gallery
            result.append(p)
    return jsonify(result)

@app.route("/api/packs/reorder", methods=["PUT"])
@require_admin
def reorder_packs():
    """Accepts an ordered list of pack IDs and updates display_order accordingly."""
    ids = request.get_json(silent=True) or []
    if not isinstance(ids, list):
        return jsonify({"error": "expected list of ids"}), 400
    with get_db() as conn:
        for i, pack_id in enumerate(ids):
            conn.execute("UPDATE packs SET display_order=? WHERE id=?", (i, pack_id))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/packs/<int:pack_id>", methods=["GET"])
def get_pack(pack_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone()
        if not row:
            abort(404)
        files   = get_pack_files(conn, pack_id)
    gallery = get_pack_gallery(conn, pack_id)
    p = row_to_pack(row, files)
    p["gallery"] = gallery
    return jsonify(p)

@app.route("/api/packs", methods=["POST"])
@require_admin
def create_pack():
    d = request.get_json(silent=True) or {}
    if not d.get("name") or not d.get("mcVer"):
        return jsonify({"error": "name and mcVer are required"}), 400
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO packs
              (name, video_url, desc, mc_ver, pack_ver, mods, status, year, tags, colors, thumb, download_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            d["name"], d.get("videoUrl",""), d.get("desc",""),
            d["mcVer"], d.get("packVer",""),
            int(d.get("mods", 0)),
            d.get("status","active"),
            int(d.get("year", datetime.utcnow().year)),
            json.dumps(d.get("tags",[])),
            json.dumps(d.get("colors",[])),
            d.get("thumb", None),
            d.get("downloadUrl", ""),
        ))
        new_id = cur.lastrowid
        # Generate and store IA identifier now we have the ID
        # Set display_order to current max + 1 so new packs go to the end
        max_order = conn.execute("SELECT COALESCE(MAX(display_order),0) FROM packs").fetchone()[0]
        conn.execute("UPDATE packs SET display_order=? WHERE id=?", (max_order + 1, new_id))
        conn.commit()
        row = conn.execute("SELECT * FROM packs WHERE id=?", (new_id,)).fetchone()
    return jsonify(row_to_pack(row, [])), 201

@app.route("/api/packs/<int:pack_id>", methods=["PUT"])
@require_admin
def update_pack(pack_id):
    d = request.get_json(silent=True) or {}
    with get_db() as conn:
        if not conn.execute("SELECT id FROM packs WHERE id=?", (pack_id,)).fetchone():
            abort(404)
        conn.execute("""
            UPDATE packs SET
                name=?, video_url=?, desc=?, mc_ver=?, pack_ver=?,
                mods=?, status=?, year=?, tags=?, colors=?, thumb=?, download_url=?
            WHERE id=?
        """, (
            d.get("name"), d.get("videoUrl",""), d.get("desc",""),
            d.get("mcVer"), d.get("packVer",""),
            int(d.get("mods", 0)),
            d.get("status","active"),
            int(d.get("year", datetime.utcnow().year)),
            json.dumps(d.get("tags",[])),
            json.dumps(d.get("colors",[])),
            d.get("thumb", None),
            d.get("downloadUrl", ""),
            pack_id,
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone()
        files   = get_pack_files(conn, pack_id)
        gallery = get_pack_gallery(conn, pack_id)
    p = row_to_pack(row, files)
    p["gallery"] = gallery
    return jsonify(p)

@app.route("/api/packs/<int:pack_id>", methods=["DELETE"])
@require_admin
def delete_pack(pack_id):
    with get_db() as conn:
        conn.execute("DELETE FROM packs WHERE id=?", (pack_id,))
        conn.commit()
    return jsonify({"ok": True})

# ── FILES ─────────────────────────────────────────────────────────────────────
@app.route("/api/packs/<int:pack_id>/files/register", methods=["POST"])
@require_admin
def register_file(pack_id):
    """Register an external file URL for a pack."""
    with get_db() as conn:
        if not conn.execute("SELECT id FROM packs WHERE id=?", (pack_id,)).fetchone():
            abort(404)
        d         = request.get_json(silent=True) or {}
        orig_name = d.get("name")
        url       = d.get("url", "")
        size      = int(d.get("size", 0))
        mime      = d.get("mime_type", "application/octet-stream")
        label     = d.get("label", "") or ""
        if not orig_name:
            return jsonify({"error": "name required"}), 400
        conn.execute("""
            INSERT OR REPLACE INTO pack_files (pack_id, url, orig_name, size, mime_type, label)
            VALUES (?,?,?,?,?,?)
        """, (pack_id, url, orig_name, size, mime, label))
        conn.commit()
    return jsonify({"name": orig_name, "size": size, "url": url}), 201

@app.route("/api/packs/<int:pack_id>/files/<path:filename>", methods=["DELETE"])
@require_admin
def delete_file(pack_id, filename):
    """Remove a file record from DB."""
    with get_db() as conn:
        if not conn.execute("SELECT id FROM packs WHERE id=?", (pack_id,)).fetchone():
            abort(404)
        conn.execute(
            "DELETE FROM pack_files WHERE pack_id=? AND orig_name=?",
            (pack_id, filename)
        )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/api/packs/<int:pack_id>/files/<path:filename>/label", methods=["PATCH"])
@require_admin
def update_file_label(pack_id, filename):
    """Update the label of an existing file."""
    d     = request.get_json(silent=True) or {}
    label = d.get("label", "") or ""
    with get_db() as conn:
        if not conn.execute("SELECT id FROM packs WHERE id=?", (pack_id,)).fetchone():
            abort(404)
        conn.execute(
            "UPDATE pack_files SET label=? WHERE pack_id=? AND orig_name=?",
            (label, pack_id, filename)
        )
        conn.commit()
    return jsonify({"ok": True})


# ── GALLERY ──────────────────────────────────────────────────────────────────
@app.route("/api/packs/<int:pack_id>/gallery", methods=["POST"])
@require_admin
def add_gallery_image(pack_id):
    """Add a base64 image to the pack gallery."""
    with get_db() as conn:
        if not conn.execute("SELECT id FROM packs WHERE id=?", (pack_id,)).fetchone():
            abort(404)
        d       = request.get_json(silent=True) or {}
        image   = d.get("image", "")
        caption = d.get("caption", "") or ""
        if not image:
            return jsonify({"error": "image required"}), 400
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM pack_gallery WHERE pack_id=?", (pack_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO pack_gallery (pack_id, image_data, caption, sort_order) VALUES (?,?,?,?)",
            (pack_id, image, caption, max_order + 1)
        )
        img_id = cur.lastrowid
        conn.commit()
    return jsonify({"id": img_id, "image": image, "caption": caption}), 201

@app.route("/api/packs/<int:pack_id>/gallery/<int:img_id>", methods=["DELETE"])
@require_admin
def delete_gallery_image(pack_id, img_id):
    with get_db() as conn:
        conn.execute("DELETE FROM pack_gallery WHERE id=? AND pack_id=?", (img_id, pack_id))
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/packs/<int:pack_id>/gallery/<int:img_id>/caption", methods=["PATCH"])
@require_admin
def update_gallery_caption(pack_id, img_id):
    d = request.get_json(silent=True) or {}
    caption = d.get("caption", "") or ""
    with get_db() as conn:
        conn.execute("UPDATE pack_gallery SET caption=? WHERE id=? AND pack_id=?", (caption, img_id, pack_id))
        conn.commit()
    return jsonify({"ok": True})


# ── ANALYTICS ─────────────────────────────────────────────────────────────────
@app.route("/api/track", methods=["POST"])
def track():
    """Lightweight event tracker called from frontend pages."""
    d = request.get_json(silent=True) or {}
    event_type = d.get("type")   # "pageview" | "download"
    page       = d.get("page")   # "index" | "pack"
    pack_id    = d.get("pack_id")

    # Build anonymised visitor ID: hash of IP + UA (no personal data stored)
    visitor_id = get_visitor_id()

    if not event_type:
        return jsonify({"ok": False}), 400

    with get_analytics_db() as conn:
        conn.execute(
            "INSERT INTO events (event_type, page, pack_id, visitor_id) VALUES (?,?,?,?)",
            (event_type, page, pack_id, visitor_id)
        )
        conn.commit()
    return jsonify({"ok": True})

@app.route("/api/analytics", methods=["GET"])
@require_admin
def get_analytics():
    days = min(int(request.args.get("days", 30)), 365)
    with get_analytics_db() as conn:
        total_visits    = conn.execute("SELECT COUNT(*) FROM events WHERE event_type='pageview'").fetchone()[0]
        total_downloads = conn.execute("SELECT COUNT(*) FROM events WHERE event_type='download'").fetchone()[0]
        unique_visitors = conn.execute("SELECT COUNT(DISTINCT visitor_id) FROM events").fetchone()[0]

    with get_analytics_db() as conn:
        total_likes = conn.execute("SELECT COUNT(*) FROM likes").fetchone()[0]
        most_liked = conn.execute("""
            SELECT pack_id, COUNT(*) as count
            FROM likes GROUP BY pack_id ORDER BY count DESC LIMIT 10
        """).fetchall()
        daily_likes = conn.execute("""
            SELECT date(ts) as day, COUNT(*) as count
            FROM likes
            WHERE ts >= date('now', :offset)
            GROUP BY date(ts)
            ORDER BY day
        """, {"offset": f"-{days-1} days"}).fetchall()

        # Most viewed packs (top 10)
        top_packs = conn.execute("""
            SELECT pack_id, COUNT(*) as views
            FROM events WHERE event_type='pageview' AND pack_id IS NOT NULL
            GROUP BY pack_id ORDER BY views DESC LIMIT 10
        """).fetchall()

        daily = conn.execute("""
            SELECT DATE(ts) as day, COUNT(*) as count
            FROM events WHERE event_type='pageview'
              AND ts >= datetime('now', :offset)
            GROUP BY day ORDER BY day ASC
        """, {"offset": f"-{days-1} days"}).fetchall()

    # Enrich top_packs with pack names
    top_packs_data = []
    most_liked_data = []
    with get_db() as conn:
        for row in top_packs:
            pack = conn.execute("SELECT name FROM packs WHERE id=?", (row["pack_id"],)).fetchone()
            top_packs_data.append({
                "pack_id": row["pack_id"],
                "name": pack["name"] if pack else f"Pack #{row['pack_id']}",
                "views": row["views"]
            })
        for row in most_liked:
            pack = conn.execute("SELECT name FROM packs WHERE id=?", (row["pack_id"],)).fetchone()
            most_liked_data.append({
                "pack_id": row["pack_id"],
                "name": pack["name"] if pack else f"Pack #{row['pack_id']}",
                "likes": row["count"]
            })

    return jsonify({
        "total_visits":    total_visits,
        "total_downloads": total_downloads,
        "unique_visitors": unique_visitors,
        "total_likes":     total_likes,
        "top_packs":       top_packs_data,
        "most_liked":      most_liked_data,
        "daily":           [{"day": r["day"], "count": r["count"]} for r in daily],
        "daily_likes":     [{"day": r["day"], "count": r["count"]} for r in daily_likes],
    })


@app.route("/api/packs/<int:pack_id>/like", methods=["POST"])
def like_pack(pack_id):
    """Toggle like for a pack. One like per visitor (hashed IP+UA)."""
    with get_db() as conn:
        if not conn.execute("SELECT id FROM packs WHERE id=?", (pack_id,)).fetchone():
            abort(404)
    visitor_id = get_visitor_id()
    with get_analytics_db() as conn:
        existing = conn.execute(
            "SELECT id FROM likes WHERE pack_id=? AND visitor_id=?",
            (pack_id, visitor_id)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM likes WHERE pack_id=? AND visitor_id=?", (pack_id, visitor_id))
            liked = False
        else:
            conn.execute("INSERT INTO likes (pack_id, visitor_id) VALUES (?,?)", (pack_id, visitor_id))
            liked = True
        count = conn.execute("SELECT COUNT(*) FROM likes WHERE pack_id=?", (pack_id,)).fetchone()[0]
        conn.commit()
    return jsonify({"liked": liked, "count": count})

@app.route("/api/packs/<int:pack_id>/like", methods=["GET"])
def get_like(pack_id):
    """Get like count and whether current visitor has liked."""
    visitor_id = get_visitor_id()
    with get_analytics_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM likes WHERE pack_id=?", (pack_id,)).fetchone()[0]
        liked = conn.execute(
            "SELECT id FROM likes WHERE pack_id=? AND visitor_id=?",
            (pack_id, visitor_id)
        ).fetchone() is not None
    return jsonify({"liked": liked, "count": count})

@app.route("/api/likes", methods=["GET"])
def get_all_likes():
    """Return like counts for all packs — used by index page."""
    with get_analytics_db() as conn:
        rows = conn.execute(
            "SELECT pack_id, COUNT(*) as count FROM likes GROUP BY pack_id"
        ).fetchall()
    return jsonify({str(r["pack_id"]): r["count"] for r in rows})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

# ── BOOT ──────────────────────────────────────────────────────────────────────
init_db()
init_analytics_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
