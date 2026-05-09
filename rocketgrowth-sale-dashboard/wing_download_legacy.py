# -*- coding: utf-8 -*-
"""
쿠팡 Wing 정산 파일 자동 다운로드
- 매출인식일 기준: 판매수수료 / 입출고배송비 / 보관비
"""

import os, sys, time, shutil, glob, threading
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Flask 연동용 전역 상태 ──────────────────────────────────────────────
STATUS = {
    "state":    "idle",   # idle | running | waiting | done | error
    "message":  "",
    "progress": 0,
    "total":    0,
    "folder":   None,
    "files":    [],
    "logs":     [],
}
_continue_event = threading.Event()   # 사용자가 "계속" 눌렀을 때 set()


def set_status(state=None, message=None, progress=None, total=None):
    if state:    STATUS["state"]    = state
    if message:  STATUS["message"]  = message
    if progress is not None: STATUS["progress"] = progress
    if total is not None:    STATUS["total"]    = total
    if message:
        STATUS["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        if len(STATUS["logs"]) > 200:
            STATUS["logs"] = STATUS["logs"][-200:]


def user_continue():
    """Flask에서 사용자가 '계속' 버튼 눌렀을 때 호출"""
    _continue_event.set()

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

ONEDRIVE_DIR = r"C:\Users\noah_remian\OneDrive - 케이엠인터트레이드\문서 - bubu\060_매출\쿠팡정산ai"
DOWNLOAD_DIR = str(Path.home() / "Downloads")
WING_URL     = "https://wing.coupang.com/tenants/rfm/settlements/status-new"
REPORTS      = ["판매수수료 리포트", "입출고/배송비 리포트", "보관비 리포트"]


def log(msg, tag=""):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"ok": "[OK]", "warn": "[!!]", "err": "[XX]"}.get(tag, "    ")
    line = f"[{ts}] {prefix} {msg}"
    print(line, flush=True)
    STATUS["logs"].append(line)
    if len(STATUS["logs"]) > 200:
        STATUS["logs"] = STATUS["logs"][-200:]
    STATUS["message"] = msg


def jclick(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.15)
    driver.execute_script("arguments[0].click();", el)


def find_visible(driver, css, text, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            try:
                if el.is_displayed() and text in el.text:
                    return el
            except Exception:
                pass
        time.sleep(0.35)
    return None


def wait_overlay_gone(driver, timeout=4):
    end = time.time() + timeout
    while time.time() < end:
        sels = '[data-wuic-partial="backdrop"],[class*="backdrop"],[class*="Backdrop"],[class*="loading-mask"]'
        overlays = driver.find_elements(By.CSS_SELECTOR, sels)
        if not any(o.is_displayed() for o in overlays):
            return
        time.sleep(0.2)




COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wing_cookies.json")


def get_driver(headless=False):
    opt = Options()
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_experimental_option("prefs", {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    })
    if headless:
        opt.add_argument("--headless=new")
        opt.add_argument("--window-size=1920,1080")
    else:
        opt.add_argument("--start-maximized")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)


def save_cookies(driver):
    import json
    cookies = driver.get_cookies()
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f)
    log(f"쿠키 저장됨 ({len(cookies)}개)", "ok")


def load_cookies(driver):
    import json
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        with open(COOKIE_FILE, encoding="utf-8") as f:
            cookies = json.load(f)
        for c in cookies:
            c.pop("sameSite", None)
            try:
                driver.add_cookie(c)
            except Exception:
                pass
        log(f"쿠키 복원됨 ({len(cookies)}개)", "ok")
        return True
    except Exception as e:
        log(f"쿠키 로드 실패: {e}", "warn")
        return False


def is_login_page(driver):
    url = driver.current_url.lower()
    return "login" in url or "signin" in url or "auth" in url


def try_cookie_login(driver):
    """쿠키로 로그인 시도. 성공하면 True, 로그인 페이지면 False"""
    if not os.path.exists(COOKIE_FILE):
        return False
    log("저장된 쿠키로 로그인 시도...")
    driver.get("https://wing.coupang.com")
    time.sleep(1)
    load_cookies(driver)
    driver.get(WING_URL)
    time.sleep(3)
    return not is_login_page(driver)


