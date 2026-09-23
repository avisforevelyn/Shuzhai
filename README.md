# 书斋 · Shuzhai

*A quiet shelf for your character cards, presets, lorebooks and themes.*

**Shuzhai** (书斋, "study room") is a tiny self-hosted vault for the files that pile up around
SillyTavern-style roleplay: **character cards** (`.json` / `.png`), **presets**, **world info /
lorebooks**, and **UI themes / CSS**. Drop a file in, read it as clean text, keep every version,
sort it into folders you create yourself.

It is one Python file plus one HTML file. No build step, no npm, no database server.

## Features

- **Read anything** — character cards (V2 / V3, JSON or PNG with embedded `chara` / `ccv3`),
  presets (every `prompt_order` table, not just the first one, so nothing is silently dropped),
  lorebooks (keys, position, depth, constant, probability, per-entry), themes / plain text
- **Export** — copy all text, download as `.md` / `.txt`, with or without parameters
- **Vault** — save a file into the library; each resource keeps **multiple versions** with label,
  note, author date, tags and folders; re-download the original bytes at any time
- **Folders & tags** — folders are created by you (nothing is pre-defined), tags are free text;
  both filter the shelf instantly
- **Shelf / list views**, drag to reorder, cover images for cards (auto-thumbnailed in the browser),
  batch select → move to folder / delete
- **Desktop layout** — on a wide screen the page turns into two columns: a pinned left rail
  (upload, search, collection stats, folders, tags, recent items) and the shelf on the right;
  drop a file anywhere on the page to upload
- **Mobile-first** — works as an installable PWA on iOS / Android
- **Private by default** — HTTP Basic auth built in; ships **empty** (no data of ours inside)

## Quick start

Requires Python 3.9+ (standard library only).

```bash
git clone <this repo> shuzhai && cd shuzhai
SHUZHAI_USER=me SHUZHAI_PASS=change-me python3 server.py
# → http://127.0.0.1:8790
```

Open the address, log in with the user / password you just set, and start dropping files in.

### Docker

```bash
docker compose up -d        # edit the user / password in docker-compose.yml first
```

### systemd (Linux server)

```bash
sudo cp -r . /opt/shuzhai
sudo cp shuzhai.service /etc/systemd/system/   # edit user / password inside
sudo systemctl enable --now shuzhai
```

Put nginx or Caddy in front for HTTPS. Example nginx block:

```nginx
location / {
    proxy_pass http://127.0.0.1:8790;
    proxy_set_header Host $host;
    client_max_body_size 64m;
}
```

Shuzhai uses relative URLs, so it also works under a sub-path (e.g. `/shuzhai/`) as long as the
proxy strips the prefix.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `SHUZHAI_HOST` | `127.0.0.1` | bind address; `0.0.0.0` to expose directly |
| `SHUZHAI_PORT` | `8790` | port |
| `SHUZHAI_DATA` | `./data` | where `vault.db` lives (back this folder up) |
| `SHUZHAI_USER` / `SHUZHAI_PASS` | *(unset)* | when both set, the whole site requires login. **Leave unset only on a private LAN.** |
| `SHUZHAI_MAX_MB` | `64` | max upload size |

All data is a single SQLite file: `data/vault.db`. Copy it to back up, copy it back to restore.

## Notes

- Fonts are loaded from Google Fonts for the nicer serif look; if that CDN is unreachable the page
  falls back to system fonts and keeps working.
- No telemetry, no external calls other than the fonts.
- The frontend is one `static/index.html`; edit it and refresh, nothing to compile.

---

## 中文说明

**书斋**是一个极简的自托管小仓库，专门收纳酒馆（SillyTavern 一类）玩法周边的文件：
**角色卡**（json / png）、**预设**、**世界书**、**美化主题 / CSS**。丢进来就能读成干净的文字，
每一份都能存多个版本，文件夹自己建、标签自己打。

一个 Python 文件加一个 HTML 文件，不用编译，不用装依赖，不用数据库服务。

### 能做什么

- **读**：角色卡（V2 / V3，json 或内嵌数据的 png）、预设（所有 `prompt_order` 表都读，不只第一张，不会漏条目）、世界书（关键词、位置、深度、常驻、概率逐条列出）、主题 / 纯文本
- **导出**：复制全部文字、下载 .md / .txt，带不带参数都行
- **仓库**：存进图书馆，每份资源可挂多个版本（版本号、备注、作者日期、标签、文件夹），随时原样下载
- **文件夹与标签**：文件夹全部由你自己创建，没有任何预置；标签自由填写；两者都能一键筛选
- **书架 / 列表两种视图**，拖动排序，角色卡封面（浏览器内自动缩图），批量选择移动 / 删除
- **电脑版**：宽屏自动变成两栏，左栏钉住（上传、搜索、藏书统计、文件夹、标签、最近放进来），右边是书架；文件拖到页面任何位置都算上传
- **手机优先**：可以"添加到主屏幕"当 PWA 用
- **默认私密**：自带 HTTP Basic 登录；仓库出厂是空的

### 三步跑起来

需要 Python 3.9 以上，不用装任何包。

```bash
git clone <本仓库> shuzhai && cd shuzhai
SHUZHAI_USER=你的用户名 SHUZHAI_PASS=你的密码 python3 server.py
# 打开 http://127.0.0.1:8790
```

Docker：改好 `docker-compose.yml` 里的用户名密码，`docker compose up -d`。
Linux 服务器常驻：把目录放到 `/opt/shuzhai`，`shuzhai.service` 拷进 systemd 改好账号密码，`systemctl enable --now shuzhai`，前面套 nginx / Caddy 做 HTTPS（示例见上方英文部分）。

### 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `SHUZHAI_HOST` | `127.0.0.1` | 监听地址，直接对外可设 `0.0.0.0` |
| `SHUZHAI_PORT` | `8790` | 端口 |
| `SHUZHAI_DATA` | `./data` | 数据目录，`vault.db` 在这里，备份就备这个文件夹 |
| `SHUZHAI_USER` / `SHUZHAI_PASS` | 不设 | 两个都设了整站要登录；**只有在纯内网才可以不设** |
| `SHUZHAI_MAX_MB` | `64` | 上传大小上限 |

所有数据就是一个 SQLite 文件 `data/vault.db`，拷走就是备份，拷回来就是恢复。

### 备注

- 字体从 Google Fonts 加载，拿不到时自动退回系统字体，功能不受影响
- 没有任何统计上报，除字体外不连任何外部服务
- 前端就是 `static/index.html` 一个文件，改完刷新即生效
