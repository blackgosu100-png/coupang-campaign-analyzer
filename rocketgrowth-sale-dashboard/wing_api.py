# -*- coding: utf-8 -*-
"""
Wing 정산 리포트 자동 다운로드 - API 직접 호출 방식
Selenium 없이 requests만 사용. 동작 시간 1~3분.
"""
import os, sys, time, json, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Flask 연동 상태 ──────────────────────────────────────────────────────
STATUS = {
    "state":    "idle",   # idle | running | waiting | done | error
    "message":  "",
    "progress": 0,
    "total":    0,
    "folder":   None,
    "files":    [],
    "logs":     [],
}
_continue_event = threading.Event()

def set_status(state=None, message=None, progress=None, total=None):
    if state:    STATUS["state"]    = state
    if message:  STATUS["message"]  = message
    if progress is not None: STATUS["progress"] = progress
    if total is not None:    STATUS["total"]    = total
    if message:
        ts = datetime.now().strftime("%H:%M:%S")
        STATUS["logs"].append(f"[{ts}] {message}")
        if len(STATUS["logs"]) > 200:
            STATUS["logs"] = STATUS["logs"][-200:]

def user_continue():
    _continue_event.set()

def log(msg, tag=""):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"ok": "[OK]", "warn": "[!!]", "err": "[XX]"}.get(tag, "    ")
    line = f"[{ts}] {prefix} {msg}"
    print(line, flush=True)
    STATUS["logs"].append(line)
    if len(STATUS["logs"]) > 200:
        STATUS["logs"] = STATUS["logs"][-200:]
    STATUS["message"] = msg


# ── 경로 설정 ────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE  = os.path.join(BASE_DIR, "wing_cookies.json")
DOWNLOAD_DIR = str(Path.home() / "Downloads")
WING_URL     = "https://wing.coupang.com/tenants/rfm/settlements/status-new"
BASE_API     = "https://wing.coupang.com/tenants/rfm/v2/settlements"

REPORT_TYPES = ["CATEGORY_TR", "WAREHOUSING_SHIPPING", "STORAGE_FEE"]


# ── 쿠키 저장 / 로드 ─────────────────────────────────────────────────────
def save_cookies(driver):
    cookies = driver.get_cookies()
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f)
    log(f"쿠키 저장됨 ({len(cookies)}개)", "ok")

def load_cookie_file():
    if not os.path.exists(COOKIE_FILE):
        return None
    try:
        with open(COOKIE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def cookies_to_header(cookie_list):
    """Selenium 쿠키 목록 → Cookie 헤더 문자열"""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookie_list)

def get_xsrf(cookie_list):
    for c in cookie_list:
        if c["name"] == "XSRF-TOKEN":
            return c["value"]
    return ""

def build_headers(cookie_list):
    xsrf = get_xsrf(cookie_list)
    return {
        "Content-Type":  "application/json",
        "Accept":        "application/json, text/plain, */*",
        "Origin":        "https://wing.coupang.com",
        "Referer":       WING_URL,
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "x-xsrf-token":  xsrf,
        "Cookie":        cookies_to_header(cookie_list),
    }


# ── Selenium 로그인 (쿠키 취득용) ────────────────────────────────────────
def selenium_login():
    """브라우저 창 열어 로그인 → 쿠키 저장 후 반환"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    log("Chrome 브라우저 열어서 로그인 필요...", "warn")
    opt = Options()
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--start-maximized")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)
    driver.get(WING_URL)
    time.sleep(2)

    # 로그인 대기
    set_status("waiting", "브라우저에서 Wing 로그인 후 [계속] 버튼을 눌러주세요")
    _continue_event.wait()
    _continue_event.clear()
    time.sleep(2)

    save_cookies(driver)
    cookies = driver.get_cookies()
    driver.quit()
    return cookies


# ── 인증 확인 ────────────────────────────────────────────────────────────
def extract_cookies_from_chrome():
    """포트 9222 Chrome에서 쿠키 추출 후 저장. 실패 시 None."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        opt = Options()
        opt.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)
        cookies = driver.get_cookies()
        if any(c["name"] == "XSRF-TOKEN" for c in cookies):
            save_cookies(driver)
            log(f"Chrome에서 쿠키 추출 완료 ({len(cookies)}개)", "ok")
            return cookies
        log("Chrome 쿠키에 XSRF-TOKEN 없음 — 로그인 필요", "warn")
        return None
    except Exception as e:
        log(f"Chrome 쿠키 추출 실패: {e}", "warn")
        return None


