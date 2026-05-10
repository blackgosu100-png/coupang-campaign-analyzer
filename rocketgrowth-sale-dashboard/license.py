# -*- coding: utf-8 -*-
"""
수강생 라이선스 검증 — Supabase vendorId 화이트리스트 방식
"""
import os, json, requests as _req
from datetime import datetime

SUPABASE_URL = "https://idtcsayclkxsfakouaww.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlkdGNzYXljbGt4c2Zha291YXd3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgzMzMzOTYsImV4cCI6MjA5MzkwOTM5Nn0.QIS2vgBacmkBwJu0l_pALNP5ZyDBA-mme5KT1uffx4Q"
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeSzCrNeH0ZzfEFHYD5KT1tnTle4-E8ET3j9ASXITv1C8Fbow/viewform"
VENDOR_ENTRY    = "entry.1452200275"

# vendorId는 쿠키에서 추출 (sc_vid 쿠키)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "license_cache.json")


def get_vendor_id_from_cookies():
    """wing_cookies.json에서 vendorId(sc_vid) 추출"""
    cookie_file = os.path.join(BASE_DIR, "wing_cookies.json")
    if not os.path.exists(cookie_file):
        return None
    try:
        with open(cookie_file, encoding="utf-8") as f:
            cookies = json.load(f)
        for c in cookies:
            if c.get("name") == "sc_vid":
                return c.get("value")
    except Exception:
        pass
    return None


def check_license(vendor_id):
    """
    Supabase에서 vendorId 상태 조회.
    반환: "approved" | "pending" | "unregistered" | "error"
    """
    try:
        r = _req.get(
            f"{SUPABASE_URL}/rest/v1/vendors",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            params={"vendor_id": f"eq.{vendor_id}", "select": "status"},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            if not data:
                return "unregistered"
            status = data[0].get("status", "pending")
            _save_cache(vendor_id, status)
            return status
    except Exception:
        # 오프라인 — 캐시 사용
        cached = _load_cache(vendor_id)
        if cached:
            return cached
    return "error"


def _save_cache(vendor_id, status):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"vendor_id": vendor_id, "status": status,
                       "cached_at": datetime.now().isoformat()}, f)
    except Exception:
        pass


def _load_cache(vendor_id):
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("vendor_id") == vendor_id:
            return data.get("status")
    except Exception:
        pass
    return None


def get_form_url(vendor_id):
    """구글폼 URL에 vendorId 자동 주입"""
    return f"{GOOGLE_FORM_URL}?usp=pp_url&{VENDOR_ENTRY}={vendor_id}"
