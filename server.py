"""tmux 세션 웹 모니터: 세션 목록/상태 조회 + 브라우저 터미널로 접속."""

import asyncio
import fcntl
import json
import os
import pty
import re
import signal
import struct
import termios
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import push
import store
from tmuxctl import capture, list_sessions, session_exists, tmux, valid_name

STATIC_DIR = Path(__file__).parent / "static"
# 서비스 경로 (예: /dev → http://주소/dev/)
BASE_PATH = "/" + os.environ.get("BASE_PATH", "/dev").strip("/")
BASE_PREFIX = BASE_PATH.rstrip("/")  # "/" 일 때는 ""
COOKIE = "tmuxweb_session"
LOOPBACK = {"127.0.0.1", "::1"}
LOCAL_HOST = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
MAX_UPLOAD = 200 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(push.monitor())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
router = APIRouter()


def require_login(request: Request) -> None:
    if not auth.valid_session(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")


# 로그인이 필요한 API 전부
api = APIRouter(prefix="/api", dependencies=[Depends(require_login)])


def client_ip(request: Request) -> str:
    ip = request.client.host if request.client else "?"
    # nginx / Tailscale Serve 등 로컬 리버스 프록시 뒤에서는 실제 클라이언트 IP 사용
    if ip in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        ip = request.headers.get("x-real-ip") or forwarded or ip
    return ip


def is_local(request: Request) -> bool:
    """이 PC에서 직접 접속했는지 (계정 설정/초기화 허용 조건).

    - 실제 연결이 루프백이고, 프록시가 붙인 클라이언트 IP 헤더도 전부 루프백
      (nginx는 X-Real-IP를 덮어쓰고, 다른 프록시는 X-Forwarded-For에 실제 IP를 덧붙임)
    - Host가 localhost/127.0.0.1 → 외부 도메인을 127.0.0.1로 돌리는 DNS 리바인딩 차단
    """
    if not request.client or request.client.host not in LOOPBACK:
        return False
    forwarded = [request.headers.get("x-real-ip", "")] + request.headers.get("x-forwarded-for", "").split(",")
    if any(ip.strip() and ip.strip() not in LOOPBACK for ip in forwarded):
        return False
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    return bool(LOCAL_HOST.match(host)) and (origin is None or origin.split("://", 1)[-1] == host)


def run(*args: str) -> None:
    res = tmux(*args)
    if res.returncode != 0:
        raise HTTPException(400, res.stderr.strip() or "tmux 명령 실패")


def find_session(name: str) -> dict:
    for s in list_sessions():
        if s["name"] == name:
            return s
    raise HTTPException(404, "세션이 없습니다")


# ---------- 페이지 ----------

@router.get("/")
def index(request: Request):
    if not auth.is_configured():
        return RedirectResponse(f"{BASE_PREFIX}/setup")
    if not auth.valid_session(request.cookies.get(COOKIE)):
        return RedirectResponse(f"{BASE_PREFIX}/login")
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/login")
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@router.get("/setup")
def setup_page():
    return FileResponse(STATIC_DIR / "setup.html")


@router.get("/sw.js")
def service_worker():
    # scope가 BASE_PATH/ 전체가 되도록 static/ 이 아닌 경로에서 제공
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/ca.crt")
def ca_certificate():
    # 자체 HTTPS 인증서의 CA (공개 정보). 기기에 설치하면 IP 주소로도 경고 없이 접속됨
    ca = Path(os.environ.get("TMUX_WEB_TLS", "~/.config/tmux-web/tls")).expanduser() / "ca.crt"
    if not ca.exists():
        raise HTTPException(404, "CA 인증서가 없습니다 (deploy/make-cert.sh 실행 필요)")
    return FileResponse(ca, media_type="application/x-x509-ca-cert", filename="tmux-web-ca.crt")


@router.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


# ---------- 로그인 ----------

class Login(BaseModel):
    username: str
    password: str


@router.post("/api/login")
def api_login(body: Login, request: Request, response: Response):
    ip = client_ip(request)
    if not auth.is_configured():
        raise HTTPException(503, "계정이 아직 없습니다. 이 PC에서 계정을 먼저 만드세요")
    if auth.locked_out(ip):
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 5분 후 다시 시도하세요")
    if not auth.verify(body.username, body.password):
        auth.record_fail(ip)
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    https = (
        request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        or request.headers.get("origin", "").startswith("https://")
    )
    response.set_cookie(
        COOKIE,
        auth.create_session(),
        max_age=auth.SESSION_TTL,
        path=f"{BASE_PREFIX}/",
        httponly=True,
        samesite="strict",
        secure=https,
    )
    return {"ok": True}


# ---------- 계정 설정/초기화 (이 PC에서 접속했을 때만) ----------

@router.get("/api/setup")
def api_setup_status(request: Request):
    local = is_local(request)
    return {
        "configured": auth.is_configured(),
        "local": local,
        "username": auth.username() if local else None,
    }


class Setup(BaseModel):
    username: str
    password: str


@router.post("/api/setup")
def api_setup(body: Setup, request: Request):
    if not is_local(request):
        raise HTTPException(403, "계정 설정은 이 PC에서 localhost 주소로 접속했을 때만 가능합니다")
    username = body.username.strip()
    if not username or len(username) > 32 or any(c.isspace() for c in username):
        raise HTTPException(400, "아이디는 공백 없이 1~32자로 입력하세요")
    if len(body.password) < 8:
        raise HTTPException(400, "비밀번호는 8자 이상이어야 합니다")
    auth.set_password(username, body.password)  # 기존 로그인은 모두 해제됨
    return {"ok": True}


@router.post("/api/logout")
def api_logout(request: Request, response: Response):
    auth.drop_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path=f"{BASE_PREFIX}/")
    return {"ok": True}