def ensure_auth():
    """저장된 쿠키 로드 또는 Chrome에서 추출. 쿠키 목록 반환."""
    import requests

    def _is_valid(cookies):
        headers = build_headers(cookies)
        try:
            r = requests.post(f"{BASE_API}/status/api",
                              headers=headers,
                              json={"startDate": "2026-03-31T15:00:00.000Z",
                                    "endDate":   "2026-04-29T15:00:00.000Z",
                                    "searchDateType": "SALES"},
                              timeout=10)
            return r.status_code == 200 and "application/json" in r.headers.get("Content-Type", "")
        except Exception:
            return False

    # 1) 저장된 쿠키 확인
    cookies = load_cookie_file()
    if cookies and _is_valid(cookies):
        log("저장된 쿠키 유효", "ok")
        return cookies

    log("쿠키 만료 — 열려있는 Chrome에서 추출 시도...", "warn")

    # 2) 포트 9222 Chrome에서 쿠키 추출
    for _ in range(3):
        cookies = extract_cookies_from_chrome()
        if cookies and _is_valid(cookies):
            log("Chrome 쿠키 유효", "ok")
            return cookies
        set_status("waiting", "Wing에 로그인 후 잠시 기다려주세요...")
        import time as _t; _t.sleep(10)

    # 3) 마지막 수단: 새 Selenium 창
    log("Chrome 쿠키 추출 실패 — 새 브라우저 창으로 로그인", "warn")
    return selenium_login()


