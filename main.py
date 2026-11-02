from __future__ import annotations

import base64
import datetime as dt
import gc
import hashlib
import json
import math
import multiprocessing
import os
import platform
import queue
import random
import re
import signal
import string
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import quote

try:
    from curl_cffi.requests import Session as CurlSession
    HAS_CURL = True
except ImportError:
    CurlSession = None
    HAS_CURL = False

try:
    import tls_client
    HAS_TLS = True
except ImportError:
    tls_client = None
    HAS_TLS = False

try:
    import requests as std_requests
except ImportError:
    std_requests = None

if not HAS_CURL and not HAS_TLS and std_requests is None:
    print("Missing dependencies. Run: py -m pip install curl_cffi requests tls_client")
    sys.exit(1)

APP_NAME = "sniper"
DISCORD_PATH = "/api/v9/unique-username/username-attempt-unauthed"
CLAIM_PATH = "/api/v9/users/@me"
HOSTS = ["https://discord.com", "https://canary.discord.com", "https://ptb.discord.com"]

RESULTS_FILE = "available.txt"
PROXY_FILE = "proxies.txt"
APP_DIR = "sniper"
SETTINGS_FILE = "settings.json"

MIN_CPS = 500.0
MAX_CPS = 5000.0
DEFAULT_CPS = 500.0

SESSION_MAX_REQ = 200
PROXY_COOLDOWN = 5.0
MIN_WORKERS = 100
MAX_WORKERS = 400
WORKER_FACTOR = 1.5

RETRY_ATTEMPTS = 8
ERR_PAUSE = 0.020
PACER_TICK = 0.003
MAX_PROCS = 4

CLAIM_TIMEOUT = 15.0
CLAIM_CLIENT_VER = "1.0.9206"
CLAIM_BUILD = 355624
CLAIM_NATIVE = 51951

ANTICAPTCHA_URL = "https://api.anti-captcha.com/createTask"
ANTICAPTCHA_RES = "https://api.anti-captcha.com/getTaskResult"
ANTICAPTCHA_BAL = "https://api.anti-captcha.com/getBalance"

LOWERCASE = string.ascii_lowercase
DIGITS = string.digits
ALNUM = LOWERCASE + DIGITS

IMPERSONATE = [
    "chrome99", "chrome100", "chrome101", "chrome104", "chrome107",
    "chrome110", "chrome116", "chrome119", "chrome120", "chrome123",
    "safari15_3", "safari15_5", "safari17_0", "safari17_2_ios",
    "firefox133",
]

RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
WHITE = "\033[97m"
GREY = "\033[90m"
BOLD = "\033[1m"
DIM = "\033[2m"
ACCENT = BLUE
ACCENT2 = BLUE

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BOX_WIDTH = 58

# ---------------------------------------------------------------------------
# UI HELPERS
# ---------------------------------------------------------------------------
def char_width(c: str) -> int:
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)

def vis_len(s: str) -> int:
    return sum(char_width(c) for c in strip_ansi(s))

def truncate_ansi(s: str, width: int) -> str:
    if width <= 0: return ""
    out, vis, i, n = [], 0, 0, len(s)
    while i < n:
        c = s[i]
        if c == "\x1b":
            j = i + 1
            if j < n and s[j] == "[":
                j += 1
                while j < n and not ("@" <= s[j] <= "~"): j += 1
                if j < n: j += 1
                out.append(s[i:j])
                i = j
                continue
            i += 1
            continue
        w = char_width(c)
        if vis + w > width: break
        out.append(c)
        vis += w
        i += 1
    return "".join(out)

def pad_str(s: str, width: int) -> str:
    v = vis_len(s)
    if v > width:
        s = truncate_ansi(s, width)
        v = vis_len(s)
    return s + " " * (width - v)

def fit_str(s: str, width: int) -> str:
    if vis_len(s) <= width: return s
    if width <= 1: return truncate_ansi(s, width)
    return truncate_ansi(s, width - 1) + "."

def clear_screen() -> None:
    try:
        sys.stdout.write("\033[2J\033[3J\033[H")
        sys.stdout.flush()
    except Exception:
        os.system("cls" if os.name == "nt" else "clear")

def setup_console() -> None:
    if os.name == "nt":
        os.system("")
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            m = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(m)):
                k.SetConsoleMode(h, m.value | 0x0004)
            k.SetConsoleTitleW(APP_NAME)
            class COORD(ctypes.Structure):
                _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]
            class SMALL_RECT(ctypes.Structure):
                _fields_ = [
                    ("Left", ctypes.c_short), ("Top", ctypes.c_short),
                    ("Right", ctypes.c_short), ("Bottom", ctypes.c_short),
                ]
            k.SetConsoleScreenBufferSize(h, COORD(100, 40))
            rect = SMALL_RECT(0, 0, 99, 39)
            k.SetConsoleWindowInfo(h, True, ctypes.byref(rect))
        except Exception:
            pass

def print_top() -> None:
    print(f"  {ACCENT}+{'-' * BOX_WIDTH}+{RESET}", flush=True)

def print_bottom() -> None:
    print(f"  {ACCENT}+{'-' * BOX_WIDTH}+{RESET}", flush=True)

def print_row(content: str = "") -> None:
    print(f"  {ACCENT}|{RESET}{pad_str(content, BOX_WIDTH)}{ACCENT}|{RESET}", flush=True)

def print_blank() -> None:
    print(f"  {ACCENT}|{' ' * BOX_WIDTH}|{RESET}", flush=True)

def get_art() -> list:
    return [
        "███████╗███╗   ██╗██╗██████╗ ███████╗██████╗ ██████╗ ",
        "██╔════╝████╗  ██║██║██╔══██╗██╔════╝██╔══██╗██╔══██╗",
        "███████╗██╔██╗ ██║██║██████╔╝█████╗  ██████╔╝██████╔╝",
        "╚════██║██║╚██╗██║██║██╔═══╝ ██╔══╝  ██╔══██╗██╔══██╗",
        "███████║██║ ╚████║██║██║     ███████╗██║  ██║██║  ██║",
        "╚══════╝╚═╝  ╚═══╝╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝",
    ]

def print_banner() -> None:
    art_w = 54
    indent = "   "
    print()
    print(f"  {BLUE}{'═' * 60}{RESET}")
    print()
    for line in get_art():
        print(f"{indent}{BOLD}{BLUE}{line}{RESET}")
    print()
    print(f"{indent}{GREY}" + "C H E C K E R".center(art_w) + f"{RESET}")
    print(f"{indent}{DIM}{GREY}" + "by Caennais".center(art_w) + f"{RESET}")
    print()
    print(f"  {BLUE}{'═' * 60}{RESET}")
    print()

def get_base_dir() -> Path:
    try:
        cand = Path(sys.argv[0]).resolve()
        if cand.is_file(): return cand.parent
    except Exception: pass
    try:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
    except Exception: pass
    return Path(__file__).resolve().parent

def get_valid_dir() -> Path:
    app_data = os.getenv('APPDATA') or os.path.expanduser('~')
    d = Path(app_data) / APP_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception: pass
    d = get_base_dir() / APP_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception: pass
    return get_base_dir()

def hide_path(p: Path) -> None:
    if os.name != "nt": return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x2)
    except Exception: pass

def get_settings_path() -> Path:
    return get_valid_dir() / SETTINGS_FILE

# ---------------------------------------------------------------------------
# SETTINGS PERSISTENCE (no license)
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    timeout_ms: int = 2500
    proxies: str = ""
    webhook: str = ""
    mode: str = "4c_smart"
    target_cps: float = DEFAULT_CPS
    show_taken: bool = True
    autoclaim_enabled: bool = True
    autoclaim_token: str = ""
    autoclaim_password: str = ""
    autoclaim_stop_on_claim: bool = True
    anticaptcha_key: str = ""
    anticaptcha_enabled: bool = True

    def sanitize(self):
        self.timeout_ms = max(900, min(8000, int(self.timeout_ms or 2500)))
        self.target_cps = max(MIN_CPS, min(MAX_CPS, float(self.target_cps or DEFAULT_CPS)))
        self.webhook = str(self.webhook or "").strip()
        self.proxies = str(self.proxies or "")
        self.autoclaim_token = clean_token(self.autoclaim_token)
        self.autoclaim_password = str(self.autoclaim_password or "")
        self.anticaptcha_key = str(self.anticaptcha_key or "").strip()
        if self.mode not in MODE_BY_ID:
            self.mode = next(iter(MODE_BY_ID))
        return self

def load_settings() -> Settings:
    p = get_settings_path()
    if not p.exists():
        return Settings()
    try:
        with open(p, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return Settings(**{
                k: v for k, v in data.items()
                if k in Settings.__dataclass_fields__
            }).sanitize()
    except Exception:
        pass
    return Settings()

def save_settings(settings: Settings) -> None:
    p = get_settings_path()
    try:
        with open(p, "w") as f:
            json.dump(asdict(settings.sanitize()), f)
        hide_path(p)
    except Exception:
        pass

TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-\.]+$")

def clean_token(raw: str) -> str:
    if raw is None: return ""
    t = "".join(
        ch for ch in raw
        if ch.isprintable() and not ch.isspace()
        and ch not in "\ufeff\u200b\u200c\u200d"
    )
    return t.strip().strip('"\'')

def looks_like_token(token: str) -> bool:
    t = clean_token(token)
    if not t or not TOKEN_RE.match(t): return False
    parts = t.split(".")
    if len(parts) != 3: return False
    return all(len(p) >= 6 for p in parts)

def mask_token(tok: str) -> str:
    if not tok: return "-"
    if len(tok) <= 16: return tok
    return f"{tok[:10]}...{tok[-6:]}"

def mask_apikey(key: str) -> str:
    if not key: return "-"
    if len(key) <= 10: return key
    return f"{key[:4]}...{key[-4:]}"

UA_POOL = [
    ("Windows NT 10.0; Win64; x64", "Windows", "10.0.22631", "x64", "120"),
    ("Windows NT 10.0; Win64; x64", "Windows", "10.0.19045", "x64", "123"),
    ("Windows NT 10.0; Win64; x64", "Windows", "10.0.22631", "x64", "126"),
    ("Windows NT 10.0; Win64; x64", "Windows", "10.0.22631", "x64", "131"),
    ("Macintosh; Intel Mac OS X 10_15_7", "Mac OS X", "14.4.1", "arm64", "120"),
    ("Macintosh; Intel Mac OS X 10_15_7", "Mac OS X", "15.0", "arm64", "131"),
    ("X11; Linux x86_64", "Linux", "6.5.0", "x64", "120"),
]
LOCALE_POOL = ["en-US", "en-GB", "en-CA", "en-AU"]
TZ_POOL = [
    "America/New_York", "America/Chicago", "America/Los_Angeles",
    "Europe/London", "Europe/Berlin", "Asia/Tokyo", "Australia/Sydney",
]

