# -*- coding: utf-8 -*-
"""
쿠팡 Wing 할인가 강조 쿠폰 관리
흐름: 쿠폰 생성(상품 없이) → 즉시 활성화 → 상품수정 > 모달로 옵션ID 추가
"""
import os, sys, json, time, threading, re
from datetime import datetime, date, timedelta

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

COUPON_URL    = "https://wing.coupang.com/front/seller-promotion-platform/sfc/coupon/new/coupon-list"
COOKIE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wing_cookies.json")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coupon_settings.json")

STATUS = {
    "state": "idle", "message": "", "logs": [],
    "coupons": [],
}
_continue_event = threading.Event()


# ── 유틸 ──────────────────────────────────────────────────────────────────

def log(msg, tag=""):
    ts     = datetime.now().strftime("%H:%M:%S")
    prefix = {"ok":"[OK]","warn":"[!!]","err":"[XX]"}.get(tag, "    ")
    line   = f"[{ts}] {prefix} {msg}"
    print(line, flush=True)
    STATUS["logs"].append(line)
    if len(STATUS["logs"]) > 200:
        STATUS["logs"] = STATUS["logs"][-200:]
    STATUS["message"] = msg


def user_continue():
    _continue_event.set()


def parse_date(text):
    text = text.strip().replace(" ", "")
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d%H:%M:%S", "%Y-%m-%d%H:%M:%S"):
        try:
            return datetime.strptime(text[:10] if len(text) > 10 else text, fmt[:8]).date()
        except ValueError:
            pass
    return None


def coupon_status_label(end_date):
    if not end_date:
        return "unknown"
    today = date.today()
    diff  = (end_date - today).days
    if diff < 0:
        return "expired"
    if diff <= 3:
        return "soon"
    return "active"


# ── 드라이버 ──────────────────────────────────────────────────────────────

def get_driver(headless=False):
    opt = Options()
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])
    if headless:
        opt.add_argument("--headless=new")
        opt.add_argument("--window-size=1920,1080")
    else:
        opt.add_argument("--start-maximized")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)


def load_cookies(driver):
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        with open(COOKIE_FILE, encoding="utf-8") as f:
            cookies = json.load(f)
        for c in cookies:
            c.pop("sameSite", None)
            try: driver.add_cookie(c)
            except Exception: pass
        return True
    except Exception:
        return False


def save_cookies(driver):
    cookies = driver.get_cookies()
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f)
    log(f"쿠키 저장됨 ({len(cookies)}개)", "ok")


def is_login_page(driver):
    url = driver.current_url.lower()
    return "login" in url or "signin" in url or "auth" in url


def ensure_login(driver, use_event=False):
    driver.get("https://wing.coupang.com")
    time.sleep(1)
    load_cookies(driver)
    driver.get(COUPON_URL)
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
        driver.get(COUPON_URL)
        time.sleep(3)
    else:
        log("로그인 확인", "ok")


def _open_driver_with_login(use_event=True):
    driver = get_driver(headless=False)
    driver.get("https://wing.coupang.com")
    time.sleep(1)
    load_cookies(driver)
    driver.get(COUPON_URL)
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
        driver.get(COUPON_URL)
        time.sleep(3)
    else:
        log("로그인 확인", "ok")
        save_cookies(driver)
    return driver


# ── 설정 저장/로드 ─────────────────────────────────────────────────────────

def save_settings(coupons):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(coupons, f, ensure_ascii=False, indent=2)
    log(f"설정 저장됨 ({len(coupons)}개 쿠폰)", "ok")


def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return []
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ── Selenium 헬퍼 ──────────────────────────────────────────────────────────

def jclick(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.15)
    driver.execute_script("arguments[0].click();", el)


def find_btn(driver, text, timeout=5, container=None):
    root = container or driver
    end = time.time() + timeout
    while time.time() < end:
        for btn in root.find_elements(By.CSS_SELECTOR, "button"):
            try:
                if text in btn.text and btn.is_displayed() and btn.is_enabled():
                    return btn
            except Exception:
                pass
        time.sleep(0.3)
    return None