def ensure_login(driver, use_event=False):
    """쿠키로 로그인 복원 시도, 실패하면 수동 로그인 후 쿠키 저장"""
    if os.path.exists(COOKIE_FILE):
        log("저장된 쿠키로 로그인 시도...")
        driver.get("https://wing.coupang.com")
        time.sleep(1)
        load_cookies(driver)
        driver.get(WING_URL)
        time.sleep(3)
    else:
        driver.get(WING_URL)
        time.sleep(3)

    if is_login_page(driver):
        log("로그인 필요 — 브라우저에서 로그인해주세요", "warn")
        if use_event:
            STATUS["state"] = "waiting"
            STATUS["message"] = "로그인 후 [계속] 버튼을 눌러주세요"
            _continue_event.wait()
            _continue_event.clear()
        else:
            input("  -> 로그인 완료 후 Enter > ")
        time.sleep(2)
        save_cookies(driver)
        log("쿠키 저장 완료 — 다음부터 자동 로그인됩니다", "ok")
        driver.get(WING_URL)
        time.sleep(2)
    else:
        log("로그인 확인", "ok")


def set_conditions(driver, start, end):
    log(f"검색 조건 설정: {start} ~ {end}")

    # 정산일 -> 매출인식일
    trigger = find_visible(driver,
        "button, [class*='select'] span, [role='combobox'], [role='button']",
        "정산일", timeout=8)
    if trigger:
        jclick(driver, trigger)
        time.sleep(0.8)
        opt = find_visible(driver, "li, [role='option'], [class*='option']",
                           "매출인식일", timeout=5)
        if opt:
            jclick(driver, opt)
            log("매출인식일 선택", "ok")
            time.sleep(0.8)
        else:
            log("매출인식일 옵션 못찾음 - 수동 선택 후 Enter", "warn")
            input("  -> Enter > ")
    else:
        log("정산일 드롭다운 못찾음 (이미 매출인식일 가능)", "warn")

    wait_overlay_gone(driver)

    # 날짜 JS 주입 (인자로 전달해 f-string 이스케이프 문제 회피)
    script = """
        var inputs = Array.from(document.querySelectorAll('input')).filter(function(el) {
            var p = (el.placeholder || '').toLowerCase();
            var t = el.type || '';
            return t === 'date' || p.includes('yyyy') || p.includes('날짜')
                || p.includes('시작') || p.includes('연도');
        });
        if (inputs.length < 2) return 0;
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inputs[0], arguments[0]);
        inputs[0].dispatchEvent(new Event('input',  {bubbles:true}));
        inputs[0].dispatchEvent(new Event('change', {bubbles:true}));
        setter.call(inputs[1], arguments[1]);
        inputs[1].dispatchEvent(new Event('input',  {bubbles:true}));
        inputs[1].dispatchEvent(new Event('change', {bubbles:true}));
        return inputs.length;
    """
    injected = driver.execute_script(script, start, end)

    if injected and injected >= 2:
        log(f"날짜 설정 완료 ({injected}개 필드)", "ok")
    else:
        log("날짜 자동 설정 실패 - 수동 설정 후 Enter", "warn")
        input("  -> Enter > ")

    btn = (find_visible(driver, "button", "조회", timeout=4) or
           find_visible(driver, "button", "검색", timeout=4))
    if btn:
        jclick(driver, btn)
        log("검색 클릭", "ok")
    else:
        log("검색 버튼 못찾음 - 수동 검색 후 Enter", "warn")
        input("  -> Enter > ")

    time.sleep(3)
    wait_overlay_gone(driver)


def find_70_rows(driver):
    result = []
    for tr in driver.find_elements(By.CSS_SELECTOR, "tbody tr"):
        for td in tr.find_elements(By.CSS_SELECTOR, "td"):
            if td.text.strip() in ("70", "70%"):
                result.append(tr)
                break
    return result


POPUP_CLOSE_SELS = [
    "button[aria-label='closed']",
    "button[aria-label='닫기']",
    "button[aria-label='close']",
    "[class*='modal'] button[class*='close']",
    "[class*='popup'] button[class*='close']",
]


def wait_for_popup_btn(driver, timeout=6):
    """팝업 X 버튼이 실제로 나타날 때까지 대기 후 반환"""
    end = time.time() + timeout
    while time.time() < end:
        for sel in POPUP_CLOSE_SELS:
            for b in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if b.is_displayed():
                        return b
                except Exception:
                    pass
        time.sleep(0.2)
    return None