# ---------- 세션 ----------

@api.get("/sessions")
def api_sessions():
    sessions = list_sessions()
    group_of = store.group_of()
    for s in sessions:
        s["group"] = group_of.get(s["name"])
        st = push.status.get(s["name"], {})
        s["state"] = st.get("state", "")
        s["preview"] = st.get("preview", [])
    return sessions


class NewSession(BaseModel):
    name: str
    cwd: str | None = None
    command: str | None = None  # 만든 뒤 셸에 입력할 명령 (예: claude)


@api.post("/sessions")
def api_create_session(body: NewSession):
    name = body.name.strip()
    if not valid_name(name):
        raise HTTPException(400, "세션 이름이 비어 있거나 '.' ':' 가 들어 있습니다")
    # 폴더를 비우면 홈 폴더 (지정 안 하면 tmux가 웹 서버의 작업 폴더를 쓰게 됨)
    cwd = os.path.expanduser((body.cwd or "").strip() or "~")
    if not os.path.isdir(cwd):
        raise HTTPException(400, f"폴더가 없습니다: {cwd}")
    run("new-session", "-d", "-s", name, "-c", cwd)
    store.add_recent_dir(cwd)
    if body.command and body.command.strip():
        # 셸에 입력하는 방식 → 명령이 끝나도 셸이 남아 세션 유지
        run("send-keys", "-t", f"={name}:", body.command.strip(), "Enter")
    return {"ok": True}


class Rename(BaseModel):
    new_name: str


@api.patch("/sessions/{name}")
def api_rename_session(name: str, body: Rename):
    new = body.new_name.strip()
    if not valid_name(new):
        raise HTTPException(400, "세션 이름이 비어 있거나 '.' ':' 가 들어 있습니다")
    run("rename-session", "-t", f"={name}", new)
    store.rename_session(name, new)
    return {"ok": True}


@api.delete("/sessions/{name}")
def api_kill_session(name: str):
    run("kill-session", "-t", f"={name}")
    store.forget_session(name)
    return {"ok": True}


class Select(BaseModel):
    window: int
    pane: int | None = None


@api.post("/sessions/{name}/select")
def api_select(name: str, body: Select):
    run("select-window", "-t", f"={name}:{body.window}")
    if body.pane is not None:
        run("select-pane", "-t", f"={name}:{body.window}.{body.pane}")
    return {"ok": True}


@api.post("/sessions/{name}/windows")
def api_new_window(name: str):
    s = find_session(name)
    run("new-window", "-t", f"={name}:", "-c", s["path"] or os.path.expanduser("~"))
    return {"ok": True}


@api.get("/sessions/{name}/capture")
def api_capture(name: str, lines: int = 2000):
    s = find_session(name)
    return {"text": capture(s["pane_id"], history=max(0, min(lines, 50000)))}