def wait_modal(driver, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        for sel in ["[role='dialog']", "[class*='modal']", "[class*='Modal']"]:
            els = [e for e in driver.find_elements(By.CSS_SELECTOR, sel) if e.is_displayed()]
            if els:
                return els[0]
        time.sleep(0.3)
    return None


def close_modal(driver):
    for sel in ["[role='dialog'] button[aria-label*='close']",
                "[role='dialog'] button[aria-label*='닫기']",
                "[role='dialog'] button[aria-label*='Close']"]:
        for b in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if b.is_displayed():
                    jclick(driver, b); time.sleep(0.5); return
            except Exception: pass
    # 텍스트 기반
    for btn in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'] button"):
        try:
            t = btn.text.strip()
            if t in ("닫기", "취소", "×", "✕", "X") and btn.is_displayed():
                jclick(driver, btn); time.sleep(0.5); return
        except Exception: pass


def set_input_value(driver, el, value):
    driver.execute_script("""
        var s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
        s.call(arguments[0], arguments[1]);
        arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
    """, el, value)


def set_textarea_value(driver, el, value):
    driver.execute_script("""
        var s = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
        s.call(arguments[0], arguments[1]);
        arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
        arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
    """, el, value)


def click_load_more(driver):
    clicked = 0
    while True:
        found = False
        for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
            try:
                t = btn.text.strip()
                if ("더보기" in t or "더 보기" in t) and btn.is_displayed():
                    jclick(driver, btn); time.sleep(1.5)
                    clicked += 1; found = True; break
            except Exception: pass
        if not found:
            break
    return clicked


# ── 쿠폰 목록 파싱 ────────────────────────────────────────────────────────

def find_coupon_rows(driver):
    """tbody tr 목록 반환. 더보기 버튼 먼저 처리."""
    click_load_more(driver)
    time.sleep(1)
    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
    if not rows:
        rows = driver.find_elements(By.CSS_SELECTOR,
            "[class*='TableRow'], [class*='table-row']")
    return rows


def find_row_by_name(driver, name):
    """쿠폰 이름으로 행 찾기"""
    for row in driver.find_elements(By.CSS_SELECTOR, "tbody tr"):
        if name in row.text:
            return row
    return None


def get_option_ids_from_product_table(driver):
    """적용 상품 모달의 테이블에서 옵션ID 읽기 (첫 번째 컬럼)"""
    option_ids = []
    for sel in ["[role='dialog'] tbody tr", "[class*='modal'] tbody tr"]:
        rows = driver.find_elements(By.CSS_SELECTOR, sel)
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if cells:
                id_text = cells[0].text.strip()
                if id_text and re.match(r'^\d+$', id_text):
                    option_ids.append(id_text)
        if option_ids:
            break
    return option_ids


def open_product_modal(driver, row):
    """행에서 '상품수정 >' 링크/버튼 클릭 → 모달 반환"""
    for el in row.find_elements(By.CSS_SELECTOR, "a, button, span"):
        try:
            t = el.text.strip()
            if "상품수정" in t and el.is_displayed():
                jclick(driver, el)
                return wait_modal(driver, timeout=5)
        except Exception:
            pass
    return None


def parse_coupon_rows(driver):
    """쿠폰 목록 파싱 + 각 쿠폰의 옵션ID 수집"""
    coupons = []
    rows = find_coupon_rows(driver)
    log(f"쿠폰 행 {len(rows)}개 감지", "ok" if rows else "warn")

    for i, row in enumerate(rows):
        try:
            full = row.text.strip()
            if not full:
                continue

            cells = row.find_elements(By.TAG_NAME, "td")
            cell_texts = [c.text.strip() for c in cells]

            # 쿠폰명: 첫 번째 셀 (ID와 이름 포함, 첫 줄이 이름)
            name = ""
            if cell_texts:
                name = cell_texts[0].split("\n")[0].strip()

            # 날짜 패턴 (쿠폰사용기간 컬럼)
            dates = re.findall(r'\d{4}-\d{2}-\d{2}', full)
            start_date = parse_date(dates[0]) if len(dates) >= 1 else None
            end_date   = parse_date(dates[1]) if len(dates) >= 2 else None

            # 할인방식 컬럼: "17,200원 (정액)" 또는 "10% (정률)"
            discount     = ""
            discount_type = "정액"
            for ct in cell_texts:
                m_amt = re.search(r'([\d,]+)원', ct)
                m_pct = re.search(r'(\d+(?:\.\d+)?)\s*%', ct)
                if "정액" in ct and m_amt:
                    discount      = m_amt.group(1).replace(",", "")
                    discount_type = "정액"
                    break
                if "정률" in ct and m_pct:
                    discount      = m_pct.group(1) + "%"
                    discount_type = "정률"
                    break
                if m_pct and "%" in ct:
                    discount      = m_pct.group(1) + "%"
                    discount_type = "정률"
                    break

            # fallback: full text에서 추출
            if not discount:
                m_amt = re.search(r'([\d,]+)원\s*\(정액\)', full)
                m_pct = re.search(r'(\d+(?:\.\d+)?)\s*%\s*\(정률\)', full)
                if m_amt:
                    discount = m_amt.group(1).replace(",", ""); discount_type = "정액"
                elif m_pct:
                    discount = m_pct.group(1) + "%"; discount_type = "정률"

            # 옵션ID: 상품수정 > 클릭 후 테이블에서 읽기
            option_ids = []
            try:
                modal = open_product_modal(driver, row)
                if modal:
                    time.sleep(1)
                    option_ids = get_option_ids_from_product_table(driver)
                    log(f"  [{i+1}] {name}: 옵션ID {len(option_ids)}개", "ok")
                    close_modal(driver)
                    time.sleep(0.8)
                    # 모달 닫힌 후 목록 재확인
                    driver.get(COUPON_URL)
                    time.sleep(2)
                    click_load_more(driver)
                    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            except Exception as e:
                log(f"  [{i+1}] 옵션ID 수집 실패: {e}", "warn")
                try: close_modal(driver)
                except Exception: pass

            coupon = {
                "name":          name,
                "discount":      discount,
                "discount_type": discount_type,
                "option_ids":    option_ids,
                "start_date":    start_date.isoformat() if start_date else "",
                "end_date":      end_date.isoformat()   if end_date   else "",
                "status":        coupon_status_label(end_date),
            }
            coupons.append(coupon)
            STATUS["message"] = f"쿠폰 파싱 중... ({i+1}/{len(rows)})"

        except Exception as e:
            log(f"행 {i+1} 파싱 오류: {e}", "warn")

    return coupons


# ── 쿠폰 생성 (2단계) ──────────────────────────────────────────────────────

def create_coupon_shell(driver, coupon_data):
    """
    1단계: 쿠폰 기본 정보만 생성 (상품 없이)
    coupon_data: {name, discount, discount_type("정액"/"정률"), duration_days}
    """
    name          = coupon_data.get("name", "")
    discount      = re.sub(r"[^0-9.]", "", coupon_data.get("discount", ""))
    disc_type     = coupon_data.get("discount_type", "정액")
    duration      = int(coupon_data.get("duration_days", 1))

    now     = datetime.now()
    end_dt  = (now + timedelta(days=duration)).replace(hour=23, minute=59)
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M")

    log(f"쿠폰 생성: {name} / {disc_type} {discount} / ~{end_str}")

    driver.get(COUPON_URL)
    time.sleep(2)

    # ① '쿠폰 만들기' 버튼
    create_btn = find_btn(driver, "쿠폰 만들기", timeout=6)
    if not create_btn:
        log("'쿠폰 만들기' 버튼 못찾음", "err"); return False
    jclick(driver, create_btn)
    time.sleep(1)

    modal = wait_modal(driver)
    if not modal:
        log("쿠폰 생성 모달 안 열림", "err"); return False

    # ② 쿠폰명 입력
    for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])"):
        try:
            if inp.is_displayed() and inp.is_enabled():
                ph = (inp.get_attribute("placeholder") or "")
                if "쿠폰" in ph or "이름" in ph or "원피스" in ph or ph == "":
                    inp.click(); inp.clear()
                    set_input_value(driver, inp, name)
                    log(f"쿠폰명 입력: {name}", "ok")
                    break
        except Exception: pass

    # ③ 즉시할인 라디오 선택 (있으면)
    for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
        try:
            label = driver.execute_script(
                "return arguments[0].closest('label') || arguments[0].parentElement;", inp)
            if label and "즉시" in (label.text or ""):
                jclick(driver, inp); time.sleep(0.3); break
        except Exception: pass

    # ④ 종료 날짜 입력 (datetime-local)
    date_inputs = [i for i in driver.find_elements(By.CSS_SELECTOR, "input[type='datetime-local']")
                   if i.is_displayed()]
    if date_inputs:
        # 마지막 datetime input = 종료일
        set_input_value(driver, date_inputs[-1], end_str)
        log(f"종료일 설정: {end_str}", "ok")
        if len(date_inputs) >= 2:
            start_str = now.strftime("%Y-%m-%dT%H:%M")
            set_input_value(driver, date_inputs[0], start_str)

    # ⑤ 할인 타입 라디오 (정액 / 정률)
    for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
        try:
            label = driver.execute_script(
                "return arguments[0].closest('label') || arguments[0].parentElement;", inp)
            lt = (label.text or "").strip() if label else ""
            if lt in (disc_type, disc_type[:2]):
                jclick(driver, inp); time.sleep(0.3); break
        except Exception: pass

    # ⑥ 할인 금액 / 할인율 입력
    # 정액: 원 단위 숫자, 정률: % 숫자
    ph_hints = {
        "정액": ["30,000", "금액", "원"],
        "정률": ["20", "예) 20", "%"],
    }.get(disc_type, [])

    filled = False
    for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='number'], input[type='text']"):
        try:
            if not inp.is_displayed() or not inp.is_enabled(): continue
            ph = (inp.get_attribute("placeholder") or "")
            if any(h in ph for h in ph_hints) or (not filled and discount):
                inp.click()
                set_input_value(driver, inp, discount)
                log(f"할인{disc_type} 입력: {discount}", "ok")
                filled = True
                break
        except Exception: pass

    # ⑦ '할인쿠폰 만들기' 제출 (상품 추가 없이)
    submit = find_btn(driver, "할인쿠폰 만들기", timeout=5)
    if not submit:
        log("'할인쿠폰 만들기' 버튼 못찾음", "err"); return False

    jclick(driver, submit)
    log("쿠폰 생성 제출", "ok")
    time.sleep(3)
    return True


