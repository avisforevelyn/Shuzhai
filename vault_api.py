# -*- coding: utf-8 -*-
"""
Shuzhai · vault backend (SQLite)
Resources (vault_resources) 1 -- N versions (vault_versions); folders per kind (vault_folders).
Routed by server.py under the /api/vault prefix.

Routes:
  GET    /api/vault/list                    all resources with version metadata (no bodies)
  GET    /api/vault/get?vid=                one version incl. body
  GET    /api/vault/download?vid=           raw file (json / png / txt)
  GET    /api/vault/folders                 user-created folders per kind
  POST   /api/vault/upload                  JSON body {kind,name,note,format,content,filename,resource_id?,...}
  POST   /api/vault/upload_bin?...          raw bytes body (png) / raw text (json), metadata in the query string
  POST   /api/vault/rename                  {resource_id,name?,note?,tags?,folders?}
  POST   /api/vault/version_edit            {version_id,label?,note?,vdate?,tags?,folders?}
  POST   /api/vault/set_cover               {resource_id,cover}
  POST   /api/vault/reorder                 {ids:[...]}
  POST   /api/vault/folder_add | folder_del {kind,name}
  DELETE /api/vault/version?vid=            delete one version (resource goes too when empty)
  DELETE /api/vault/resource?rid=           delete a resource with all versions
"""
import os, time, json, base64, secrets, sqlite3
from urllib.parse import parse_qs