@api.post("/sessions/{name}/upload")
async def api_upload(name: str, file: UploadFile):
    s = find_session(name)
    folder = Path(s["path"] or os.path.expanduser("~"))
    base = re.sub(r"[/\\\x00]", "_", Path(file.filename or "upload").name).lstrip(".") or "upload"
    dest = folder / base
    stem, suffix, n = dest.stem, dest.suffix, 1
    while dest.exists():  # 덮어쓰지 않도록 이름 뒤에 번호
        dest = folder / f"{stem}-{n}{suffix}"
        n += 1
    size = 0
    try:
        with open(dest, "xb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "파일이 너무 큽니다 (최대 200MB)")
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except OSError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"저장 실패: {e}")
    return {"path": str(dest), "size": size}


# ---------- 그룹 ----------

def valid_group(name: str) -> str:
    name = name.strip()
    if not name or len(name) > 40:
        raise HTTPException(400, "그룹 이름은 1~40자로 입력하세요")
    return name


@api.get("/groups")
def api_groups():
    return list(store.groups())


class GroupName(BaseModel):
    name: str


@api.post("/groups")
def api_create_group(body: GroupName):
    try:
        store.create_group(valid_group(body.name))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class GroupRename(BaseModel):
    new_name: str


@api.patch("/groups/{name}")
def api_rename_group(name: str, body: GroupRename):
    try:
        store.rename_group(name, valid_group(body.new_name))
    except KeyError as e:
        raise HTTPException(404, e.args[0])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@api.delete("/groups/{name}")
def api_delete_group(name: str, kill: bool = False):
    """kill=true 이면 그룹 안 세션도 종료, 아니면 그룹만 없애고 세션은 '그룹 없음'으로."""
    try:
        members = store.delete_group(name)
    except KeyError as e:
        raise HTTPException(404, e.args[0])
    killed, failed = [], []
    if kill:
        existing = {s["name"] for s in list_sessions()}
        for s in members:
            if s not in existing:
                continue
            if tmux("kill-session", "-t", f"={s}").returncode == 0:
                killed.append(s)
            else:
                failed.append(s)
    return {"killed": killed, "failed": failed}


class MoveGroup(BaseModel):
    group: str | None  # None → 그룹 없음


@api.put("/sessions/{name}/group")
def api_move_session(name: str, body: MoveGroup):
    try:
        store.move_session(name, body.group)
    except KeyError as e:
        raise HTTPException(404, e.args[0])
    return {"ok": True}


# ---------- 설정 (명령 버튼 / 폴더 추천) ----------

class Config(BaseModel):
    snippets: list[str]


@api.get("/config")
def api_config():
    return store.load_config()


@api.put("/config")
def api_save_config(body: Config):
    cfg = store.load_config()
    cfg["snippets"] = [s for s in (x.strip() for x in body.snippets) if s][:50]
    store.save_config(cfg)
    return cfg


@api.get("/dirs")
def api_dirs():
    home = Path.home()
    candidates = list(store.load_config()["recent_dirs"])
    candidates += [s["path"] for s in list_sessions() if s["path"]]
    for parent in (home / "Workspace", home / "dev", home):
        if parent.is_dir():
            candidates += sorted(str(p) for p in parent.iterdir() if p.is_dir() and not p.name.startswith("."))
    seen, dirs = set(), []
    for d in candidates:
        if d not in seen and os.path.isdir(d):
            seen.add(d)
            dirs.append(d)
    return dirs[:60]


# ---------- 푸시 알림 ----------

@api.get("/push/key")
def api_push_key():
    return {"key": push.public_key()}


class Subscription(BaseModel):
    endpoint: str
    keys: dict[str, str]


@api.post("/push/subscribe")
def api_push_subscribe(sub: Subscription):
    push.subscribe(sub.model_dump())
    return {"ok": True}


class Unsubscribe(BaseModel):
    endpoint: str


@api.post("/push/unsubscribe")
def api_push_unsubscribe(body: Unsubscribe):
    push.unsubscribe(body.endpoint)
    return {"ok": True}


@api.post("/push/test")
def api_push_test():
    return {"sent": push.send_all("🔔 tmux 모니터", "알림이 정상적으로 설정되었습니다")}


router.include_router(api)


# ---------- 터미널 WebSocket ----------