def close_popup(driver):
    """팝업이 나타날 때까지 기다렸다가 X 버튼 클릭"""
    btn = wait_for_popup_btn(driver, timeout=6)
    if btn:
        try:
            jclick(driver, btn)
            log("팝업 닫기", "ok")
            time.sleep(0.2)
            return True
        except Exception as e:
            log(f"팝업 닫기 실패: {e}", "warn")
    else:
        log("팝업 X 버튼 못찾음 (자동닫힘으로 간주)", "warn")
    return False


def find_excel_btn(row):
    """행에서 ⋮(엑셀 다운로드) 버튼 반환"""
    for b in row.find_elements(By.CSS_SELECTOR, "button"):
        if "엑셀 다운로드" in b.text:
            return b
    btns = row.find_elements(By.CSS_SELECTOR, "button")
    return btns[-1] if btns else None


def ensure_dropdown_open(driver, row_index):
    """드롭다운 아이템이 안 보이면 ⋮ 다시 클릭해서 열기"""
    visible = [el for el in driver.find_elements(By.CSS_SELECTOR, "button.drop-down-item")
               if el.is_displayed()]
    if visible:
        return True
    rows = find_70_rows(driver)
    if row_index >= len(rows):
        return False
    btn = find_excel_btn(rows[row_index])
    if btn:
        jclick(driver, btn)
        time.sleep(0.4)
        return True
    return False


def request_one_row(driver, row_index, rows_count, keep_last_popup=False):
    """
    ⋮ 클릭 → 3개 리포트 순서대로 요청(팝업 나타나면 닫기) → ⋮ 닫기
    keep_last_popup=True 이면 마지막 보관비 팝업 유지
    """
    rows = find_70_rows(driver)
    if row_index >= len(rows):
        log(f"행 {row_index+1} 재탐색 실패", "warn")
        return

    row = rows[row_index]
    log(f"행 {row_index+1}/{rows_count} 처리 중...")

    btn = find_excel_btn(row)
    if not btn:
        log(f"  ⋮ 버튼 못찾음", "warn")
        return

    jclick(driver, btn)
    time.sleep(0.4)

    for i, report in enumerate(REPORTS):
        is_last_overall = (i == len(REPORTS) - 1) and keep_last_popup

        # 드롭다운이 닫혀있으면 다시 열기
        ensure_dropdown_open(driver, row_index)

        item = find_visible(driver, "button.drop-down-item", report, timeout=4)
        if not item:
            item = find_visible(driver, "button.drop-down-item", report[:3], timeout=3)
        if not item:
            log(f"  [{report}] 드롭다운 항목 못찾음", "warn")
            continue

        jclick(driver, item)
        log(f"  [{report}] 요청됨", "ok")

        if is_last_overall:
            log(f"  다운로드 모달 유지 - 대기 시작")
            return

        # 팝업이 실제로 뜰 때까지 기다렸다가 닫기
        close_popup(driver)
        wait_overlay_gone(driver)

    # ⋮ 다시 클릭해 드롭다운 닫기
    try:
        rows2 = find_70_rows(driver)
        if row_index < len(rows2):
            btn2 = find_excel_btn(rows2[row_index])
            if btn2:
                jclick(driver, btn2)
                log(f"  행 {row_index+1} 드롭다운 닫기", "ok")
                time.sleep(0.3)
    except Exception as e:
        log(f"  드롭다운 닫기 실패: {e}", "warn")


def request_all_reports(driver, rows_count):
    for ri in range(rows_count):
        is_last_row = (ri == rows_count - 1)
        request_one_row(driver, ri, rows_count, keep_last_popup=is_last_row)
        if not is_last_row:
            time.sleep(0.4)


def open_dl_modal(driver):
    wait_overlay_gone(driver)
    btn = None
    for css in ["button", "a", "[role='button']", "span", "div"]:
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            try:
                t = el.text.strip()
                if "엑셀 다운로드 목록" in t and el.is_displayed():
                    btn = el
                    break
            except Exception:
                pass
        if btn:
            break
    if not btn:
        log("다운로드 목록 버튼 못찾음 - 수동으로 열고 Enter", "warn")
        input("  -> Enter > ")
        return
    jclick(driver, btn)
    log("다운로드 목록 모달 열림", "ok")
    time.sleep(2)