DB_PATH = os.environ.get("SHUZHAI_DB") or os.path.join(os.environ.get("SHUZHAI_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), "vault.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
KINDS = ("card", "preset", "book", "beauty", "unknown")
FORMATS = ("json", "png", "text")


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=8.0)
    c.row_factory = sqlite3.Row
    return c


def _init():
    c = _conn()
    c.execute("""CREATE TABLE IF NOT EXISTS vault_resources(
        id TEXT PRIMARY KEY, kind TEXT, name TEXT, note TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS vault_versions(
        id TEXT PRIMARY KEY, resource_id TEXT, label TEXT, note TEXT,
        filename TEXT, format TEXT, content TEXT, size INTEGER, created_at INTEGER)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_vv_res ON vault_versions(resource_id)")
    c.execute("CREATE TABLE IF NOT EXISTS vault_folders(kind TEXT, name TEXT, created_at INTEGER, PRIMARY KEY(kind,name))")
    # 展示柜封面(小缩略图 data URL): 老库没有这列就补上
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(vault_resources)").fetchall()]
        if "cover" not in cols:
            c.execute("ALTER TABLE vault_resources ADD COLUMN cover TEXT")
    except Exception:
        pass
    # 作者更新日期(她填的, 卡作者发布日期, 区别于导入时间 created_at)
    try:
        vcols = [r[1] for r in c.execute("PRAGMA table_info(vault_versions)").fetchall()]
        if "vdate" not in vcols:
            c.execute("ALTER TABLE vault_versions ADD COLUMN vdate TEXT")
        if "tags" not in vcols:
            c.execute("ALTER TABLE vault_versions ADD COLUMN tags TEXT")
        if "folders" not in vcols:
            c.execute("ALTER TABLE vault_versions ADD COLUMN folders TEXT")
    except Exception:
        pass
    # 标签(tags, JSON 数组) + 文件夹(folder)
    try:
        rcols = [r[1] for r in c.execute("PRAGMA table_info(vault_resources)").fetchall()]
        if "tags" not in rcols:
            c.execute("ALTER TABLE vault_resources ADD COLUMN tags TEXT")
        if "folder" not in rcols:
            c.execute("ALTER TABLE vault_resources ADD COLUMN folder TEXT")
        if "sort_order" not in rcols:
            c.execute("ALTER TABLE vault_resources ADD COLUMN sort_order INTEGER")
    except Exception:
        pass
    c.commit(); c.close()


_init()


def _now():
    return int(time.time() * 1000)


def _rid():
    return "r_" + format(_now(), "x") + "_" + secrets.token_hex(3)


def _vid():
    return "v_" + format(_now(), "x") + "_" + secrets.token_hex(3)


def _split_tags(sv):
    import re as _re
    out, seen = [], set()
    for t in _re.split(r'[/|，,、\n\r]+', str(sv or '')):
        t = t.strip()
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out


def _norm_list(v):
    """接受 list 或分隔字符串 → 去重清洗后的 list"""
    if isinstance(v, list):
        out, seen = [], set()
        for t in v:
            t = str(t).strip()
            if t and t not in seen:
                seen.add(t); out.append(t)
        return out
    return _split_tags(v)


def _parse_folders(raw):
    """folder 列: 新格式=JSON 数组; 老格式=单个字符串 → 包成单元素"""
    raw = raw or ""
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return _norm_list(v)
    except Exception:
        pass
    return _norm_list(raw)


def _ver_meta(r):
    try:
        vdate = r["vdate"] or ""
    except Exception:
        vdate = ""
    try:
        vtags = json.loads(r["tags"]) if r["tags"] else []
        if not isinstance(vtags, list): vtags = []
    except Exception:
        vtags = []
    try:
        vfolders = _parse_folders(r["folders"])
    except Exception:
        vfolders = []
    return {
        "id": r["id"], "resource_id": r["resource_id"],
        "label": r["label"] or "", "note": r["note"] or "",
        "filename": r["filename"] or "", "format": r["format"] or "json",
        "size": r["size"] or 0, "created_at": r["created_at"] or 0,
        "vdate": vdate, "tags": vtags, "folders": vfolders,
    }


# ---------- GET ----------
def route_get(s, p, q):
    try:
        if p.path == "/api/vault/list":
            return _list(s)
        if p.path == "/api/vault/get":
            vid = (q.get("vid", [""])[0] or "").strip()
            return _get_version(s, vid, with_content=True)
        if p.path == "/api/vault/download":
            vid = (q.get("vid", [""])[0] or "").strip()
            return _download(s, vid)
        if p.path == "/api/vault/folders":
            c = _conn(); rows = c.execute("SELECT kind,name FROM vault_folders ORDER BY created_at").fetchall(); c.close()
            d = {}
            for r in rows: d.setdefault(r["kind"], []).append(r["name"])
            s._json({"ok": True, "folders": d}); return
        s._json({"ok": False, "error": "unknown vault route"}, 404)
    except Exception as e:
        s._json({"ok": False, "error": str(e)[:300]}, 500)


def _list(s):
    c = _conn()
    res = c.execute("SELECT * FROM vault_resources ORDER BY updated_at DESC").fetchall()
    out = []
    for r in res:
        vers = c.execute(
            "SELECT id,resource_id,label,note,filename,format,size,created_at,vdate,tags,folders "
            "FROM vault_versions WHERE resource_id=? ORDER BY created_at DESC",
            [r["id"]]).fetchall()
        try:
            cover = r["cover"] or ""
        except Exception:
            cover = ""
        try:
            tags = json.loads(r["tags"]) if r["tags"] else []
            if not isinstance(tags, list): tags = []
        except Exception:
            tags = []
        try:
            folders = _parse_folders(r["folder"])
        except Exception:
            folders = []
        try:
            sord = r["sort_order"] if r["sort_order"] is not None else (r["created_at"] or 0)
        except Exception:
            sord = r["created_at"] or 0
        out.append({
            "id": r["id"], "kind": r["kind"] or "unknown",
            "name": r["name"] or "untitled", "note": r["note"] or "",
            "cover": cover, "tags": tags, "folders": folders, "folder": (folders[0] if folders else ""), "sort_order": sord,
            "created_at": r["created_at"] or 0, "updated_at": r["updated_at"] or 0,
            "versions": [_ver_meta(v) for v in vers],
        })
    c.close()
    s._json({"ok": True, "resources": out, "count": len(out)})


def _get_version(s, vid, with_content=False):
    if not vid:
        s._json({"ok": False, "error": "vid required"}, 400); return
    c = _conn()
    r = c.execute("SELECT * FROM vault_versions WHERE id=?", [vid]).fetchone()
    c.close()
    if not r:
        s._json({"ok": False, "error": "version not found"}, 404); return
    d = _ver_meta(r)
    if with_content:
        d["content"] = r["content"] or ""
    s._json({"ok": True, "version": d})


def _download(s, vid):
    if not vid:
        s._json({"ok": False, "error": "vid required"}, 400); return
    c = _conn()
    r = c.execute(
        "SELECT v.*, res.name AS rname FROM vault_versions v "
        "LEFT JOIN vault_resources res ON res.id=v.resource_id WHERE v.id=?",
        [vid]).fetchone()
    c.close()
    if not r:
        s._json({"ok": False, "error": "version not found"}, 404); return
    fmt = r["format"] or "json"
    content = r["content"] or ""
    if fmt == "png":
        try:
            data = base64.b64decode(content)
        except Exception:
            data = b""
        ctype = "image/png"; ext = "png"
    elif fmt == "text":
        data = content.encode("utf-8")
        ctype = "text/plain; charset=utf-8"; ext = "txt"
    else:
        data = content.encode("utf-8")
        ctype = "application/json; charset=utf-8"; ext = "json"
    # 文件名 = 卡名_版本号_备注.格式 (缺的那截自动省略), 中文保留, 去非法字符
    def _clean(x):
        return "".join(ch for ch in str(x or "") if ch not in '\\/:*?"<>|\n\r\t').strip()
    parts = [p for p in [_clean(r["rname"]), _clean(r["label"]), _clean(r["note"])] if p]
    base = "_".join(parts) or _clean(r["filename"]) or "file"
    safe = base[:80] + "." + ext
    s.send_response(200)
    s.send_header("Content-Type", ctype)
    s.send_header("Content-Disposition",
                  "attachment; filename*=UTF-8''" + _pct(safe))
    s.send_header("Content-Length", str(len(data)))
    s._cors(); s.end_headers()
    s.wfile.write(data)


def _pct(sv):
    # RFC 3986 百分号编码, 只留 unreserved(A-Za-z0-9-_.~), 中文等全部按 UTF-8 字节编码
    import urllib.parse as _u
    return _u.quote(sv, safe="")


# ---------- POST ----------
def route_post(s, p, body):
    try:
        if not isinstance(body, dict):
            s._json({"ok": False, "error": "body must be object"}, 400); return
        if p.path == "/api/vault/upload":
            return _upload(s, body)
        if p.path == "/api/vault/rename":
            return _rename(s, body)
        if p.path == "/api/vault/version_edit":
            return _version_edit(s, body)
        if p.path == "/api/vault/set_cover":
            return _set_cover(s, body)
        if p.path == "/api/vault/reorder":
            return _reorder(s, body)
        if p.path == "/api/vault/folder_add":
            kind=(body.get("kind") or "").strip(); name=(body.get("name") or "").strip()
            if not kind or not name: s._json({"ok": False, "error": "kind and name required"}, 400); return
            c=_conn(); c.execute("INSERT OR IGNORE INTO vault_folders(kind,name,created_at) VALUES(?,?,?)", [kind, name, _now()]); c.commit(); c.close()
            s._json({"ok": True}); return
        if p.path == "/api/vault/folder_del":
            kind=(body.get("kind") or "").strip(); name=(body.get("name") or "").strip()
            c=_conn(); c.execute("DELETE FROM vault_folders WHERE kind=? AND name=?", [kind, name]); c.commit(); c.close()
            s._json({"ok": True}); return
        s._json({"ok": False, "error": "unknown vault route"}, 404)
    except Exception as e:
        s._json({"ok": False, "error": str(e)[:300]}, 500)


def _upload(s, b):
    kind = (b.get("kind") or "unknown").strip()
    if kind not in KINDS:
        kind = "unknown"
    fmt = (b.get("format") or "json").strip()
    if fmt not in FORMATS:
        fmt = "json"
    content = b.get("content")
    if not isinstance(content, str) or not content.strip():
        s._json({"ok": False, "error": "content required"}, 400); return
    # 体积: json 按 utf-8 字节, png 按解码后字节
    if fmt == "png":
        try:
            size = len(base64.b64decode(content))
        except Exception:
            s._json({"ok": False, "error": "png content not valid base64"}, 400); return
    else:
        # 校验 json 合法(不合法也允许存, 但标记; 这里宽松: 只在明显 json 时校验)
        size = len(content.encode("utf-8"))
    filename = (b.get("filename") or "").strip()
    vlabel = (b.get("version_label") or "").strip()
    vnote = (b.get("version_note") or "").strip()
    now = _now()
    c = _conn()
    resource_id = (b.get("resource_id") or "").strip()
    if resource_id:
        row = c.execute("SELECT * FROM vault_resources WHERE id=?", [resource_id]).fetchone()
        if not row:
            c.close(); s._json({"ok": False, "error": "resource_id not found"}, 404); return
        # 允许上传时顺便更新资源名/备注
        nm = (b.get("name") or "").strip()
        nt = b.get("note")
        if nm:
            c.execute("UPDATE vault_resources SET name=? WHERE id=?", [nm, resource_id])
        if isinstance(nt, str) and nt.strip():
            c.execute("UPDATE vault_resources SET note=? WHERE id=?", [nt.strip(), resource_id])
    else:
        name = (b.get("name") or filename or "untitled").strip() or "untitled"
        note = (b.get("note") or "").strip()
        resource_id = _rid()
        _fl = _norm_list(b.get("folders")) if b.get("folders") is not None else _norm_list(b.get("folder"))
        _tglist = _norm_list(b.get("tags"))
        c.execute("INSERT INTO vault_resources(id,kind,name,note,created_at,updated_at,folder,sort_order,tags) VALUES(?,?,?,?,?,?,?,?,?)",
                  [resource_id, kind, name, note, now, now, json.dumps(_fl, ensure_ascii=False), now, json.dumps(_tglist, ensure_ascii=False)])
    # 版本号缺省: 按该资源现有版本数 +1
    if not vlabel:
        n = c.execute("SELECT COUNT(*) FROM vault_versions WHERE resource_id=?", [resource_id]).fetchone()[0]
        vlabel = "v" + str(int(n) + 1)
    vdate = (b.get("version_date") or "").strip()
    v_tags = json.dumps(_norm_list(b.get("v_tags")), ensure_ascii=False)
    v_folders = json.dumps(_norm_list(b.get("v_folders")), ensure_ascii=False)
    vid = _vid()
    c.execute("INSERT INTO vault_versions(id,resource_id,label,note,filename,format,content,size,created_at,vdate,tags,folders) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              [vid, resource_id, vlabel, vnote, filename, fmt, content, size, now, vdate, v_tags, v_folders])
    c.execute("UPDATE vault_resources SET updated_at=? WHERE id=?", [now, resource_id])
    c.commit(); c.close()
    s._json({"ok": True, "resource_id": resource_id, "version_id": vid, "label": vlabel})


def route_post_bin(s, p, raw):
    """二进制上传: body 是原始文件字节(png)或原始文本(json), 元数据全在 query。
    避开'大 base64 塞 JSON'在 iOS 上发不出去的坑, 原生流式、体积小。"""
    try:
        q = parse_qs(p.query)
        def g(k, d=""):
            v = q.get(k, [d])
            return (v[0] if v else d) or d
        fmt = g("format", "png")
        if fmt not in FORMATS:
            fmt = "png"
        if not raw:
            s._json({"ok": False, "error": "empty body"}, 400); return
        if fmt == "png":
            content = base64.b64encode(raw).decode()
        else:
            content = raw.decode("utf-8", "replace")
        b = {
            "kind": g("kind", "unknown"), "format": fmt, "content": content,
            "filename": g("filename", ""), "name": g("name", ""), "note": g("note", ""),
            "version_label": g("version_label", ""), "version_note": g("version_note", ""),
            "version_date": g("version_date", ""),
            "folder": g("folder", ""), "tags": g("tags", ""),
            "v_tags": g("v_tags", ""), "v_folders": g("v_folders", ""),
            "resource_id": g("resource_id", ""),
        }
        return _upload(s, b)
    except Exception as e:
        s._json({"ok": False, "error": str(e)[:300]}, 500)


def _rename(s, b):
    rid = (b.get("resource_id") or "").strip()
    if not rid:
        s._json({"ok": False, "error": "resource_id required"}, 400); return
    c = _conn()
    row = c.execute("SELECT id FROM vault_resources WHERE id=?", [rid]).fetchone()
    if not row:
        c.close(); s._json({"ok": False, "error": "not found"}, 404); return
    if isinstance(b.get("name"), str) and b.get("name").strip():
        c.execute("UPDATE vault_resources SET name=? WHERE id=?", [b["name"].strip(), rid])
    if isinstance(b.get("note"), str):
        c.execute("UPDATE vault_resources SET note=? WHERE id=?", [b["note"].strip(), rid])
    if isinstance(b.get("tags"), list):
        clean = [str(t).strip() for t in b["tags"] if str(t).strip()]
        seen = set(); uniq = []
        for t in clean:
            if t not in seen: seen.add(t); uniq.append(t)
        c.execute("UPDATE vault_resources SET tags=? WHERE id=?", [json.dumps(uniq, ensure_ascii=False), rid])
    if b.get("folders") is not None or isinstance(b.get("folder"), str):
        fl = _norm_list(b.get("folders")) if b.get("folders") is not None else _norm_list(b.get("folder"))
        c.execute("UPDATE vault_resources SET folder=? WHERE id=?", [json.dumps(fl, ensure_ascii=False), rid])
    c.commit(); c.close()
    s._json({"ok": True})


def _reorder(s, b):
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids:
        s._json({"ok": False, "error": "ids required"}, 400); return
    c = _conn()
    for i, rid in enumerate(ids):
        c.execute("UPDATE vault_resources SET sort_order=? WHERE id=?", [i, str(rid)])
    c.commit(); c.close()
    s._json({"ok": True, "n": len(ids)})


def _set_cover(s, b):
    rid = (b.get("resource_id") or "").strip()
    if not rid:
        s._json({"ok": False, "error": "resource_id required"}, 400); return
    cover = b.get("cover")
    if cover is not None and not isinstance(cover, str):
        s._json({"ok": False, "error": "cover must be string"}, 400); return
    # 封面就是个小缩略图 data URL, 给个上限防塞爆(约 2MB base64)
    if isinstance(cover, str) and len(cover) > 2_000_000:
        s._json({"ok": False, "error": "cover too large"}, 400); return
    c = _conn()
    row = c.execute("SELECT id FROM vault_resources WHERE id=?", [rid]).fetchone()
    if not row:
        c.close(); s._json({"ok": False, "error": "not found"}, 404); return
    c.execute("UPDATE vault_resources SET cover=? WHERE id=?", [cover or "", rid])
    c.commit(); c.close()
    s._json({"ok": True})


def _version_edit(s, b):
    vid = (b.get("version_id") or "").strip()
    if not vid:
        s._json({"ok": False, "error": "version_id required"}, 400); return
    c = _conn()
    row = c.execute("SELECT id FROM vault_versions WHERE id=?", [vid]).fetchone()
    if not row:
        c.close(); s._json({"ok": False, "error": "not found"}, 404); return
    if isinstance(b.get("label"), str) and b.get("label").strip():
        c.execute("UPDATE vault_versions SET label=? WHERE id=?", [b["label"].strip(), vid])
    if isinstance(b.get("note"), str):
        c.execute("UPDATE vault_versions SET note=? WHERE id=?", [b["note"].strip(), vid])
    if isinstance(b.get("vdate"), str):
        c.execute("UPDATE vault_versions SET vdate=? WHERE id=?", [b["vdate"].strip(), vid])
    if b.get("tags") is not None:
        c.execute("UPDATE vault_versions SET tags=? WHERE id=?", [json.dumps(_norm_list(b.get("tags")), ensure_ascii=False), vid])
    if b.get("folders") is not None:
        c.execute("UPDATE vault_versions SET folders=? WHERE id=?", [json.dumps(_norm_list(b.get("folders")), ensure_ascii=False), vid])
    c.commit(); c.close()
    s._json({"ok": True})


# ---------- DELETE ----------
def route_delete(s, p):
    try:
        q = parse_qs(p.query)
        if p.path == "/api/vault/version":
            vid = (q.get("vid", [""])[0] or "").strip()
            return _del_version(s, vid)
        if p.path == "/api/vault/resource":
            rid = (q.get("rid", [""])[0] or "").strip()
            return _del_resource(s, rid)
        s._json({"ok": False, "error": "unknown vault route"}, 404)
    except Exception as e:
        s._json({"ok": False, "error": str(e)[:300]}, 500)


def _del_version(s, vid):
    if not vid:
        s._json({"ok": False, "error": "vid required"}, 400); return
    c = _conn()
    row = c.execute("SELECT resource_id FROM vault_versions WHERE id=?", [vid]).fetchone()
    if not row:
        c.close(); s._json({"ok": False, "error": "not found"}, 404); return
    rid = row["resource_id"]
    c.execute("DELETE FROM vault_versions WHERE id=?", [vid])
    left = c.execute("SELECT COUNT(*) FROM vault_versions WHERE resource_id=?", [rid]).fetchone()[0]
    resource_deleted = False
    if int(left) == 0:
        c.execute("DELETE FROM vault_resources WHERE id=?", [rid])
        resource_deleted = True
    else:
        c.execute("UPDATE vault_resources SET updated_at=? WHERE id=?", [_now(), rid])
    c.commit(); c.close()
    s._json({"ok": True, "resource_deleted": resource_deleted, "resource_id": rid})


def _del_resource(s, rid):
    if not rid:
        s._json({"ok": False, "error": "rid required"}, 400); return
    c = _conn()
    c.execute("DELETE FROM vault_versions WHERE resource_id=?", [rid])
    c.execute("DELETE FROM vault_resources WHERE id=?", [rid])
    c.commit(); c.close()
    s._json({"ok": True})