def set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def scroll_pane(name: str, lines: int, cols: int, rows: int) -> bytes:
    """lines > 0: 위로(과거), < 0: 아래로.

    앱이 마우스를 받는 경우(Claude Code 전체화면 등 자체 스크롤): 휠 이벤트 바이트를 반환 → pty로 전달.
    그 외(일반 셸): tmux copy-mode로 히스토리 스크롤. 맨 아래까지 내리면 자동 종료(-e).
    """
    target = f"={name}:"
    flags = tmux("display", "-p", "-t", target,
                 "#{pane_in_mode} #{mouse_standard_flag}#{mouse_button_flag}#{mouse_any_flag} #{mouse_sgr_flag}").stdout.split()
    in_mode, wants_mouse, sgr = flags[0] == "1", "1" in flags[1], flags[2] == "1"
    if wants_mouse and not in_mode:
        button = 64 if lines > 0 else 65  # 휠 위/아래
        col, row = max(cols // 2, 1), max(rows // 2, 1)
        if sgr:
            event = f"\x1b[<{button};{col};{row}M".encode()
        else:  # 구형 X10 마우스 형식
            event = b"\x1b[M" + bytes([32 + button, 32 + min(col, 223), 32 + min(row, 223)])
        return event * min(abs(lines), 30)
    if lines > 0:
        tmux("copy-mode", "-e", "-t", target)
    tmux("send-keys", "-t", target, "-X", "-N", str(min(abs(lines), 200)),
         "scroll-up" if lines > 0 else "scroll-down")
    return b""


def origin_allowed(ws: WebSocket) -> bool:
    # 다른 사이트의 페이지가 브라우저를 통해 localhost 셸에 붙는 것을 방지
    origin = ws.headers.get("origin")
    host = ws.headers.get("host")
    return origin is None or origin.split("://", 1)[-1] == host


@router.websocket("/ws/{name}")
async def ws_attach(ws: WebSocket, name: str):
    if not origin_allowed(ws):
        await ws.close()  # 핸드셰이크 단계에서 403 거부
        return
    # accept 후에 닫아야 브라우저가 close code(4401/4404)를 받을 수 있음
    await ws.accept()
    if not auth.valid_session(ws.cookies.get(COOKIE)):
        await ws.close(code=4401)
        return
    if not session_exists(name):
        await ws.close(code=4404)
        return

    pid, fd = pty.fork()
    if pid == 0:  # child: tmux 클라이언트로 attach
        os.environ["TERM"] = "xterm-256color"
        os.environ.pop("TMUX", None)
        os.execvp("tmux", ["tmux", "-u", "attach-session", "-t", f"={name}"])

    loop = asyncio.get_running_loop()
    output: asyncio.Queue[bytes | None] = asyncio.Queue()

    def on_readable():
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if not data:
            loop.remove_reader(fd)
            output.put_nowait(None)
        else:
            output.put_nowait(data)

    loop.add_reader(fd, on_readable)

    async def pump_output():
        while (data := await output.get()) is not None:
            await ws.send_bytes(data)
        await ws.close()

    sender = asyncio.create_task(pump_output())
    size = (80, 24)
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg["type"] == "input":
                os.write(fd, msg["data"].encode())
            elif msg["type"] == "resize":
                size = (int(msg["cols"]), int(msg["rows"]))
                set_winsize(fd, size[1], size[0])
            elif msg["type"] == "ping":  # 연결 살아있는지 확인용 → 빈 프레임으로 응답
                output.put_nowait(b"")
            elif msg["type"] == "scroll":  # 모바일 스와이프: tmux copy-mode로 히스토리 스크롤
                wheel = await loop.run_in_executor(None, scroll_pane, name, int(msg["lines"]), *size)
                if wheel:
                    os.write(fd, wheel)
            elif msg["type"] == "scroll-exit":
                await loop.run_in_executor(None, tmux, "send-keys", "-t", f"={name}:", "-X", "cancel")
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        sender.cancel()
        loop.remove_reader(fd)
        # tmux 클라이언트만 종료 → 세션은 그대로 유지(detach와 동일)
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        os.close(fd)
        await loop.run_in_executor(None, os.waitpid, pid, 0)


app.include_router(router, prefix=BASE_PREFIX)
app.mount(f"{BASE_PREFIX}/static", StaticFiles(directory=STATIC_DIR), name="static")

if BASE_PATH != "/":

    @app.get("/")
    @app.get(BASE_PATH)
    def redirect_to_base():
        return RedirectResponse(BASE_PATH + "/")


if __name__ == "__main__":
    import sys

    import uvicorn

    if not auth.is_configured():
        port_ = os.environ.get("PORT", "8765")
        print(f"로그인 계정이 없습니다. 이 PC의 브라우저에서 http://localhost:{port_}{BASE_PREFIX}/setup 을 열어 만드세요",
              file=sys.stderr)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host=host, port=port)
