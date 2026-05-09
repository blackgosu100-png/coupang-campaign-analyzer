# -*- coding: utf-8 -*-
"""
Wing 다운로드 모달 조작 (Selenium)
큐잉은 wing_api.py에서 완료된 상태로 진입.
"""
import os, sys, time, glob, shutil
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

DOWNLOAD_DIR = str(Path.home() / "Downloads")
WING_URL     = "https://wing.coupang.com/tenants/rfm/settlements/status-new"


def _log(msg, tag=""):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"ok": "[OK]", "warn": "[!!]", "err": "[XX]"}.get(tag, "    ")
    print(f"[{ts}] {prefix} {msg}", flush=True)


def _jclick(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.15)
    driver.execute_script("arguments[0].click();", el)


def _find_visible(driver, css, text, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            try:
                if el.is_displayed() and text in el.text:
                    return el
            except Exception:
                pass
        time.sleep(0.3)
    return None


def _wait_overlay_gone(driver, timeout=4):
    end = time.time() + timeout
    while time.time() < end:
        sels = '[data-wuic-partial="backdrop"],[class*="backdrop"],[class*="Backdrop"],[class*="loading-mask"]'
        if not any(o.is_displayed() for o in driver.find_elements(By.CSS_SELECTOR, sels)):
            return
        time.sleep(0.2)


def _get_driver():
    """기존 Chrome(원격 디버깅 포트 9222)에 붙기. 없으면 새 창 열기."""
    opt = Options()
    opt.add_experimental_option("prefs", {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    })
    try:
        opt.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)
        _ = driver.current_url  # 연결 확인
        _log("기존 Chrome에 연결됨", "ok")
        return driver, True  # True = 재사용 (quit 하면 안 됨)
    except Exception as e:
        _log(f"기존 Chrome 연결 실패 ({e}) — 새 창 열기", "warn")
        opt2 = Options()
        opt2.add_argument("--no-sandbox")
        opt2.add_argument("--disable-dev-shm-usage")
        opt2.add_argument("--start-maximized")
        opt2.add_argument("--disable-blink-features=AutomationControlled")
        opt2.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt2.add_experimental_option("prefs", {
            "download.default_directory": DOWNLOAD_DIR,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        })
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt2), False


def _close_notice_popup(driver):
    """공지 팝업 '닫기' 버튼 즉시 클릭. 없으면 무시."""
    try:
        for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
            if btn.text.strip() == "닫기" and btn.is_displayed():
                _jclick(driver, btn)
                _log("공지 팝업 닫기", "ok")
                time.sleep(0.5)
                return
    except Exception:
        pass


def _open_dl_modal(driver):
    _wait_overlay_gone(driver)
    for css in ["button", "a", "[role='button']", "span", "div"]:
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            try:
                if "엑셀 다운로드 목록" in el.text and el.is_displayed():
                    _jclick(driver, el)
                    _log("다운로드 목록 모달 클릭", "ok")
                    # 모달 제목으로 실제 열렸는지 확인
                    deadline = time.time() + 8
                    while time.time() < deadline:
                        if _get_modal(driver):
                            _log("다운로드 목록 모달 열림 확인", "ok")
                            time.sleep(1)
                            return True
                        time.sleep(0.5)
                    _log("모달 열림 확인 실패", "warn")
                    return False
            except Exception:
                pass
    _log("다운로드 목록 버튼 못찾음", "err")
    return False


def _get_modal(driver):
    """다운로드 목록 모달 컨테이너 반환. 없으면 None."""
    return driver.execute_script("""
        var all = Array.from(document.querySelectorAll('*'));
        for (var el of all) {
            if (el.textContent.includes('정산관리 엑셀 다운로드 목록') &&
                el.children.length > 0 &&
                window.getComputedStyle(el).display !== 'none') {
                return el;
            }
        }
        return null;
    """)