def refresh_dl_modal(driver):
    """모달 닫고 다시 열어서 목록 갱신"""
    # X 버튼으로 닫기 시도
    for sel in ["button[aria-label='closed']", "button[aria-label='닫기']",
                "button[aria-label='close']", "[class*='modal'] button[class*='close']"]:
        for b in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if b.is_displayed():
                    jclick(driver, b)
                    time.sleep(0.5)
                    break
            except Exception:
                pass
    time.sleep(0.5)
    open_dl_modal(driver)


def wait_and_download(driver, expected, timeout=300):
    """모달 내 활성화된 '다운로드' 버튼을 직접 찾아 전부 클릭"""
    log(f"다운로드 대기 중... ({expected}개 예상)")
    clicked_ids = set()
    downloaded = 0
    t_start = time.time()
    last_refresh = time.time()

    while time.time() - t_start < timeout:
        # 새로고침 버튼 클릭 (있으면)
        if time.time() - last_refresh >= 3:
            for label in ("새로 고침", "새로고침", "고침"):
                btn = find_visible(driver, "button", label, timeout=0.5)
                if btn:
                    try:
                        jclick(driver, btn)
                    except Exception:
                        pass
                    break
            last_refresh = time.time()

        # 활성화된 다운로드 버튼 - 위에서부터 expected개만
        # CSS class에 disabled가 있으면 회색(비활성) 버튼이므로 제외
        all_dl_btns = []
        for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
            try:
                if btn.text.strip() != "다운로드":
                    continue
                if not (btn.is_enabled() and btn.is_displayed()):
                    continue
                cls = btn.get_attribute("class") or ""
                if "disabled" in cls.lower():
                    continue
                if btn.get_attribute("disabled") is not None:
                    continue
                all_dl_btns.append(btn)
            except Exception:
                pass

        for btn in all_dl_btns[:expected]:
            try:
                bid = btn.id
                if bid in clicked_ids:
                    continue
                jclick(driver, btn)
                clicked_ids.add(bid)
                downloaded += 1
                log(f"다운로드 클릭 ({downloaded}/{expected})", "ok")
                STATUS["progress"] = downloaded
                time.sleep(0.8)
            except Exception:
                pass

        if downloaded >= expected:
            log(f"전체 다운로드 완료! ({downloaded}개)", "ok")
            break

        time.sleep(1)

    log(f"최종 다운로드: {downloaded}개", "ok" if downloaded else "warn")
    return downloaded


def wait_dl_finish(files_before, count, timeout=60):
    log("파일 저장 완료 대기 중...")
    end = time.time() + timeout
    while time.time() < end:
        new = [f for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx"))
               if f not in files_before]
        crdownloads = glob.glob(os.path.join(DOWNLOAD_DIR, "*.crdownload"))
        if len(new) >= count and not crdownloads:
            return new
        if len(new) >= count and crdownloads:
            # crdownload가 있어도 xlsx가 다 왔으면 잠깐만 더 대기
            time.sleep(2)
            new = [f for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx"))
                   if f not in files_before]
            return new
        time.sleep(0.5)
    return [f for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx"))
            if f not in files_before]


def move_to_folder(new_files, dl_time):
    folder_name = "rocketg_" + dl_time.strftime("%Y%m%d_%H%M%S")
    dest_dir = os.path.join(DOWNLOAD_DIR, folder_name)
    os.makedirs(dest_dir, exist_ok=True)
    moved = []
    for src in new_files:
        dst = os.path.join(dest_dir, os.path.basename(src))
        shutil.move(src, dst)
        moved.append(os.path.basename(src))
        log(f"  이동: {os.path.basename(src)}", "ok")
    return dest_dir, moved