def add_products_to_coupon(driver, coupon_name, option_ids):
    """
    2단계: 생성된 쿠폰에 '상품수정 >' → 옵션ID 추가
    """
    if not option_ids:
        log("옵션ID 없음 — 상품 추가 건너뜀", "warn")
        return True

    log(f"상품 추가: {coupon_name} / {len(option_ids)}개 옵션ID")

    driver.get(COUPON_URL)
    time.sleep(3)

    # 쿠폰 행 찾기
    row = find_row_by_name(driver, coupon_name)
    if not row:
        log(f"목록에서 '{coupon_name}' 못찾음", "err"); return False

    # '상품수정 >' 클릭
    modal = open_product_modal(driver, row)
    if not modal:
        log("상품 추가 모달 안 열림", "err"); return False

    time.sleep(1)

    # 요청사항 = 상품 추가 (기본값이어야 하지만 확인)
    for inp in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'] input[type='radio']"):
        try:
            label = driver.execute_script(
                "return arguments[0].closest('label') || arguments[0].parentElement;", inp)
            if label and "상품 추가" in (label.text or ""):
                if not inp.is_selected():
                    jclick(driver, inp)
                time.sleep(0.2)
                break
        except Exception: pass

    # 상품 추가 방식 = 옵션ID (기본값)
    for inp in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'] input[type='radio']"):
        try:
            label = driver.execute_script(
                "return arguments[0].closest('label') || arguments[0].parentElement;", inp)
            if label and "옵션ID" in (label.text or ""):
                if not inp.is_selected():
                    jclick(driver, inp)
                time.sleep(0.2)
                break
        except Exception: pass

    # textarea에 옵션ID 입력
    id_text = "\n".join(str(x) for x in option_ids)
    for ta in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'] textarea"):
        try:
            if ta.is_displayed():
                ta.click()
                set_textarea_value(driver, ta, id_text)
                log(f"옵션ID {len(option_ids)}개 입력", "ok")
                break
        except Exception: pass

    time.sleep(0.5)

    # '+쿠폰 적용 상품 추가' 버튼
    add_btn = find_btn(driver, "쿠폰 적용 상품 추가", timeout=5)
    if not add_btn:
        log("'+쿠폰 적용 상품 추가' 버튼 못찾음", "err"); return False

    jclick(driver, add_btn)
    log("상품 추가 버튼 클릭", "ok")
    time.sleep(3)

    # 결과 확인 (테이블에 행이 생겼는지)
    ids = get_option_ids_from_product_table(driver)
    if ids:
        log(f"상품 추가 완료: {len(ids)}개 확인", "ok")
    else:
        log("상품 추가 결과 확인 필요", "warn")

    # 모달 닫기
    close_modal(driver)
    time.sleep(1)
    return True