def _count_active_dl_btns(driver):
    try:
        return driver.execute_script("""
            var modal = null;
            var all = Array.from(document.querySelectorAll('*'));
            for (var el of all) {
                if (el.textContent.includes('정산관리 엑셀 다운로드 목록') &&
                    el.children.length > 0 &&
                    window.getComputedStyle(el).display !== 'none') {
                    modal = el;
                    break;
                }
            }
            var root = modal || document;
            var btns = Array.from(root.querySelectorAll('button'));
            return btns.filter(function(b) {
                var t = b.textContent.trim();
                if (t !== '다운로드') return false;
                if (b.disabled) return false;
                var cls = b.className || '';
                if (cls.toLowerCase().includes('disabled')) return false;
                var style = window.getComputedStyle(b);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                return true;
            }).length;
        """)
    except Exception:
        return 0


def _click_all_dl_btns(driver, expected, log_fn):
    downloaded = 0
    try:
        active_btns = driver.execute_script("""
            var modal = null;
            var all = Array.from(document.querySelectorAll('*'));
            for (var el of all) {
                if (el.textContent.includes('정산관리 엑셀 다운로드 목록') &&
                    el.children.length > 0 &&
                    window.getComputedStyle(el).display !== 'none') {
                    modal = el;
                    break;
                }
            }
            var root = modal || document;
            var btns = Array.from(root.querySelectorAll('button'));
            return btns.filter(function(b) {
                var t = b.textContent.trim();
                if (t !== '다운로드') return false;
                if (b.disabled) return false;
                var cls = b.className || '';
                if (cls.toLowerCase().includes('disabled')) return false;
                var style = window.getComputedStyle(b);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                return true;
            }).slice(0, arguments[0]);
        """, expected)
        for btn in active_btns:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.1)
                driver.execute_script("arguments[0].click();", btn)
                downloaded += 1
                log_fn(f"다운로드 클릭 ({downloaded}/{expected})", "ok")
                time.sleep(0.8)
            except Exception:
                pass
    except Exception as e:
        log_fn(f"버튼 클릭 오류: {e}", "warn")
    return downloaded


def _refresh_modal(driver):
    for label in ("새로 고침", "새로고침"):
        btn = _find_visible(driver, "button", label, timeout=1)
        if btn:
            try:
                _jclick(driver, btn)
            except Exception:
                pass
            return