def run_download():
    """Flask 백그라운드 스레드에서 호출. STATUS를 통해 진행상황 보고."""
    global _continue_event
    _continue_event = threading.Event()
    STATUS.update({"state":"running","message":"","progress":0,"total":0,
                   "folder":None,"files":[],"logs":[]})

    driver = None
    try:
        set_status("running", "Chrome 드라이버 준비 중...")

        # 쿠키 로그인 시도 → 성공하면 헤드리스(백그라운드), 실패하면 visible 창으로 진행
        driver = get_driver(headless=True)
        cookie_ok = try_cookie_login(driver)

        if not cookie_ok:
            log("쿠키 로그인 실패 — 브라우저 창을 열어서 로그인해주세요", "warn")
            driver.quit()
            driver = get_driver(headless=False)
            driver.get(WING_URL)
            time.sleep(2)
            # 로그인 필요하면 대기
            if is_login_page(driver):
                STATUS["state"] = "waiting"
                STATUS["message"] = "로그인 후 날짜 설정하고 검색해주세요 — 자동으로 감지됩니다"
                _continue_event.wait()
                _continue_event.clear()
                time.sleep(2)
                save_cookies(driver)
                log("쿠키 저장 완료 — 다음부터 백그라운드 실행됩니다", "ok")
        else:
            log("백그라운드 모드로 실행 중 (창 없음)", "ok")

        # 날짜 설정 후 검색하면 70% 행 자동 감지 (최대 3분 대기)
        set_status("waiting", "날짜를 설정하고 검색을 클릭해주세요 — 자동으로 감지합니다")
        rows70 = []
        t_wait = time.time()
        while time.time() - t_wait < 180:
            rows70 = find_70_rows(driver)
            if rows70:
                break
            time.sleep(1)

        if not rows70:
            set_status("waiting", "70% 행을 찾지 못했습니다. 검색 후 [계속] 클릭")
            _continue_event.wait()
            _continue_event.clear()
            rows70 = find_70_rows(driver)
        if not rows70:
            set_status("error", "70% 행 없음 - 종료")
            return

        rows70_count = len(rows70)
        expected = rows70_count * len(REPORTS)
        set_status("running", f"70% 행 {rows70_count}개 발견 — 리포트 요청 시작", progress=0, total=expected)
        log(f"70% 행 {rows70_count}개 발견", "ok")

        # 다운로드 직전 현재 파일 목록 확정 (이전 파일 혼입 방지)
        files_before = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")) +
                           glob.glob(os.path.join(DOWNLOAD_DIR, "*.xls")))
        request_all_reports(driver, rows70_count)

        set_status("running", "다운로드 대기 중...", progress=0, total=expected)
        count = wait_and_download(driver, expected=expected)

        if count > 0:
            dl_time = datetime.now()
            set_status("running", "파일 저장 완료 대기 중...")
            new_files = wait_dl_finish(files_before, count)
            if new_files:
                dest_dir, moved = move_to_folder(new_files, dl_time)
                STATUS["folder"] = dest_dir
                STATUS["files"]  = moved
                set_status("done", f"완료! {len(moved)}개 파일 저장됨", progress=len(moved), total=len(moved))
                log(f"저장 위치: {dest_dir}", "ok")
            else:
                set_status("error", "xlsx 파일 감지 실패")
        else:
            set_status("error", "다운로드된 파일 없음")

    except Exception as e:
        import traceback
        traceback.print_exc()
        set_status("error", f"오류: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def main():
    """커맨드라인 단독 실행용 (기존 방식 유지)"""
    print("\n" + "=" * 55)
    print("  쿠팡 Wing 정산 파일 자동 다운로드")
    print("=" * 55)

    driver = None
    try:
        log("Chrome 드라이버 준비 중...")
        driver = get_driver()
        driver.get(WING_URL)
        ensure_login(driver, use_event=False)

        log("Wing 페이지에서 날짜를 직접 설정하고 검색 후 Enter", "warn")
        input("  -> 검색 완료 후 Enter > ")

        rows70 = find_70_rows(driver)
        if not rows70:
            log("70% 행 없음 - 날짜/검색 확인 후 Enter", "warn")
            input("  -> Enter > ")
            rows70 = find_70_rows(driver)
        if not rows70:
            log("70% 행 없음 - 종료", "err")
            return

        rows70_count = len(rows70)
        log(f"70% 행 {rows70_count}개 발견", "ok")
        files_before = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")))

        request_all_reports(driver, rows70_count)
        expected = rows70_count * len(REPORTS)
        count = wait_and_download(driver, expected=expected)

        if count > 0:
            dl_time = datetime.now()
            new_files = wait_dl_finish(files_before, count)
            if new_files:
                dest_dir, moved = move_to_folder(new_files, dl_time)
                print("\n" + "=" * 55)
                print(f"  완료! {len(moved)}개 파일 저장됨")
                for f in moved: print(f"  -> {f}")
                print(f"  위치: {dest_dir}")
                print("=" * 55)
        else:
            log("다운로드된 파일 없음", "warn")

    except KeyboardInterrupt:
        log("사용자 중단", "warn")
    except Exception as e:
        log(f"오류: {e}", "err")
        import traceback; traceback.print_exc()
    finally:
        if driver:
            input("\n브라우저 닫으려면 Enter > ")
            driver.quit()


if __name__ == "__main__":
    main()