# ── API ①: 정산 목록 조회 → 70% groupKey 추출 ───────────────────────────
def kst_to_utc(date_str):
    """'2026-04-01' → '2026-03-31T15:00:00.000Z'"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=9)))
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def fetch_group_keys(headers, start_date, end_date):
    """start_date, end_date: 'YYYY-MM-DD' (KST)"""
    import requests
    payload = {
        "startDate":      kst_to_utc(start_date),
        "endDate":        kst_to_utc(end_date),
        "searchDateType": "SALES",
    }
    log(f"정산 목록 조회: {start_date} ~ {end_date}")
    r = requests.post(f"{BASE_API}/status/api", headers=headers,
                      json=payload, timeout=15)
    r.raise_for_status()
    ct = r.headers.get("Content-Type", "")
    if "application/json" not in ct:
        raise Exception("Wing 인증 실패 — 쿠키가 만료되었습니다. 다시 시도해 로그인해주세요.")
    data = r.json()

    reports = data.get("settlementStatusReports", [])
    keys = [x["settlementGroupKey"] for x in reports
            if x.get("settlementRatio") == 70 and x.get("settlementGroupKey")]
    log(f"70% 행 {len(keys)}개: {keys}", "ok")
    return keys


# ── API ②: 리포트 다운로드 큐잉 → requestId 목록 반환 ──────────────────
def queue_reports(headers, group_keys):
    """3종 × N주 리포트 큐잉. {(rtype, gkey): requestId} 딕셔너리 반환."""
    import requests
    request_ids = {}
    queue_start = int(time.time() * 1000)

    for gkey in group_keys:
        for rtype in REPORT_TYPES:
            payload = {
                "sellerReportType":    rtype,
                "requestTime":         str(int(time.time() * 1000)),
                "locale":              "ko",
                "settlementGroupKeys": [gkey],
            }
            r = requests.post(f"{BASE_API}/request-download/api",
                              headers=headers, json=payload, timeout=15)
            if r.status_code == 200:
                rid = r.json().get("requestId", "")
                request_ids[(rtype, gkey)] = rid
                log(f"큐잉 완료: {rtype} / {gkey} → {rid}", "ok")
            else:
                log(f"큐잉 실패: {rtype} / {gkey} ({r.status_code})", "warn")
            time.sleep(0.5)

    return request_ids, queue_start


# ── API ③: 상태 폴링 → URL 조회 → 파일 다운로드 ────────────────────────
def poll_and_download(headers, request_ids, queue_start, dest_dir):
    """
    1) /download-list/api {requestTimeFrom, requestTimeTo} → COMPLETED 확인
    2) /download/api/v2  {requestId} → S3 URL 반환
    3) S3 URL GET → 파일 저장
    """
    import requests
    os.makedirs(dest_dir, exist_ok=True)
    downloaded_files = []
    done_ids = set()
    expected = len(request_ids)
    max_wait = 180
    poll_interval = 8
    t_start = time.time()

    set_status(progress=0, total=expected)
    log(f"파일 생성 대기 중... ({expected}개)", "ok")

    while time.time() - t_start < max_wait:
        elapsed = int(time.time() - t_start)
        remaining_ids = {rt: rid for rt, rid in request_ids.items() if rid not in done_ids}
        log(f"상태 확인 중... ({elapsed}초 경과, {len(downloaded_files)}/{expected} 완료)")

        now_ms = int(time.time() * 1000)
        try:
            r = requests.post(f"{BASE_API}/download-list/api",
                              headers=headers,
                              json={"requestTimeFrom": str(queue_start - 5000),
                                    "requestTimeTo":   str(now_ms + 60000)},
                              timeout=15)

            if r.status_code in (401, 403):
                log("인증 만료", "err")
                return downloaded_files

            if r.status_code != 200:
                log(f"목록 조회 실패: {r.status_code}", "warn")
                time.sleep(poll_interval)
                continue

            items = r.json() if isinstance(r.json(), list) else []
            completed_map = {x["requestId"]: x for x in items
                             if x.get("downloadStatus") == "COMPLETED"}

            for key, rid in list(remaining_ids.items()):
                if rid not in completed_map:
                    continue
                item = completed_map[rid]
                label = f"{key[0]}/{key[1]}" if isinstance(key, tuple) else key
                # URL 조회: payload는 {requestTime, locale}
                url_r = requests.post(f"{BASE_API}/download/api/v2",
                                      headers=headers,
                                      json={"requestTime": str(item["requestTime"]),
                                            "locale":      "ko"},
                                      timeout=15)
                if url_r.status_code != 200:
                    log(f"URL 조회 실패: {label} ({url_r.status_code})", "warn")
                    continue

                url = url_r.json().get("url", "")
                if not url:
                    log(f"URL 없음: {label}", "warn")
                    continue

                fname = _url_to_filename(url)
                fpath = os.path.join(dest_dir, fname)
                log(f"다운로드 중: {fname}")
                dl_r = requests.get(url, timeout=60)
                if dl_r.status_code == 200:
                    with open(fpath, "wb") as f:
                        f.write(dl_r.content)
                    downloaded_files.append(fname)
                    done_ids.add(rid)
                    set_status(progress=len(downloaded_files))
                    log(f"완료 ({len(downloaded_files)}/{expected}): {fname}", "ok")

        except Exception as e:
            log(f"폴링 오류: {e}", "warn")

        if len(downloaded_files) >= expected:
            break
        time.sleep(poll_interval)

    return downloaded_files


def _url_to_filename(url):
    """S3 URL에서 파일명 추출. 없으면 타임스탬프 기반 이름."""
    try:
        path = url.split("?")[0].rstrip("/")
        name = path.split("/")[-1]
        if name.endswith(".xlsx"):
            return name
    except Exception:
        pass
    return f"wing_{int(time.time())}.xlsx"


# ── 전체 흐름 ────────────────────────────────────────────────────────────
def run_download(start_date=None, end_date=None):
    """
    Flask 백그라운드 스레드에서 호출.
    start_date, end_date: 'YYYY-MM-DD' (없으면 지난달 전체 자동)
    """
    global _continue_event
    _continue_event = threading.Event()
    STATUS.update({"state": "running", "message": "", "progress": 0,
                   "total": 0, "folder": None, "files": [], "logs": []})

    # 날짜 기본값: 지난달 1일 ~ 말일
    if not start_date or not end_date:
        today = datetime.now()
        first = today.replace(day=1) - timedelta(days=1)
        start_date = first.replace(day=1).strftime("%Y-%m-%d")
        end_date   = first.strftime("%Y-%m-%d")

    try:
        set_status("running", "인증 중...")
        cookies = ensure_auth()
        headers = build_headers(cookies)

        set_status("running", "정산 목록 조회 중...")
        group_keys = fetch_group_keys(headers, start_date, end_date)
        if not group_keys:
            set_status("error", "70% 정산 행을 찾지 못했습니다. 날짜 범위를 확인하세요.")
            return

        set_status("running", f"{len(group_keys)}주 × 3종 리포트 큐잉 중...")

        request_ids, queue_start = queue_reports(headers, group_keys)
        if not request_ids:
            set_status("error", "큐잉 실패 — Wing API 응답을 확인하세요.")
            return

        expected_count = len(request_ids)  # 3종 × N주
        set_status("running", f"큐잉 완료 ({expected_count}개) — 파일 생성 대기 중...",
                   total=expected_count)
        time.sleep(15)

        dl_time  = datetime.now()
        dest_dir = os.path.join(DOWNLOAD_DIR, "rocketg_" + dl_time.strftime("%Y%m%d_%H%M%S"))
        files    = poll_and_download(headers, request_ids, queue_start, dest_dir)

        if files:
            STATUS["folder"] = dest_dir
            STATUS["files"]  = files
            set_status("done", f"완료! {len(files)}개 파일 저장됨",
                       progress=len(files), total=len(files))
            log(f"저장 위치: {dest_dir}", "ok")
        else:
            set_status("error", "다운로드된 파일이 없습니다.")

    except Exception as e:
        import traceback; traceback.print_exc()
        set_status("error", f"오류: {e}")