def _wait_dl_finish(files_before, count, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        new = [f for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")) if f not in files_before]
        crdownloads = glob.glob(os.path.join(DOWNLOAD_DIR, "*.crdownload"))
        if len(new) >= count and not crdownloads:
            return new
        time.sleep(0.5)
    return [f for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")) if f not in files_before]


def _move_to_folder(new_files, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    moved = []
    for src in new_files:
        dst = os.path.join(dest_dir, os.path.basename(src))
        shutil.move(src, dst)
        moved.append(os.path.basename(src))
        _log(f"이동: {os.path.basename(src)}", "ok")
    return moved


def download_queued_files(cookies, expected_count, dest_dir, log_fn=None, max_wait=300):
    """
    wing_api.py 큐잉 완료 후 호출.
    cookies  : wing_api에서 사용한 쿠키 목록
    expected_count : 다운로드 예상 파일 수 (리포트 종류 수, 예: 3)
    dest_dir : 최종 파일 저장 폴더
    log_fn   : log(msg, tag) 형식 콜백 (없으면 print 사용)
    반환: (dest_dir, [파일명, ...])
    """
    if log_fn is None:
        log_fn = _log

    driver = None
    reuse = False
    try:
        log_fn("Chrome 연결 중...", "")
        driver, reuse = _get_driver()

        # Wing 탭으로 전환 (여러 탭 중 rfm/settlements 탭 찾기)
        handles = driver.window_handles
        print(f"[DEBUG] 열린 탭 수: {len(handles)}", flush=True)
        for h in handles:
            try:
                driver.switch_to.window(h)
                url = driver.current_url
                print(f"[DEBUG] 탭: {url}", flush=True)
                if "wing.coupang.com" in url:
                    log_fn(f"Wing 탭 선택됨: {url}", "ok")
                    break
            except Exception:
                pass

        # 현재 URL 확인 — 이미 정산 페이지면 이동 안 함
        current_url = driver.current_url
        log_fn(f"현재 URL: {current_url}", "")
        if "rfm/settlements" not in current_url:
            log_fn("정산 페이지로 이동 중...", "")
            driver.get(WING_URL)
            time.sleep(4)
            current_url = driver.current_url

        # 로그인 여부 확인
        if "login" in current_url.lower() or "signin" in current_url.lower() or "auth" in current_url.lower():
            log_fn("로그인 상태 아님 — 브라우저에서 로그인 후 60초 대기...", "err")
            time.sleep(60)
            current_url = driver.current_url
            if "login" in current_url.lower():
                print(f"[DEBUG] page_source[:2000]:\n{driver.page_source[:2000]}", flush=True)
                try:
                    driver.save_screenshot("error_debug.png")
                    print("[DEBUG] 스크린샷 저장: error_debug.png", flush=True)
                except Exception:
                    pass
                raise Exception("로그인 실패 — 쿠키 재취득 필요")
        else:
            log_fn("로그인 상태 확인됨", "ok")

        # 공지 팝업 닫기
        log_fn("공지 팝업 확인 중...", "")
        _close_notice_popup(driver)
        time.sleep(1)

        log_fn("다운로드 목록 모달 열기...", "")
        if not _open_dl_modal(driver):
            print(f"[DEBUG] 모달 실패 시 URL: {driver.current_url}", flush=True)
            print(f"[DEBUG] page_source[:2000]:\n{driver.page_source[:2000]}", flush=True)
            try:
                driver.save_screenshot("error_debug.png")
            except Exception:
                pass
            raise Exception("다운로드 목록 모달을 열 수 없습니다")

        # 파일 생성 대기: 새로고침하면서 활성 버튼이 expected_count 이상 될 때까지 폴링
        log_fn(f"파일 생성 대기 중... (상위 {expected_count}개 활성화 기다리는 중)", "")
        t_start = time.time()
        last_refresh = 0

        while time.time() - t_start < max_wait:
            if time.time() - last_refresh >= 8:
                _refresh_modal(driver)
                last_refresh = time.time()

            active = _count_active_dl_btns(driver)
            elapsed = int(time.time() - t_start)
            log_fn(f"활성 버튼 {active}개 확인 중... ({elapsed}초 경과)", "")

            if active >= expected_count:
                log_fn(f"활성 버튼 {active}개 확인 — 상위 {expected_count}개 다운로드 시작", "ok")
                break

            time.sleep(8)
        else:
            active = _count_active_dl_btns(driver)
            if active == 0:
                raise Exception("활성 버튼 0개 — 파일 생성 실패")
            log_fn(f"대기 시간 초과 — 활성 버튼 {active}개 중 상위 {expected_count}개 다운로드", "warn")

        files_before = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")) +
                           glob.glob(os.path.join(DOWNLOAD_DIR, "*.xls")))

        # 상위 expected_count개만 클릭 (모달은 최신순 = 맨 위가 신규)
        count = _click_all_dl_btns(driver, expected_count, log_fn)
        log_fn(f"{count}개 클릭 완료 — 파일 저장 대기 중...", "ok")

        new_files = _wait_dl_finish(files_before, count)
        if not new_files:
            raise Exception("xlsx 파일이 감지되지 않았습니다")

        moved = _move_to_folder(new_files, dest_dir)
        log_fn(f"완료! {len(moved)}개 파일 저장됨 → {dest_dir}", "ok")
        return dest_dir, moved

    finally:
        # 기존 Chrome 재사용 시 quit 하지 않음 (사용자 창 유지)
        if driver and not reuse:
            try:
                driver.quit()
            except Exception:
                pass