CLAIM_CTX = None

def gen_inst_id() -> str: return str(uuid.uuid4())
def gen_launch_sig() -> str: return base64.b64encode(os.urandom(16)).decode().rstrip("=")

def rotating_fp():
    ua_seg, os_name, os_version, os_arch, chrome_major = random.choice(UA_POOL)
    locale = random.choice(LOCALE_POOL)
    tz = random.choice(TZ_POOL)
    return {
        "ua_seg": ua_seg, "os_name": os_name, "os_version": os_version,
        "os_arch": os_arch, "chrome_major": chrome_major,
        "locale": locale, "tz": tz,
    }

def build_super_props(host: str, fp: dict) -> str:
    if "canary" in host: channel = "canary"
    elif "ptb" in host: channel = "ptb"
    else: channel = "stable"
    props = {
        "os": fp["os_name"], "browser": "Discord Client", "release_channel": channel,
        "client_version": f"1.0.{random.randint(9150, 9250)}",
        "os_version": fp["os_version"], "os_arch": fp["os_arch"],
        "system_locale": fp["locale"], "client_build_number": random.randint(270000, 285000),
        "native_build_number": random.randint(43000, 47000), "client_event_source": None,
        "launch_signature": gen_launch_sig(), "installation_id": gen_inst_id(),
    }
    raw = json.dumps(props, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")

def build_x_fp(fp: dict) -> str:
    xfp = {
        "os": fp["os_name"], "browser": "Discord Client", "release_channel": "stable",
        "client_version": f"1.0.{random.randint(9150, 9250)}",
        "os_version": fp["os_version"], "os_arch": fp["os_arch"],
        "system_locale": fp["locale"], "client_build_number": random.randint(270000, 285000),
        "native_build_number": random.randint(43000, 47000),
    }
    raw = json.dumps(xfp, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")

def build_headers(host: str) -> dict:
    fp = rotating_fp()
    cm = fp["chrome_major"]
    sec_platform = (
        "Windows" if fp["os_name"] == "Windows"
        else "macOS" if fp["os_name"] == "Mac OS X"
        else "Linux"
    )
    return {
        "accept": "*/*", "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": f"{fp['locale']},en;q=0.9",
        "cache-control": "no-cache", "content-type": "application/json",
        "origin": "https://discord.com", "pragma": "no-cache", "priority": "u=1, i",
        "referer": "https://discord.com/channels/@me",
        "sec-ch-ua": f'"Google Chrome";v="{cm}", "Chromium";v="{cm}", "Not(A:Brand";v="24"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": f'"{sec_platform}"',
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin", "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": f"Mozilla/5.0 ({fp['ua_seg']}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{cm}.0.0.0 Safari/537.36",
        "x-debug-options": "bugReporterEnabled", "x-discord-locale": fp["locale"],
        "x-discord-timezone": fp["tz"], "x-super-properties": build_super_props(host, fp),
        "x-fingerprint": build_x_fp(fp),
    }

def claim_ctx():
    global CLAIM_CTX
    if CLAIM_CTX is None:
        fp = rotating_fp()
        props = {
            "os": fp["os_name"], "browser": "Discord Client", "release_channel": "stable",
            "client_version": CLAIM_CLIENT_VER, "os_version": fp["os_version"],
            "os_arch": fp["os_arch"], "system_locale": fp["locale"],
            "client_build_number": CLAIM_BUILD, "native_build_number": CLAIM_NATIVE,
            "client_event_source": None, "launch_signature": gen_launch_sig(),
            "installation_id": gen_inst_id(),
        }
        xfp = {
            "os": fp["os_name"], "browser": "Discord Client", "release_channel": "stable",
            "client_version": CLAIM_CLIENT_VER, "os_version": fp["os_version"],
            "os_arch": fp["os_arch"], "system_locale": fp["locale"],
            "client_build_number": CLAIM_BUILD, "native_build_number": CLAIM_NATIVE,
        }
        sp = base64.b64encode(json.dumps(props, separators=(",", ":")).encode("utf-8")).decode("ascii")
        xf = base64.b64encode(json.dumps(xfp, separators=(",", ":")).encode("utf-8")).decode("ascii")
        ua_seg = fp["ua_seg"]
        cm = fp["chrome_major"]
        sec_platform = (
            "Windows" if fp["os_name"] == "Windows"
            else "macOS" if fp["os_name"] == "Mac OS X"
            else "Linux"
        )
        CLAIM_CTX = {
            "user-agent": f"Mozilla/5.0 ({ua_seg}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{cm}.0.0.0 Safari/537.36",
            "x-super-properties": sp, "x-fingerprint": xf,
            "x-discord-locale": fp["locale"], "x-discord-timezone": fp["tz"],
            "sec-ch-ua": f'"Google Chrome";v="{cm}", "Chromium";v="{cm}", "Not(A:Brand";v="24"',
            "sec-ch-ua-platform": f'"{sec_platform}"', "accept-language": f"{fp['locale']},en;q=0.9",
        }
    return CLAIM_CTX

def token_headers(token: str, host: str = "https://discord.com") -> dict:
    ctx = claim_ctx()
    return {
        "accept": "*/*", "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": ctx["accept-language"], "cache-control": "no-cache",
        "content-type": "application/json", "origin": "https://discord.com",
        "pragma": "no-cache", "priority": "u=1, i", "referer": "https://discord.com/channels/@me",
        "sec-ch-ua": ctx["sec-ch-ua"], "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": ctx["sec-ch-ua-platform"], "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1", "upgrade-insecure-requests": "1",
        "user-agent": ctx["user-agent"], "x-debug-options": "bugReporterEnabled",
        "x-discord-locale": ctx["x-discord-locale"], "x-discord-timezone": ctx["x-discord-timezone"],
        "x-super-properties": ctx["x-super-properties"], "x-fingerprint": ctx["x-fingerprint"],
        "authorization": token,
    }

def anticaptcha_req(url: str, payload: dict, timeout: float = 30.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "User-Agent": "sniperr/1.0"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as he:
            try: return json.loads(he.read().decode("utf-8", "replace"))
            except Exception: return {"errorId": -1, "errorDescription": f"HTTP {he.code}"}
    except Exception as e:
        return {"errorId": -1, "errorDescription": f"{type(e).__name__}: {str(e)[:120]}"}

def anticaptcha_balance(api_key: str) -> tuple:
    key = (api_key or "").strip()
    if not key or len(key) < 20: return False, "key looks too short"
    resp = anticaptcha_req(ANTICAPTCHA_BAL, {"clientKey": key}, timeout=8.0)
    if resp.get("errorId") and resp.get("errorId") != 0:
        return False, resp.get("errorDescription", "invalid key")
    bal = resp.get("balance")
    if bal is None: return False, "no balance field returned"
    try: return True, f"balance ${float(bal):.4f}"
    except Exception: return True, f"balance {bal}"

def anticaptcha_solve(api_key: str, sitekey: str, url: str, rqdata: str = "", user_agent: str = "", timeout: int = 180, max_bid: float = 0.005) -> tuple:
    key = (api_key or "").strip()
    if not key: return False, "no api key"
    if not sitekey: return False, "no sitekey"
    task = {"type": "HCaptchaTaskProxyless", "websiteURL": url, "websiteKey": sitekey}
    if rqdata: task["enterprisePayload"] = {"rqdata": rqdata}
    if user_agent: task["userAgent"] = user_agent
    submit_body = {"clientKey": key, "task": task, "softId": 0, "maxBid": max_bid}
    deadline = time.monotonic() + timeout
    last_err = "unknown"
    while time.monotonic() < deadline:
        create = anticaptcha_req(ANTICAPTCHA_URL, submit_body, timeout=15.0)
        err_desc = str(create.get("errorDescription", ""))
        if create.get("errorId") and ("idle workers" in err_desc.lower() or "try a bit later" in err_desc.lower() or "service unavailable" in err_desc.lower()):
            last_err = err_desc; time.sleep(20.0); continue
        if create.get("errorId") and create.get("errorId") != 0: return False, err_desc or "create failed"
        task_id = create.get("taskId")
        if not task_id: last_err = "no taskId returned"; time.sleep(5.0); continue
        poll_deadline = min(deadline, time.monotonic() + 150.0)
        while time.monotonic() < poll_deadline:
            time.sleep(3.0)
            res = anticaptcha_req(ANTICAPTCHA_RES, {"clientKey": key, "taskId": task_id}, timeout=15.0)
            rerr = str(res.get("errorDescription", ""))
            if res.get("errorId") and ("idle workers" in rerr.lower() or "service unavailable" in rerr.lower()): break
            if res.get("errorId") and res.get("errorId") != 0: last_err = rerr or "poll failed"; break
            if res.get("status") == "ready":
                sol = res.get("solution", {})
                tok = sol.get("gRecaptchaResponse") or sol.get("token")
                if tok: return True, tok
                last_err = "solver returned empty token"; break
        else: last_err = "poll timed out for this task"; break
        time.sleep(5.0)
    return False, last_err

def decode_base(index: int, charset: str, length: int) -> str:
    base = len(charset)
    chars = [charset[0]] * length
    for pos in range(length - 1, -1, -1):
        index, rem = divmod(index, base)
        chars[pos] = charset[rem]
    return "".join(chars)

def decode_semi(idx: int, seps: str, body_len: int, charset: str) -> str:
    per_sep = (body_len + 1) * (len(charset) ** body_len)
    sep_idx, rest = divmod(idx, per_sep)
    pos, body_idx = divmod(rest, len(charset) ** body_len)
    body = decode_base(body_idx, charset, body_len)
    chars = list(body)
    chars.insert(pos, seps[sep_idx])
    return "".join(chars)

SHORT_WORD_BLOB = (
    "acidaeroagedallyapexarchariaatomauraaxisbanebeambetabiteblipblurboltbrimbyte"
    "calmcavecharclawcodecoldcorecosycrowdawndazedeckdripduskechoedgeepicfangfern"
    "fluxfoamgaleglowgridgrimhalohazehushirisjadejoltkilokitelarklavalimelinkluna"
    "lynxmacemintmistmusemythnavyneonnovaonyxopalpalepeakplumrainriftsagesilksnow"
    "solostarstemtidevoidwavewispwolfxenoyarnyetizealzerozinczonearilbuhrcymafane"
    "ilexixiajapekelpkithlinnrimewoadyarefardfoudhylekamemiltuveafirn"
)
SHORT_WORDS = [SHORT_WORD_BLOB[i:i + 4] for i in range(0, len(SHORT_WORD_BLOB), 4)]

RARE_WORD_BLOB = (
    "amberazureemberfablefrostorbitpixelpulsequillslatesparkabysmadretaegisaglet"
    "alateamiceanileapianarborardorargotaskewattarauricazothbardobezelbightbohea"
    "boricbrumecairncalyxchertchirkcivetcladeclarycoigndightdongadrossducaleagree"
    "clateduceelideenvoiergotetweefetorfirthflumefrondgamicgaultghyllglebeglume"
    "goralgrithguyothalerhelvehilumhouriicticinurnjabotjorumkedgeknurllaitylathyl"
    "emanlumenmaclemaundmerlemurexnacrenivalnonceockerogiveorlopoxterpavidpewit"
    "pingoplicaprillquernquoinratalroblesakersalepscurfsepalshawmsilexsizarskirl"
    "soughstoupswaletargetigontopertronaulemaumbelurialvaticvelarvireowhealwight"
    "xeniczayinzebeczonda"
)
RARE_WORDS = [RARE_WORD_BLOB[i:i + 5] for i in range(0, len(RARE_WORD_BLOB), 5)]

OBSCURE_WORD_BLOB = (
    "abditablowaboonabsitacmicaduncaegiraiveralbeealephalgidalureambitamoleanelean"
    "entannalanomyarameargalarlesaroidasconascusaulicavensavisoaxileazidebairnbalky"
    "bardebaricbassibattubawtybeanobedelbeedibemixbermebirleblateblawnblentblore"
    "boartbocceboffobolarbonceboralbortyboskybractbramebromebunducadgecairdcalky"
    "camuscavieceorlceredchapechirmchirtchylecimarclepeclourcoblecogoncoombcozen"
    "crakecreelcronkcruseculchculetcusecdavitdeavedeedydemitdizendobladoorndoura"
    "dowiedrantdreckdunamealedephoretapeettlefanalfaughfeuarflaryfleamfliskflong"
    "flotaforbyfrapefrithfuglegallyganevgawkygibusgimelgiponglairgleetgliskgopak"
    "gricegromagrykegurshhainthamalhaughhaverhelothormehoughinklejagerjambujiber"
    "juralkabobkaiakkalamkepiskirbykvasslairdlanailarumlaverleachlearylimenlorel"
    "lurrymaficmalicmargemashymesicmoraemowramucidmungonairunaresnievenogalnooky"
    "oaredoctadodyleollavopineorpinottarpangapannepareupavispeerypeisepiculpisky"
    "pleonpraamproemquirtrabatraneerenterhemerhyneriantronderubleruchesabalsagum"
    "samelscaupsegarselahsengiseracshielsmazesnecksnoodsorelspeansteddstirksward"
    "tabortawietentythirltichytorsktrullulnarunlayvarecvenalvinalvolarwackewaled"
    "wealdwiddywirrawurstxylanyamenyapokyestyzabrazibetzillszoril"
)
OBSCURE_WORDS = [OBSCURE_WORD_BLOB[i:i + 5] for i in range(0, len(OBSCURE_WORD_BLOB), 5)]
ALL_WORDS = list(dict.fromkeys(SHORT_WORDS + RARE_WORDS + OBSCURE_WORDS))

POOL_A = (
    "north south east west upper lower inner outer red blue black white green gold "
    "silver pink purple orange gray grey brown cyan teal navy lime mint coral ruby "
    "jade pearl ivory onyx amber cherry copper bronze indigo violet dawn dusk morning "
    "evening night day noon midnight sunrise sunset twilight summer winter spring autumn "
    "wild calm cool warm cold hot fresh old new young sharp smooth rough soft hard "
    "quick slow fast bright dark dull clear foggy cloudy sunny stormy quiet loud silent "
    "roaring sky sea ocean coast river lake forest wood tree leaf stone rock sand snow "
    "rain wind storm cloud sun moon star fire water ice earth mountain hill valley canyon "
    "desert cliff cave spring tide wave thunder lightning breeze mist frost hail drizzle "
    "flood drought blizzard tornado hurricane monsoon cyclone peace joy love hope dream "
    "fear brave kind pride rage fury soul spirit ghost mercy grace honor glory faith trust "
    "truth memory secret whisper promise fate destiny karma fall rise run walk jump fly "
    "swim dive climb break crack burn glow shine spark hit kick punch slash cut chop slice "
    "dash sprint chase hunt seek find keep lose sword shield crown ring gem coin book key "
    "lock door gate wall tower bridge road path trail camp tent hut house home castle "
    "throne spear bow arrow axe hammer dagger blade helm armor cloak robe mask glove boot "
    "belt wolf fox bear lion tiger eagle hawk crow raven owl snake shark whale deer elk "
    "moose hare rabbit mouse cat dog lynx panther leopard jaguar puma boar stag"
).split()

POOL_B = (
    "town city village hamlet fort keep manor hall temple shrine church market port "
    "harbor dock bay cove inlet isle head hand foot arm leg eye ear nose mouth tooth "
    "claw fang wing tail horn steel iron brass copper glass cloth silk wool leather "
    "paper clay one two three four five six seven eight nine ten comet meteor planet "
    "orbit galaxy nebula cosmos ether void abyss zenith horizon aurora eclipse solstice "
    "rifle pistol cannon mortar mine bomb grenade missile rocket sniper scope trigger "
    "bullet shell song tune beat rhythm chord melody anthem hymn chorus verse pixel "
    "byte code chip data cyber crypto laser radar signal circuit matrix nexus vector "
    "blaze ash smoke dust mud thorn ivy moss fern reed vine root bark branch seed "
    "flower petal bloom berry fruit apple grape lemon peach plum pear bite drink eat "
    "sleep wake sing dance play laugh cry shout yell scream talk speak listen hear see "
    "look watch search explore wander happy sad angry tired hungry thirsty sleepy awake "
    "alive dead real fake true false good bad evil holy clean dirty rich poor wise"
).split()

POOL_C = (
    "shadow phantom specter wraith banshee revenant sorrow bliss chaos infinite "
    "infinity eternity forever always never mystic magical sacred holy divine cursed "
    "blessed gaming gamer player gamemaster gameover epic legend legendary mythical "
    "mythic mythos alpha beta gamma delta omega sigma theta lambda victory triumph "
    "defeat glory shame puzzle riddle mystery enigma cipher wanderlust adventure "
    "quest voyage expedition harmony melody tempo tune silence echo murmur hum buzz "
    "phoenix dragon unicorn griffin pegasus sphinx cyberpunk neon chrome vapor synth "
    "retro future cosmic starlight moonlight twilight hunter tracker ranger scout "
    "explorer pioneer warrior fighter boxer wrestler samurai ninja shinobi sailor "
    "pirate captain admiral commander general knight paladin templar crusader guardian "
    "warden wizard mage sorcerer warlock enchanter conjurer bard minstrel troubadour "
    "poet artist painter monk priest cleric bishop cardinal pope king queen prince "
    "princess royal noble emperor empress smith mason weaver tanner tailor baker "
    "butcher doctor healer medic physician surgeon nurse teacher scholar student pupil "
    "master apprentice thief rogue bandit outlaw smuggler spy agent assassin marksman "
    "scout spirit soul essence being entity presence velocity momentum gravity inertia "
    "entropy cosmos void zenith abyss eternity infinity"
).split()

COMBO_WORDS = list(dict.fromkeys(POOL_A + POOL_B + POOL_C))
DICTIONARY_WORDS = list(dict.fromkeys(POOL_A + POOL_B + POOL_C))

MODE_POOL = [
    ("4c_smart", "4C", "q7m2"), ("3c", "3C", "v0m"),
    ("semi_3c", "Semi 3C", "a.7x / a_7x"), ("semi_2c", "Semi 2C", "_.s4 / .b2_"),
    ("4L", "4L", "abcd"), ("4n", "4N", "1234"), ("5n", "5N", "12345"),
    ("semi_4n", "Semi 4N", "1.234 / 12_34"), ("semi_3n", "Semi 3N", "1.23 / 4_56"),
    ("word_sep", "Word + . / _", "lumen_ / .lumen"), ("word_join", "Word pairs", "eastcoast / firefly"),
    ("word_dict", "Big dictionary", "dragon / phoenix"),
]

MODE_SHUFFLED = list(MODE_POOL)
random.SystemRandom().shuffle(MODE_SHUFFLED)

MODE_MAP = {str(i + 1): entry for i, entry in enumerate(MODE_SHUFFLED)}
MODE_BY_ID = {v[0]: v for v in MODE_MAP.values()}

class NameGen:
    def __init__(self, mode: str, seed: Optional[int] = None):
        self.mode = mode
        self.rng = random.Random(seed if seed is not None else random.SystemRandom().getrandbits(64))
        self.total = self.calc_total()
        self.counter = self.rng.randrange(0, self.total)
        self.bits = max(1, (self.total - 1).bit_length())
        self.mask = (1 << self.bits) - 1
        self.rounds = []
        for _ in range(8):
            self.rounds.append((
                self.rng.randrange(1, self.mask + 1) | 1,
                self.rng.randrange(0, self.mask + 1),
                self.rng.randint(1, max(1, self.bits - 1)),
                self.rng.randint(1, max(1, self.bits - 1)),
            ))
        self.lock = threading.Lock()

    def calc_total(self) -> int:
        m = self.mode
        n = len(ALNUM)
        if m == "4c_smart":   return n ** 4
        if m == "3c":         return n ** 3
        if m == "semi_3c":    return 4 * 2 * (n ** 3)
        if m == "semi_2c":    return 6 * 4 * (n ** 2)
        if m == "4L":         return len(LOWERCASE) ** 4
        if m == "4n":         return len(DIGITS) ** 4
        if m == "5n":         return len(DIGITS) ** 5
        if m == "semi_4n":    return 5 * 2 * (10 ** 4)
        if m == "semi_3n":    return 4 * 2 * (10 ** 3)
        if m == "word_sep":   return len(ALL_WORDS) * 4
        if m == "word_join":  return len(COMBO_WORDS) * (len(COMBO_WORDS) - 1)
        if m == "word_dict":  return len(DICTIONARY_WORDS)
        raise ValueError(f"unknown mode: {self.mode}")

    def decode(self, idx: int) -> str:
        m = self.mode
        if m == "4c_smart":  return decode_base(idx, ALNUM, 4)
        if m == "3c":        return decode_base(idx, ALNUM, 3)
        if m == "semi_3c":   return decode_semi(idx, "._", 3, ALNUM)
        if m == "4L":        return decode_base(idx, LOWERCASE, 4)
        if m == "4n":        return decode_base(idx, DIGITS, 4)
        if m == "5n":        return decode_base(idx, DIGITS, 5)
        if m == "semi_4n":   return decode_semi(idx, "._", 4, DIGITS)
        if m == "semi_3n":   return decode_semi(idx, "._", 3, DIGITS)
        if m == "semi_2c":
            n2 = len(ALNUM) ** 2
            pattern = idx // (4 * n2)
            idx %= (4 * n2)
            sep_pair = idx // n2
            idx %= n2
            s1 = "._"[sep_pair // 2]
            s2 = "._"[sep_pair % 2]
            a = ALNUM[idx // len(ALNUM)]
            b = ALNUM[idx % len(ALNUM)]
            if pattern == 0: return f"{s1}{s2}{a}{b}"
            if pattern == 1: return f"{s1}{a}{s2}{b}"
            if pattern == 2: return f"{s1}{a}{b}{s2}"
            if pattern == 3: return f"{a}{b}{s1}{s2}"
            if pattern == 4: return f"{a}{s1}{b}{s2}"
            return f"{a}{s1}{s2}{b}"
        if m == "word_sep":
            wi, f = divmod(idx, 4)
            w = ALL_WORDS[wi]
            return (w + ".", w + "_", "." + w, "_" + w)[f]
        if m == "word_join":
            k = len(COMBO_WORDS)
            a, b = divmod(idx, k - 1)
            if b >= a: b += 1
            return COMBO_WORDS[a] + COMBO_WORDS[b]
        if m == "word_dict": return DICTIONARY_WORDS[idx]
        raise ValueError(m)

    def permute_idx(self, value: int) -> int:
        if self.total <= 1: return 0
        x = value & self.mask
        while True:
            for mult, add, sa, sb in self.rounds:
                x = (x + add) & self.mask
                x ^= x >> sa
                x = (x * mult) & self.mask
                x ^= x >> sb
                x &= self.mask
            if x < self.total: return x

    def next(self) -> str:
        with self.lock:
            idx = self.permute_idx(self.counter)
            self.counter = (self.counter + 1) % self.total
        return self.decode(idx)

def normalize_proxy(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw or raw.startswith("#"): return None
    if raw.startswith(("http://", "https://", "socks5://", "socks5h://")): return raw.rstrip("/")
    if "@" in raw:
        auth, address = raw.rsplit("@", 1)
        if ":" in auth and ":" in address:
            user, password = auth.split(":", 1)
            host, port = address.rsplit(":", 1)
            if user and host and port.isdigit():
                return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    parts = raw.split(":")
    if len(parts) == 2:
        host, port = parts
        if host and port.isdigit(): return f"http://{host}:{port}"
    if len(parts) >= 4:
        host, port, user = parts[0], parts[1], parts[2]
        password = ":".join(parts[3:])
        if host and port.isdigit() and user:
            return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return None

def load_proxies(base: Path, settings: Settings) -> list:
    rows = []
    if settings.proxies.strip(): rows.extend(re.split(r"[\r\n,]+", settings.proxies))
    else:
        p = base / PROXY_FILE
        if p.exists():
            try: rows.extend(p.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError: pass
    out, seen = [], set()
    for row in rows:
        proxy = normalize_proxy(row)
        if proxy and proxy not in seen:
            out.append(proxy); seen.add(proxy)
    return out

DISCORD_GREEN = 0x57F287

def build_wh_payload(username: str, mode_label: str) -> dict:
    return {
        "content": f"**@{username}** is available", "username": "sniper",
        "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
        "embeds": [{"title": "Username available", "description": f"`@{username}`", "color": DISCORD_GREEN, "footer": {"text": "by Caennais"}}],
    }

def mask_url(url: str) -> str:
    url = url.strip()
    m = re.match(r"^(https://[^\s/]+/api/webhooks/\d+)/([^\s/?#]+)", url)
    if m:
        token = m.group(2)
        if len(token) > 10: return f"{m.group(1)}/{token[:4]}...{token[-4:]}"
        return f"{m.group(1)}/{token}"
    return url[:60] + ("..." if len(url) > 60 else "")

def try_send_wh(url: str, username: str, mode_label: str, timeout: int = 10) -> tuple:
    payload = build_wh_payload(username, mode_label)
    body_text = json.dumps(payload)
    errors = []
    if std_requests is not None:
        try:
            s = std_requests.Session(); s.trust_env = False
            r = s.post(url, data=body_text, headers={"Content-Type": "application/json"}, timeout=timeout)
            try: s.close()
            except Exception: pass
            if 200 <= r.status_code < 300: return True, "requests", ""
            errors.append(f"requests HTTP {r.status_code}")
        except Exception as e: errors.append(f"requests {type(e).__name__}: {str(e)[:120]}")
    try:
        req = urllib.request.Request(url, data=body_text.encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "sniper/1.0"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300: return True, "urllib", ""
        except urllib.error.HTTPError as he: errors.append(f"urllib HTTP {he.code}")
    except Exception as e: errors.append(f"urllib {type(e).__name__}: {str(e)[:120]}")
    return False, "none", " | ".join(errors)

def try_send_claim_wh(url: str, username: str, user_id: str, avatar_url: str, timeout: int = 10) -> tuple:
    if not url: return False, "no url"
    avatar_full = avatar_url or "https://cdn.discordapp.com/embed/avatars/0.png"
    payload = {
        "username": "sniper", "content": f"**auto claimed!** `@{username}`",
        "embeds": [{"title": "auto claimed!", "description": f"**username** `@{username}`\n**id** `{user_id}`", "color": 0x57F287, "thumbnail": {"url": avatar_full}, "footer": {"text": "by Caennais"}}],
    }
    body = json.dumps(payload)
    try:
        req = urllib.request.Request(url, data=body.encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "sniper/1.0"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300: return True, "ok"
        except urllib.error.HTTPError as he: return False, f"HTTP {he.code}"
    except Exception as e: return False, f"{type(e).__name__}: {str(e)[:120]}"
    if std_requests is not None:
        try:
            s = std_requests.Session(); s.trust_env = False
            r = s.post(url, data=body, headers={"Content-Type": "application/json"}, timeout=timeout)
            try: s.close()
            except Exception: pass
            if 200 <= r.status_code < 300: return True, "ok"
            return False, f"HTTP {r.status_code}"
        except Exception as e: return False, f"{type(e).__name__}: {str(e)[:120]}"
    return False, "no transport"

class WebhookSender:
    RATE_LIMIT_PER_MIN = 25
    MAX_ATTEMPTS = 3
    def __init__(self, url: str):
        self.url = url.strip(); self.queue = queue.Queue(); self.stop_evt = threading.Event()
        self.thread = None; self.times = deque(); self.lock = threading.Lock(); self.sent = 0; self.failed = 0
    def start(self) -> bool:
        if self.thread is not None: return True
        self.thread = threading.Thread(target=self.run, daemon=True, name="webhook"); self.thread.start(); return True
    def enqueue(self, username: str, mode_label: str) -> None:
        if not self.url: return
        self.queue.put_nowait((username, mode_label))
    def wait_for_slot(self) -> None:
        while True:
            with self.lock:
                now = time.time()
                while self.times and self.times[0] < now - 60: self.times.popleft()
                if len(self.times) < self.RATE_LIMIT_PER_MIN:
                    self.times.append(now); return
                wait = (self.times[0] + 60) - now
            if wait > 0: time.sleep(min(wait + 0.05, 5.0))
    def run(self) -> None:
        try:
            while not self.stop_evt.is_set() or not self.queue.empty():
                try: username, mode_label = self.queue.get(timeout=0.5)
                except queue.Empty: continue
                self.wait_for_slot()
                success = False
                for attempt in range(self.MAX_ATTEMPTS):
                    success, _b, _e = try_send_wh(self.url, username, mode_label)
                    if success: break
                    time.sleep(0.7 * (attempt + 1))
                with self.lock:
                    if success: self.sent += 1
                    else: self.failed += 1
        except Exception: pass
    def stop(self, drain_timeout: float = 15.0) -> None:
        self.stop_evt.set()
        if self.thread is not None: self.thread.join(timeout=drain_timeout)

CF_MARKERS = ("cf-chl", "cf_chl", "challenge-platform", "cf-please-wait", "just a moment", "attention required")

def is_cf_challenge(body: str) -> bool:
    if not body: return False
    low = body[:600].lower()
    if "<!doctype html" in low and "discord" not in low[:200]: return True
    return any(m in low for m in CF_MARKERS)

def build_line(name, state):
    tag = f"{BLUE}@{name}{RESET}"
    if state == "available": status = f"{GREEN}[AVAILABLE]{RESET}"
    elif state == "taken": status = f"{RED}[TAKEN]{RESET}"
    elif state == "rate_limited": status = f"{YELLOW}[RATE-LIMITED]{RESET}"
    elif state == "error": status = f"{YELLOW}[ERROR]{RESET}"
    else: status = f"{GREY}[{state.upper()}]{RESET}"
    return f"  {tag} {status}"

class AutoClaimer:
    def __init__(self, settings: Settings, stop_evt=None):
        self.settings = settings; self.token = clean_token(settings.autoclaim_token)
        self.password = settings.autoclaim_password or ""; self.anticaptcha_key = (settings.anticaptcha_key or "").strip()
        self.anticaptcha_enabled = bool(settings.anticaptcha_enabled); self.stop_evt = stop_evt
        self.lock = threading.Lock(); self.claimed = threading.Event()
    def claim(self, username: str) -> tuple:
        with self.lock:
            ok, detail = self.inner_claim(username)
            if ok: self.claimed.set(); return True, detail
            return False, detail
    def fetch_user(self):
        h = token_headers(self.token)
        try:
            if HAS_CURL:
                s = CurlSession(impersonate=random.choice(IMPERSONATE))
                try:
                    r = s.get("https://discord.com" + CLAIM_PATH, headers=h, timeout=CLAIM_TIMEOUT)
                    if r.status_code != 200: return None
                    return r.json()
                finally:
                    try: s.close()
                    except Exception: pass
            else:
                req = urllib.request.Request("https://discord.com" + CLAIM_PATH, headers=h, method="GET")
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    with opener.open(req, timeout=CLAIM_TIMEOUT) as resp:
                        return json.loads(resp.read().decode("utf-8", "replace"))
                except urllib.error.HTTPError: return None
        except Exception: return None
    def patch_claim(self, host: str, payload: dict, captcha_key=None, rqtoken=None):
        h = token_headers(self.token, host)
        if captcha_key: h["X-Captcha-Key"] = captcha_key
        if rqtoken: h["X-Captcha-Rqtoken"] = rqtoken
        body = json.dumps(payload).encode("utf-8")
        status = 0; data = {}
        try:
            if HAS_CURL:
                s = CurlSession(impersonate=random.choice(IMPERSONATE))
                try:
                    r = s.patch(host + CLAIM_PATH, data=body, headers=h, timeout=CLAIM_TIMEOUT)
                    status = r.status_code
                    try: data = r.json()
                    except Exception:
                        try: data = {"_raw": (r.text or "")[:300]}
                        except Exception: data = {}
                finally:
                    try: s.close()
                    except Exception: pass
            else:
                req = urllib.request.Request(host + CLAIM_PATH, data=body, headers=h, method="PATCH")
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    with opener.open(req, timeout=CLAIM_TIMEOUT) as resp:
                        status = resp.status
                        try: data = json.loads(resp.read().decode("utf-8", "replace"))
                        except Exception: data = {}
                except urllib.error.HTTPError as he:
                    status = he.code
                    try:
                        raw = he.read().decode("utf-8", "replace"); data = json.loads(raw)
                    except Exception: data = {}
        except Exception as e: data = {"_transport_error": f"{type(e).__name__}: {str(e)[:120]}"}
        return status, data
    def inner_claim(self, username: str) -> tuple:
        payload = {"username": username}
        if self.password: payload["password"] = self.password
        status, data = self.patch_claim("https://discord.com", payload)
        if status == 200: return True, f"claimed @{username}"
        if status == 400 and data.get("captcha_key"):
            sitekey = data.get("captcha_sitekey", "")
            rqdata = data.get("captcha_rqdata", "")
            rqtoken = data.get("captcha_rqtoken", "")
            ua = claim_ctx().get("user-agent", "")
            if not self.anticaptcha_key or not self.anticaptcha_enabled:
                return False, "captcha required — no Anti-Captcha key set (menu 9 -> 5)"
            if not sitekey: return False, "captcha required but sitekey missing"
            ok_solve, tok_or_err = anticaptcha_solve(self.anticaptcha_key, sitekey=sitekey, url="https://discord.com", rqdata=rqdata, user_agent=ua)
            if not ok_solve: return False, f"anti-captcha: {tok_or_err}"
            status2, data2 = self.patch_claim("https://discord.com", payload, captcha_key=tok_or_err, rqtoken=rqtoken)
            if status2 == 200: return True, f"claimed @{username} (captcha solved)"
            if status2 == 400 and data2.get("captcha_key"): return False, "captcha token rejected (enterprise rqdata mismatch)"
            if status2 == 400 and data2.get("username"): return False, f"username rejected: {data2['username']}"
            if status2 == 401: return False, "token invalid or expired"
            return False, f"captcha retry failed: HTTP {status2}"
        if status == 401: return False, "token invalid or expired"
        if status == 429:
            retry_after = float(data.get("retry_after") or 3.0)
            return False, f"rate limited, retry in {retry_after:.1f}s"
        if status == 400:
            if data.get("password"): return False, "password required or wrong — set in menu 9 -> 2"
            if data.get("username"): return False, f"username rejected: {data['username']}"
            if data.get("message") and "phone" in str(data["message"]).lower(): return False, "phone verification required"
            return False, f"400 :: {json.dumps(data)[:220]}"
        if status == 0: return False, f"transport :: {str(data)[:200]}"
        return False, f"HTTP {status} :: {json.dumps(data)[:220]}"

def probe_token(token: str) -> tuple:
    h = token_headers(clean_token(token))
    try:
        if HAS_CURL:
            s = CurlSession(impersonate=random.choice(IMPERSONATE))
            try:
                r = s.get("https://discord.com/api/v9/users/@me", headers=h, timeout=10.0)
                code = r.status_code
                try: body = r.json()
                except Exception: body = {}
            finally:
                try: s.close()
                except Exception: pass
            if code == 200: return True, f"ok - @{body.get('username','?')} (id {body.get('id','?')})"
            return False, f"HTTP {code}: {str(body)[:120]}"
        else:
            req = urllib.request.Request("https://discord.com/api/v9/users/@me", headers=h, method="GET")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(req, timeout=10.0) as resp:
                    body = json.loads(resp.read().decode("utf-8", "replace"))
                return True, f"ok - @{body.get('username','?')} (id {body.get('id','?')})"
            except urllib.error.HTTPError as he: return False, f"HTTP {he.code}"
    except Exception as e: return False, f"{type(e).__name__}: {e}"

def install_sigint(stop_evt, procs):
    def handler(signum, frame):
        try: stop_evt.set()
        except Exception: pass
    try: signal.signal(signal.SIGINT, handler)
    except Exception: pass

def restore_sigint():
    try: signal.signal(signal.SIGINT, signal.default_int_handler)
    except Exception: pass

def subprocess_main(proc_id, n_procs, proxies, settings_dict, stop_evt, counters, file_lock, results_path, names_q):
    try: signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception: pass
    try: gc.enable()
    except Exception: pass
    try:
        settings = Settings(**settings_dict)
        my_proxies = proxies[proc_id::n_procs]
        if not my_proxies: my_proxies = proxies
        gen = NameGen(settings.mode, seed=random.SystemRandom().getrandbits(63))
        band = gen.total // max(1, n_procs)
        gen.counter = (gen.counter + proc_id * band) % gen.total
        per_proc_cps = max(1.0, settings.target_cps / n_procs)
        n_workers = max(MIN_WORKERS, min(MAX_WORKERS, int(math.ceil(per_proc_cps * WORKER_FACTOR))))
        work_q = queue.Queue(maxsize=100000); retry_q = queue.Queue(maxsize=20000)
        proxy_dead = {}; proxy_lock = threading.Lock()
        counter_checked = counters['checked']; counter_taken = counters['taken']
        counter_available = counters['available']; counter_limited = counters['limited']; counter_errors = counters['errors']
        def new_session(proxy, host):
            headers = build_headers(host)
            if HAS_CURL:
                s = CurlSession(impersonate=random.choice(IMPERSONATE))
                if proxy: s.proxies = {"http": proxy, "https": proxy}
                s.headers.update(headers); return s
            elif HAS_TLS:
                ident = random.choice(["chrome_110", "chrome_116", "chrome_119", "chrome_120"])
                s = tls_client.Session(client_identifier=ident, random_tls_extension_order=True)
                if proxy: s.proxies = {"http": proxy, "https": proxy}
                s.headers.update(headers); return s
            else:
                s = std_requests.Session(); s.trust_env = False
                from requests.adapters import HTTPAdapter
                adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0)
                s.mount("https://", adapter); s.mount("http://", adapter)
                s.headers.update(headers)
                if proxy: s.proxies.update({"http": proxy, "https": proxy})
                return s
        def pick_proxy():
            n = len(my_proxies)
            if n == 0: return None
            now = time.monotonic()
            for _ in range(20):
                p = random.choice(my_proxies)
                with proxy_lock: dead = proxy_dead.get(p, 0)
                if dead > now: continue
                return p
            return my_proxies[0]
        def record_name(proxy, name, state):
            if state == "taken":
                with counter_taken.get_lock(): counter_taken.value += 1
                try: names_q.put_nowait((name, "taken"))
                except Exception: pass
            elif state == "available":
                with counter_available.get_lock(): counter_available.value += 1
                try:
                    with file_lock:
                        with open(results_path, "a", encoding="utf-8") as f: f.write(name + "\n")
                except Exception: pass
                try: names_q.put_nowait((name, "available"))
                except Exception: pass
            elif state == "rate_limited":
                with counter_limited.get_lock(): counter_limited.value += 1
            elif state == "error":
                with counter_errors.get_lock(): counter_errors.value += 1
        def check_name(session, proxy, host, name):
            url = host + DISCORD_PATH
            try: r = session.post(url, json={"username": name}, timeout=settings.timeout_ms / 1000.0)
            except Exception:
                with proxy_lock: proxy_dead[proxy] = time.monotonic() + PROXY_COOLDOWN
                return "error"
            status = r.status_code
            if status == 429: return "rate_limited"
            if status == 407:
                with proxy_lock: proxy_dead[proxy] = time.monotonic() + PROXY_COOLDOWN
                return "error"
            if status in (401, 403): return "rate_limited"
            try: body_probe = r.text or ""
            except Exception: body_probe = ""
            if is_cf_challenge(body_probe): return "rate_limited"
            try: data = r.json()
            except Exception: return "error"
            taken = data.get("taken")
            if isinstance(taken, bool): return "taken" if taken else "available"
            return "rate_limited"
        def check_until_definite(name, thread_local_holder):
            last_state = "error"
            for attempt in range(RETRY_ATTEMPTS):
                proxy = thread_local_holder.get("proxy") or pick_proxy()
                if proxy is None: time.sleep(0.05); continue
                sess = thread_local_holder.get("session")
                host = thread_local_holder.get("host") or random.choice(HOSTS)
                if sess is None:
                    try:
                        sess = new_session(proxy, host)
                        thread_local_holder["session"] = sess
                        thread_local_holder["proxy"] = proxy
                        thread_local_holder["host"] = host
                        thread_local_holder["reqs"] = 0
                    except Exception:
                        with proxy_lock: proxy_dead[proxy] = time.monotonic() + PROXY_COOLDOWN
                        thread_local_holder["session"] = None
                        thread_local_holder["proxy"] = None
                        time.sleep(ERR_PAUSE); continue
                try:
                    state = check_name(sess, proxy, host, name)
                    thread_local_holder["reqs"] = thread_local_holder.get("reqs", 0) + 1
                    if thread_local_holder["reqs"] >= SESSION_MAX_REQ:
                        try: sess.close()
                        except Exception: pass
                        thread_local_holder["session"] = None
                except Exception:
                    try: sess.close()
                    except Exception: pass
                    thread_local_holder["session"] = None
                    state = "error"

                last_state = state
                if state in ("taken", "available"): return state
                if state in ("rate_limited", "error"):
                    try: sess.close()
                    except Exception: pass
                    thread_local_holder["session"] = None
                    thread_local_holder["proxy"] = None
                    time.sleep(ERR_PAUSE)
            return last_state
        def worker_loop():
            session = None; proxy = None; req_count = 0; host = random.choice(HOSTS)
            while not stop_evt.is_set():
                if proxy is None:
                    proxy = pick_proxy()
                    if proxy is None: time.sleep(0.05); continue
                if session is None:
                    host = random.choice(HOSTS)
                    try:
                        session = new_session(proxy, host); req_count = 0
                    except Exception:
                        with proxy_lock: proxy_dead[proxy] = time.monotonic() + PROXY_COOLDOWN
                        proxy = None; continue
                try: name = work_q.get(timeout=0.5)
                except queue.Empty: continue
                state = check_name(session, proxy, host, name); req_count += 1
                if req_count >= SESSION_MAX_REQ:
                    try: session.close()
                    except Exception: pass
                    session = None
                if state in ("taken", "available"):
                    with counter_checked.get_lock(): counter_checked.value += 1
                    record_name(proxy, name, state)
                elif state == "rate_limited":
                    try: session.close()
                    except Exception: pass
                    session = None
                    try: retry_q.put_nowait(name)
                    except queue.Full: pass
                else:
                    try: session.close()
                    except Exception: pass
                    session = None
                    try: retry_q.put_nowait(name)
                    except queue.Full: pass
        def retry_loop():
            holder = {}
            while not stop_evt.is_set():
                try: name = retry_q.get(timeout=0.4)
                except queue.Empty: continue
                state = check_until_definite(name, holder)
                if state in ("taken", "available"):
                    with counter_checked.get_lock(): counter_checked.value += 1
                    proxy_for_record = pick_proxy() or my_proxies[0]
                    record_name(proxy_for_record, name, state)
                elif state == "error":
                    with counter_checked.get_lock(): counter_checked.value += 1
                    with counter_errors.get_lock(): counter_errors.value += 1
                    try: names_q.put_nowait((name, "error"))
                    except Exception: pass
                else:
                    with counter_checked.get_lock(): counter_checked.value += 1
                    with counter_limited.get_lock(): counter_limited.value += 1
                    try: names_q.put_nowait((name, "rate_limited"))
                    except Exception: pass
        for _ in range(n_workers): threading.Thread(target=worker_loop, daemon=True).start()
        for _ in range(12): threading.Thread(target=retry_loop, daemon=True).start()
        batch_size = max(1, int(round(per_proc_cps * PACER_TICK)))
        next_name = gen.next; put = work_q.put_nowait
        while not stop_evt.is_set():
            try:
                for _ in range(batch_size):
                    try: put(next_name())
                    except queue.Full: break
                time.sleep(PACER_TICK)
            except Exception: continue
    except Exception: pass

def run_checker(base: Path, settings: Settings):
    proxies = load_proxies(base, settings)
    if not proxies:
        clear_screen(); print_banner(); print_top(); print_blank()
        print_row(f"   {RED}!  No proxies loaded.{RESET}")
        print_blank(); print_bottom(); print()
        try: input(f"  {GREY}Press Enter to return...{RESET}")
        except (EOFError, KeyboardInterrupt): pass
        return
    effective_cps = max(MIN_CPS, float(settings.target_cps))
    gen = NameGen(settings.mode)
    mode_label = MODE_BY_ID[settings.mode][1]
    total = gen.total
    n_procs = max(2, min(MAX_PROCS, os.cpu_count() or 4))
    if len(proxies) < n_procs: n_procs = max(1, len(proxies))
    webhook_sender = None
    if settings.webhook: webhook_sender = WebhookSender(settings.webhook)
    ac_ready = looks_like_token(settings.autoclaim_token)
    clear_screen(); print_banner(); print_top(); print_blank()
    print_row(f"   {GREY}mode        {RESET}{CYAN}{mode_label}{RESET}")
    print_row(f"   {GREY}connection  {RESET}{WHITE}{len(proxies):,}{RESET} {GREY}proxies{RESET}")
    print_row(f"   {GREY}pace        {RESET}{WHITE}{effective_cps:.1f}{RESET} {GREY}cps target{RESET}")
    print_row(f"   {GREY}total       {RESET}{WHITE}{total:,}{RESET} {GREY}combos{RESET}")
    if settings.autoclaim_enabled and ac_ready: print_row(f"   {GREY}auto-claim  {RESET}{GREEN}ARMED{RESET}")
    elif settings.autoclaim_enabled: print_row(f"   {GREY}auto-claim  {RESET}{YELLOW}no token set{RESET}")
    else: print_row(f"   {GREY}auto-claim  {RESET}{GREY}OFF{RESET}")
    if settings.anticaptcha_enabled and settings.anticaptcha_key: print_row(f"   {GREY}anti-captcha{RESET} {GREEN}ARMED{RESET}")
    else: print_row(f"   {GREY}anti-captcha{RESET} {GREY}off{RESET}")
    print_blank(); print_bottom(); print()
    if webhook_sender: webhook_sender.start(); print()
    if settings.autoclaim_enabled and ac_ready and not settings.autoclaim_password:
        print(f"  {RED}!  auto-claim armed but no password set{RESET}")
        print(f"  {GREY}Discord requires the account password on the username PATCH.{RESET}")
        print(f"  {GREY}Set it in menu 9 -> 2, then save and re-run.{RESET}\n")
        try: input(f"  {GREY}Press Enter to return...{RESET}")
        except (EOFError, KeyboardInterrupt): pass
        return
    print(f"  {BOLD}{GREEN}running{RESET}   {GREY}(ctrl+c to stop){RESET}\n", flush=True)
    try: gc.enable(); gc.collect()
    except Exception: pass
    results_path = base / RESULTS_FILE
    results_path.parent.mkdir(parents=True, exist_ok=True)
    stop_evt = multiprocessing.Event(); file_lock = multiprocessing.Lock()
    autoclaimer = None
    if settings.autoclaim_enabled and ac_ready: autoclaimer = AutoClaimer(settings, stop_evt=stop_evt)
    counters = {
        'checked': multiprocessing.Value('L', 0, lock=True), 'taken': multiprocessing.Value('L', 0, lock=True),
        'available': multiprocessing.Value('L', 0, lock=True), 'limited': multiprocessing.Value('L', 0, lock=True),
        'errors': multiprocessing.Value('L', 0, lock=True),
    }
    names_q = multiprocessing.Queue(maxsize=100000)
    settings_dict = asdict(settings.sanitize())
    results_path_str = str(results_path)
    procs = []
    for i in range(n_procs):
        p = multiprocessing.Process(
            target=subprocess_main,
            args=(i, n_procs, proxies, settings_dict, stop_evt, counters, file_lock, results_path_str, names_q),
            daemon=True, name=f"snpr-{i}",
        )
        p.start(); procs.append(p)
    install_sigint(stop_evt, procs)
    def hard_kill_workers():
        for p in procs:
            try:
                if p.is_alive(): p.terminate()
            except Exception: pass
    claim_state = {"running": False, "finished": False}
    claim_state_lock = threading.Lock()
    def printer():
        try: out = sys.stdout.buffer
        except Exception: out = None
        panel_rows = 13; recent = deque(maxlen=10); last_seen_count = 0
        results_pending = False; render_interval = 1.0 / 30.0
        next_render = time.perf_counter() + render_interval; rate_sample_started = time.perf_counter()
        frame_results = 0; results_per_second = 0.0
        def render_panel():
            nonlocal results_pending
            try:
                c = counters['checked'].value; t = counters['taken'].value
                a = counters['available'].value; l = counters['limited'].value; e = counters['errors'].value
            except Exception: c = t = a = l = e = 0
            rows = [
                f"  {BOLD}{WHITE}LIVE RESULTS{RESET}",
                f"  {GREY}checked {WHITE}{c:,}{RESET}  {GREY}taken {WHITE}{t:,}{RESET}  "
                f"{GREY}found {BOLD}{GREEN}{a:,}{RESET}  {GREY}rate-limited {WHITE}{l:,}{RESET}  "
                f"{GREY}errors {WHITE}{e:,}{RESET}  {GREY}CPS {WHITE}{results_per_second:,.0f}{RESET}", "",
            ]
            rows.extend(reversed(recent)); rows.extend([""] * (panel_rows - len(rows)))
            data = "".join("\r\033[2K" + r + "\n" for r in rows) + f"\033[{panel_rows}A"
            try:
                if out is not None: out.write(data.encode("utf-8", "replace")); out.flush()
                else: sys.stdout.write(data); sys.stdout.flush()
            except Exception: pass
            if results_pending:
                try: results_file.flush()
                except OSError: pass
                else: results_pending = False
        with results_path.open("a", encoding="utf-8") as results_file:
            sys.stdout.write("\n" * panel_rows + f"\033[{panel_rows}A"); sys.stdout.flush()
            while True:
                drained_any = False
                for _ in range(500):
                    try: name, state = names_q.get_nowait()
                    except queue.Empty: break
                    except Exception: break
                    drained_any = True
                    if state == "taken":
                        if settings.show_taken: recent.append(build_line(name, "taken"))
                    elif state == "available":
                        recent.append(build_line(name, "available"))
                        if webhook_sender:
                            try: webhook_sender.enqueue(name, mode_label)
                            except Exception: pass
                        if autoclaimer is not None and not autoclaimer.claimed.is_set() and not claim_state["running"]:
                            with claim_state_lock: claim_state["running"] = True
                            recent.append(f"  {BOLD}{CYAN}[ AUTO-CLAIMING ]{RESET} {BOLD}{WHITE}@{name}{RESET} {CYAN}-> claiming now{RESET}")
                            stop_evt.set(); hard_kill_workers()
                            try: render_panel()
                            except Exception: pass
                            def do_claim(nm):
                                t0 = time.monotonic(); ok, detail = False, "unknown"
                                try: ok, detail = autoclaimer.claim(nm)
                                except Exception as exc: ok, detail = False, f"{type(exc).__name__}: {exc}"
                                dt = time.monotonic() - t0
                                try:
                                    if ok:
                                        user = autoclaimer.fetch_user() or {}
                                        uname = user.get("username", nm); uid = user.get("id", "?"); avatar = user.get("avatar")
                                        if avatar:
                                            ext = "gif" if str(avatar).startswith("a_") else "png"
                                            avatar_url = f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.{ext}?size=256"
                                        else: avatar_url = f"https://cdn.discordapp.com/embed/avatars/0.png"
                                        recent.append(f"  {BOLD}{GREEN}[ CLAIMED! ]{RESET} {BOLD}{WHITE}@{uname}{RESET} {GREEN}-> id {uid} in {dt:.2f}s{RESET}")
                                        try: render_panel()
                                        except Exception: pass
                                        if settings.webhook:
                                            try: try_send_claim_wh(settings.webhook, uname, uid, avatar_url)
                                            except Exception: pass
                                    else:
                                        dshort = detail if len(detail) <= 260 else detail[:260] + "..."
                                        recent.append(f"  {YELLOW}[CLAIM-FAIL]{RESET} {BLUE}@{nm}{RESET} {GREY}- {dshort} ({dt:.2f}s){RESET}")
                                        try: render_panel()
                                        except Exception: pass
                                finally:
                                    with claim_state_lock:
                                        claim_state["running"] = False; claim_state["finished"] = True
                            threading.Thread(target=do_claim, args=(name,), daemon=True, name="claim").start()
                    elif state == "rate_limited": recent.append(build_line(name, "rate_limited"))
                    elif state == "error": recent.append(build_line(name, "error"))
                now = time.perf_counter()
                try: cur_checked = counters['checked'].value
                except Exception: cur_checked = last_seen_count
                if cur_checked > last_seen_count:
                    frame_results += (cur_checked - last_seen_count); last_seen_count = cur_checked
                if now >= next_render or drained_any:
                    elapsed = max(now - rate_sample_started, 0.001); sample = frame_results / elapsed
                    smoothing = 1.0 - math.exp(-elapsed / 0.75)
                    results_per_second += (sample - results_per_second) * smoothing
                    frame_results = 0; rate_sample_started = now; render_panel(); next_render = now + render_interval
                else: time.sleep(0.005)
                if stop_evt.is_set() and names_q.empty() and claim_state["finished"]: break
            try: results_file.flush()
            except OSError: pass
            sys.stdout.write(f"\033[{panel_rows}B\r\n"); sys.stdout.flush()
    printer_thread = threading.Thread(target=printer, daemon=True, name="printer")
    printer_thread.start()
    
    # INSTANT KILL ON CTRL+C
    try:
        while True:
            if stop_evt.is_set() and claim_state["finished"]: break
            time.sleep(0.1)
    except KeyboardInterrupt: 
        stop_evt.set()
        for p in procs:
            try:
                if p.is_alive(): p.terminate()
            except Exception: pass
    finally:
        stop_evt.set()
        for p in procs:
            try:
                if p.is_alive(): p.terminate()
            except Exception: pass
        for p in procs:
            try: p.join(timeout=2.0)
            except Exception: pass
        for p in procs:
            try:
                if p.is_alive(): p.kill()
            except Exception: pass
        try:
            for _ in range(60):
                with claim_state_lock:
                    if claim_state["finished"] or not claim_state["running"]: break
                time.sleep(0.1)
        except Exception: pass
        try: printer_thread.join(timeout=2.0)
        except Exception: pass
        try: sys.stdout.write("\033[?25h"); sys.stdout.flush()
        except Exception: pass
        try:
            c = counters['checked'].value; t = counters['taken'].value
            a = counters['available'].value; l = counters['limited'].value; e = counters['errors'].value
        except Exception: c = t = a = l = e = 0
        print(); print_top(); print_blank()
        print_row(f"   {GREY}checked      {RESET}{WHITE}{c:,}{RESET}")
        print_row(f"   {GREY}taken        {RESET}{WHITE}{t:,}{RESET}")
        print_row(f"   {GREY}found        {RESET}{BOLD}{GREEN}{a:,}{RESET}")
        print_row(f"   {GREY}rate-limited {RESET}{WHITE}{l:,}{RESET}")
        print_row(f"   {GREY}errors       {RESET}{WHITE}{e:,}{RESET}")
        if autoclaimer is not None and autoclaimer.claimed.is_set(): print_row(f"   {GREY}claim        {RESET}{BOLD}{GREEN}SUCCESS{RESET}")
        print_blank(); print_bottom(); print(flush=True)
        if webhook_sender:
            try: webhook_sender.stop(drain_timeout=10.0)
            except Exception: pass
        try: gc.enable(); gc.collect()
        except Exception: pass
        restore_sigint()
        print()
        try: input(f"  {GREY}Press Enter to return to menu...{RESET}")
        except (EOFError, KeyboardInterrupt): print()

def drain_stdin():
    if os.name == "nt":
        try:
            import msvcrt
            while msvcrt.kbhit(): msvcrt.getwch()
            return
        except Exception: pass
    try:
        import select
        while select.select([sys.stdin], [], [], 0)[0]: sys.stdin.read(1)
    except Exception: pass

def read_clipboard() -> str:
    try:
        import tkinter as tk
        r = tk.Tk(); r.withdraw()
        try: txt = r.clipboard_get()
        finally:
            try: r.destroy()
            except Exception: pass
        if isinstance(txt, str): return txt
    except Exception: pass
    if os.name == "nt":
        try:
            import subprocess
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, timeout=6)
            if out.returncode == 0: return out.stdout.decode("utf-8", "replace")
        except Exception: pass
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(["pbpaste"], capture_output=True, timeout=6)
            if out.returncode == 0: return out.stdout.decode("utf-8", "replace")
        except Exception: pass
    try:
        import subprocess
        for cmd in (["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
            try:
                out = subprocess.run(cmd, capture_output=True, timeout=6)
                if out.returncode == 0: return out.stdout.decode("utf-8", "replace")
            except Exception: continue
    except Exception: pass
    return ""

def ask_clipboard(what: str) -> str:
    drain_stdin()
    try:
        sys.stdout.write(f"  {GREY}copy your {what} to the clipboard, then press Enter.{RESET}\n")
        sys.stdout.write(f"  {ACCENT}press Enter to read {what} >{RESET} "); sys.stdout.flush()
        sys.stdin.readline()
    except (EOFError, KeyboardInterrupt): return ""
    return read_clipboard()

def ask(prompt: str) -> str:
    drain_stdin()
    try:
        sys.stdout.write(prompt); sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "": return ""
        return line.rstrip("\r\n")
    except (EOFError, KeyboardInterrupt): return ""

def looks_like_webhook(url):
    u = url.strip()
    return (
        u.startswith("https://discord.com/api/webhooks/")
        or u.startswith("https://discordapp.com/api/webhooks/")
        or u.startswith("https://canary.discord.com/api/webhooks/")
        or u.startswith("https://ptb.discord.com/api/webhooks/")
    )

def render_status(settings, proxies):
    mode = MODE_BY_ID[settings.mode][1]
    conn = f"{GREEN}on{RESET} {GREY}({len(proxies):,}){RESET}" if proxies else f"{RED}off{RESET}"
    wh = f"{CYAN}on{RESET}" if settings.webhook else f"{GREY}off{RESET}"
    ac_ready = looks_like_token(settings.autoclaim_token)
    if settings.autoclaim_enabled and ac_ready: ac = f"{GREEN}armed{RESET}"
    elif settings.autoclaim_enabled: ac = f"{YELLOW}no token{RESET}"
    else: ac = f"{GREY}off{RESET}"
    print(
        f"  {ACCENT2}::  {RESET}{WHITE}{mode}{RESET}"
        f"   {ACCENT2}::{RESET}  {GREY}proxies{RESET} {conn}"
        f"   {ACCENT2}::{RESET}  {GREY}cps{RESET} {WHITE}{settings.target_cps:.0f}{RESET}"
        f"   {ACCENT2}::{RESET}  {GREY}wh{RESET} {wh}"
        f"   {ACCENT2}::{RESET}  {GREY}claim{RESET} {ac}"
    )
    print()

def render_main_menu(settings):
    print_top(); print_blank()
    taken_state = f"{GREEN}ON{RESET}" if settings.show_taken else f"{GREY}OFF{RESET}"
    ac_ready = looks_like_token(settings.autoclaim_token)
    if settings.autoclaim_enabled and ac_ready: ac_state = f"{GREEN}ARMED{RESET}"
    elif settings.autoclaim_enabled: ac_state = f"{YELLOW}NO TOKEN{RESET}"
    else: ac_state = f"{GREY}OFF{RESET}"
    rows = [
        ("1", "Start checker"), ("2", "Choose username type"), ("3", "Connection / proxies"),
        ("4", "Target CPS"), ("5", "Discord webhook"), ("6", "Save settings"),
        ("7", f"Show taken  {ACCENT2}::{RESET}  {taken_state}"),
        ("8", f"Auto-claim  {ACCENT2}::{RESET}  {ac_state}"),
    ]
    for key, label in rows: print_row(f"   {ACCENT2}[{key}]{RESET}   {WHITE}{label}{RESET}")
    print_blank(); print_row(f"   {ACCENT2}[0]{RESET}   {RED}Exit{RESET}")
    print_blank(); print_bottom()
    print(f"  {DIM}{GREY}by Caennais{RESET}\n")

def choose_mode(settings):
    items = list(MODE_MAP.items())
    n = len(items); half = (n + 1) // 2; name_w = 18; gap = 4
    def cell(key, mid, label):
        selected = settings.mode == mid
        marker = f"{ACCENT}{BOLD}>{RESET}" if selected else " "
        if selected:
            key_str = f"{ACCENT}{BOLD}[ {key:>2} ]{RESET}"; name_raw = f"{BOLD}{WHITE}{label}{RESET}"
        else:
            key_str = f"{GREY}[ {key:>2} ]{RESET}"; name_raw = f"{WHITE}{label}{RESET}"
        name_col = pad_str(fit_str(name_raw, name_w), name_w)
        return f"{marker} {key_str} {name_col}"
    while True:
        clear_screen(); print_banner(); print_top(); print_blank()
        for i in range(half):
            lk, (lmid, llabel, _) = items[i]
            left = cell(lk, lmid, llabel)
            if i + half < n:
                rk, (rmid, rlabel, _) = items[i + half]
                right = cell(rk, rmid, rlabel)
            else: right = ""
            print_row(f"  {left}{' ' * gap}{right}")
        print_blank(); print_row(f"   {ACCENT2}[0]{RESET}   {GREY}back{RESET}")
        print_blank(); print_bottom()
        val = ask(f"  {ACCENT}>{RESET} ").strip()
        if val == "0": return
        if val in MODE_MAP:
            settings.mode = MODE_MAP[val][0]; return

def choose_speed(settings):
    clear_screen(); print_banner(); print_top(); print_blank()
    print_row(f"   {GREY}current target  {RESET}{WHITE}{settings.target_cps:.1f}{RESET} {GREY}cps{RESET}")
    print_blank(); print_row(f"   {GREY}range {MIN_CPS:g} - {MAX_CPS:g}{RESET}")
    print_blank(); print_bottom()
    raw = ask(f"  {ACCENT}>{RESET} ").strip()
    if not raw: return
    try:
        settings.target_cps = max(MIN_CPS, min(MAX_CPS, float(raw)))
        print(f"  {GREEN}target set to {settings.target_cps:.1f} cps{RESET}")
    except ValueError: print(f"  {YELLOW}invalid number{RESET}")

def choose_connection(base, settings):
    while True:
        clear_screen(); print_banner(); proxies = load_proxies(base, settings)
        print_top(); print_blank()
        print_row(f"   {ACCENT2}[1]{RESET}   {WHITE}Load from proxies.txt{RESET}   {GREY}({len(proxies):,} found){RESET}")
        print_row(f"   {ACCENT2}[2]{RESET}   {WHITE}Paste proxies now{RESET}")
        print_row(f"   {ACCENT2}[3]{RESET}   {WHITE}Clear configured proxies{RESET}")
        print_blank(); print_row(f"   {ACCENT2}[0]{RESET}   {GREY}back{RESET}")
        print_blank(); print_bottom()
        choice = ask(f"  {ACCENT}>{RESET} ").strip()
        if choice == "0": return
        if choice == "1":
            settings.proxies = ""
            print(f"  {GREEN}using {len(load_proxies(base, settings)):,} proxies{RESET}")
        elif choice == "2":
            print(f"  {GREY}Paste proxies, one per line. Blank line when done.{RESET}")
            rows = []
            while True:
                try: row = input().strip()
                except (EOFError, KeyboardInterrupt): break
                if not row: break
                rows.append(row)
            settings.proxies = "\n".join(rows)
            print(f"  {GREEN}stored {len(rows):,} entries{RESET}")
        elif choice == "3":
            settings.proxies = ""; print(f"  {GREY}cleared{RESET}")

def choose_webhook(settings):
    while True:
        clear_screen(); print_banner(); print_top(); print_blank()
        if settings.webhook:
            print_row(f"   {GREY}current  {RESET}{WHITE}{mask_url(settings.webhook)}{RESET}"); print_blank()
        print_row(f"   {ACCENT2}[1]{RESET}   {WHITE}Set / replace webhook{RESET}")
        print_row(f"   {ACCENT2}[2]{RESET}   {WHITE}Send test ping{RESET}")
        print_row(f"   {ACCENT2}[3]{RESET}   {WHITE}Clear webhook{RESET}")
        print_blank(); print_row(f"   {ACCENT2}[0]{RESET}   {GREY}back{RESET}")
        print_blank(); print_bottom()
        ch = ask(f"  {ACCENT}>{RESET} ").strip()
        if ch == "0": return
        if ch == "1":
            url = ask(f"  {GREY}url >{RESET} ").strip()
            if not looks_like_webhook(url): print(f"  {YELLOW}invalid webhook url{RESET}"); continue
            settings.webhook = url
            ok, _, err = try_send_wh(url, "sniper_test", "Test")
            print((f"  {GREEN}test sent{RESET}" if ok else f"  {RED}{err}{RESET}"))
        elif ch == "2":
            if not settings.webhook: print(f"  {YELLOW}no webhook set{RESET}"); continue
            ok, _, err = try_send_wh(settings.webhook, "sniper", "Test")
            print((f"  {GREEN}sent{RESET}" if ok else f"  {RED}{err}{RESET}"))
        elif ch == "3":
            settings.webhook = ""; print(f"  {GREY}cleared{RESET}")

def choose_autoclaim(settings: Settings):
    while True:
        clear_screen(); print_banner(); print_top(); print_blank()
        state_str = f"{GREEN}ON{RESET}" if settings.autoclaim_enabled else f"{GREY}OFF{RESET}"
        tok = mask_token(settings.autoclaim_token) if settings.autoclaim_token else "-"
        pw = "set" if settings.autoclaim_password else "unset"
        stop_disp = "yes" if settings.autoclaim_stop_on_claim else "no"
        wh = "on" if settings.webhook else "off"
        cap_armed = "ARMED" if settings.anticaptcha_enabled and settings.anticaptcha_key else "off"
        cap_key_disp = mask_apikey(settings.anticaptcha_key) if settings.anticaptcha_key else "-"
        print_row(f"   {GREY}status     {RESET}{state_str}")
        print_row(f"   {GREY}token      {RESET}{WHITE}{tok}{RESET}")
        print_row(f"   {GREY}password   {RESET}{WHITE}{pw}{RESET}")
        print_row(f"   {GREY}stop 1st   {RESET}{WHITE}{stop_disp}{RESET}")
        print_row(f"   {GREY}webhook    {RESET}{WHITE}{wh}{RESET}")
        print_row(f"   {GREY}anticaptcha{RESET} {WHITE}{cap_armed}{RESET} {GREY}{cap_key_disp}{RESET}")
        print_blank()
        print_row(f"   {ACCENT2}[1]{RESET}   {WHITE}Set account token (from clipboard){RESET}")
        print_row(f"   {ACCENT2}[2]{RESET}   {WHITE}Set account password (from clipboard){RESET}")
        print_row(f"   {ACCENT2}[3]{RESET}   {WHITE}Test token{RESET}")
        print_row(f"   {ACCENT2}[4]{RESET}   {WHITE}Toggle auto-claim{RESET}")
        print_row(f"   {ACCENT2}[5]{RESET}   {WHITE}Anti-Captcha API key{RESET}")
        print_row(f"   {ACCENT2}[6]{RESET}   {WHITE}Test Anti-Captcha key{RESET}")
        print_blank(); print_row(f"   {ACCENT2}[0]{RESET}   {GREY}back{RESET}")
        print_blank(); print_bottom()
        ch = ask(f"  {ACCENT}>{RESET} ").strip()
        if ch == "0": return
        if ch == "1":
            raw = ask_clipboard("account token"); t = clean_token(raw)
            if looks_like_token(t):
                settings.autoclaim_token = t
                print(f"  {GREEN}token stored ({len(t)} chars, {t.count('.')} dots){RESET}")
                print(f"  {GREY}starts: {t[:12]}...  ends: ...{t[-6:]}{RESET}")
            else: print(f"  {RED}rejected — got {len(t)} chars, {t.count('.')} dots{RESET}")
        elif ch == "2":
            raw = ask_clipboard("account password"); settings.autoclaim_password = raw.strip("\r\n\t ")
            if settings.autoclaim_password: print(f"  {GREEN}password stored ({len(settings.autoclaim_password)} chars){RESET}")
            else: print(f"  {GREY}clipboard empty — password not set{RESET}")
        elif ch == "3":
            if not looks_like_token(settings.autoclaim_token): print(f"  {RED}no valid token stored{RESET}")
            else:
                ok, detail = probe_token(settings.autoclaim_token)
                print((f"  {GREEN}{detail}{RESET}" if ok else f"  {RED}{detail}{RESET}"))
        elif ch == "4": settings.autoclaim_enabled = not settings.autoclaim_enabled
        elif ch == "5":
            print(f"  {GREY}sign up: {CYAN}https://anti-captcha.com/{RESET}")
            raw = ask_clipboard("Anti-Captcha API key"); key = raw.strip()
            if not key: print(f"  {GREY}clipboard empty — key not set{RESET}")
            else:
                print(f"  {GREY}validating...{RESET}")
                ok, detail = anticaptcha_balance(key)
                if ok:
                    settings.anticaptcha_key = key; settings.anticaptcha_enabled = True
                    print(f"  {GREEN}key saved — {detail}{RESET}")
                else: print(f"  {RED}rejected — {detail}{RESET}")
        elif ch == "6":
            if not settings.anticaptcha_key: print(f"  {RED}no key stored — set one first{RESET}")
            else:
                print(f"  {GREY}validating...{RESET}")
                ok, detail = anticaptcha_balance(settings.anticaptcha_key)
                print((f"  {GREEN}valid — {detail}{RESET}" if ok else f"  {RED}invalid — {detail}{RESET}"))
        drain_stdin()
        try:
            sys.stdout.write(f"  {GREY}Press Enter...{RESET}"); sys.stdout.flush(); sys.stdin.readline()
        except Exception: pass

def main():
    setup_console()
    base = get_base_dir()
    settings = load_settings()
    while True:
        clear_screen(); print_banner()
        proxies = load_proxies(base, settings)
        render_status(settings, proxies)
        render_main_menu(settings)
        try: choice = input(f"  {ACCENT}>{RESET} ").strip()
        except EOFError: return
        except KeyboardInterrupt: print(); continue
        if choice == "0": return
        if choice == "1":
            try: run_checker(base, settings)
            except KeyboardInterrupt: pass
        elif choice == "2": choose_mode(settings); save_settings(settings)
        elif choice == "3": choose_connection(base, settings); save_settings(settings)
        elif choice == "4": choose_speed(settings); save_settings(settings)
        elif choice == "5": choose_webhook(settings); save_settings(settings)
        elif choice == "6":
            save_settings(settings)
            print(f"  {GREEN}settings saved{RESET}"); time.sleep(0.8)
        elif choice == "7":
            settings.show_taken = not settings.show_taken; save_settings(settings)
        elif choice == "8": choose_autoclaim(settings); save_settings(settings)

if __name__ == "__main__":
    try: multiprocessing.freeze_support()
    except Exception: pass
    try: main()
    except KeyboardInterrupt: print(f"\n  {GREY}stopped.{RESET}")
    except Exception as exc:
        import traceback
        print(f"\n  {RED}unexpected error - {type(exc).__name__}: {exc}{RESET}")
        traceback.print_exc()
        try: input(f"\n  {GREY}Press Enter to close...{RESET}")
        except EOFError: pass