def create_coupon(driver, coupon_data):
    """쿠폰 생성 + 상품 추가 (2단계 전체)"""
    ok = create_coupon_shell(driver, coupon_data)
    if not ok:
        return False
    time.sleep(2)
    option_ids = coupon_data.get("option_ids", [])
    if option_ids:
        return add_products_to_coupon(driver, coupon_data["name"], option_ids)
    return True


# ── Flask 진입점 ──────────────────────────────────────────────────────────

def run_coupon_scan(use_event=True):
    global _continue_event
    _continue_event = threading.Event()
    STATUS.update({"state":"running","message":"","logs":[],"coupons":[]})

    driver = None
    try:
        log("Chrome 준비 중...")
        driver = _open_driver_with_login(use_event=use_event)

        STATUS["state"] = "running"
        log("쿠폰 목록 로딩 중...")
        driver.get(COUPON_URL)
        time.sleep(3)

        # 페이지 HTML 저장 (구조 분석용)
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coupon_page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log("페이지 HTML 저장됨 (coupon_page.html)", "ok")

        coupons = parse_coupon_rows(driver)

        STATUS["coupons"] = coupons
        if coupons:
            save_settings(coupons)
            log(f"쿠폰 {len(coupons)}개 파싱 완료", "ok")
            STATUS["state"] = "done"
            STATUS["message"] = f"{len(coupons)}개 쿠폰 로드됨"
        else:
            log("쿠폰 파싱 실패 — coupon_page.html 확인 필요", "warn")
            STATUS["state"] = "done"
            STATUS["message"] = "쿠폰 파싱 실패 — 페이지 구조 확인 필요"

    except Exception as e:
        import traceback; traceback.print_exc()
        STATUS["state"] = "error"
        STATUS["message"] = f"오류: {e}"
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass


def _do_renew(targets, use_event=True):
    if not targets:
        STATUS["state"] = "done"
        STATUS["message"] = "선택된 쿠폰 없음"
        return

    log(f"갱신 대상: {len(targets)}개")
    driver = None
    try:
        driver = _open_driver_with_login(use_event=use_event)

        ok_count = 0
        for i, c in enumerate(targets):
            log(f"[{i+1}/{len(targets)}] {c['name']} 갱신 중...")
            success = create_coupon(driver, {
                "name":          c["name"],
                "discount":      c.get("discount", ""),
                "discount_type": c.get("discount_type", "정액"),
                "option_ids":    c.get("option_ids", []),
                "duration_days": 1,
            })
            if success:
                ok_count += 1
                log(f"  완료", "ok")
            else:
                log(f"  실패 (수동 확인 필요)", "warn")

        STATUS["state"] = "done"
        STATUS["message"] = f"완료: {ok_count}/{len(targets)}개"

    except Exception as e:
        import traceback; traceback.print_exc()
        STATUS["state"] = "error"
        STATUS["message"] = f"오류: {e}"
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass


def run_coupon_renew(use_event=True):
    global _continue_event
    _continue_event = threading.Event()
    STATUS.update({"state":"running","message":"","logs":[]})
    settings = load_settings()
    if not settings:
        STATUS["state"] = "error"
        STATUS["message"] = "저장된 설정 없음 — 먼저 [쿠폰 현황 가져오기] 실행"
        return
    targets = [c for c in settings if c.get("status") in ("expired", "soon")]
    _do_renew(targets, use_event=use_event)


def run_coupon_renew_selected(coupon_list, use_event=True):
    global _continue_event
    _continue_event = threading.Event()
    STATUS.update({"state":"running","message":"","logs":[]})
    _do_renew(coupon_list, use_event=use_event)
