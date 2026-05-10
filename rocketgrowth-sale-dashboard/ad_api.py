"""
Coupang 광고센터 (advertising.coupang.com) 보고서 자동 다운로드
- 캠페인 목록 자동 조회
- 보고서 큐잉 → 폴링 → 엑셀 다운로드
"""
import re
import time
from pathlib import Path

import requests

BASE_API = "https://advertising.coupang.com/marketing-reporting"
GRAPHQL_URL = f"{BASE_API}/v2/graphql"
EXCEL_URL = f"{BASE_API}/v2/api/excel-report"

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://advertising.coupang.com",
    "referer": "https://advertising.coupang.com/marketing-reporting/billboard/reports/pa",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}


# ─────────────────────────────────────────────────────────────
# 1. 캠페인 목록 조회
# ─────────────────────────────────────────────────────────────
def get_campaign_ids(cookies, start_date: int, end_date: int, log_fn=print):
    """현재 활성 캠페인 ID 전체 반환"""
    query = """query GetCampaignListInBillboard($startDate: Int!, $endDate: Int!, $reportType: ReportType!) {
  getCampaignList(startDate: $startDate, endDate: $endDate, reportType: $reportType) {
    id
    name
    __typename
  }
}"""
    payload = [{
        "operationName": "GetCampaignListInBillboard",
        "query": query,
        "variables": {"startDate": start_date, "endDate": end_date, "reportType": "pa"}
    }]
    r = requests.post(GRAPHQL_URL, headers=HEADERS, cookies=cookies, json=payload, timeout=30)
    r.raise_for_status()
    campaigns = r.json()[0]["data"]["getCampaignList"]
    ids = [c["id"] for c in campaigns]
    log_fn(f"캠페인 {len(ids)}개 조회 완료")
    return ids


# ─────────────────────────────────────────────────────────────
# 2. 보고서 큐잉 (보고서 만들기)
# ─────────────────────────────────────────────────────────────
def queue_ad_report(cookies, start_date: int, end_date: int, campaign_ids: list, log_fn=print):
    """광고 보고서 생성 요청 → report_id 반환"""
    query = """mutation ($startDate: Int!, $endDate: Int!, $campaignIds: [ID], $reportType: ReportType!, $dateGroup: DateGroup!, $granularity: Granularity, $excludeIfNoClickCount: Boolean) {
  requestReport(data: {startDate: $startDate, endDate: $endDate, campaignIds: $campaignIds, reportType: $reportType, dateGroup: $dateGroup, granularity: $granularity, excludeIfNoClickCount: $excludeIfNoClickCount}) {
    id
    status
    __typename
  }
}"""
    payload = [{
        "query": query,
        "variables": {
            "reportType": "pa",
            "startDate": start_date,
            "endDate": end_date,
            "dateGroup": "daily",
            "granularity": "keyword",
            "campaignIds": campaign_ids,
            "excludeIfNoClickCount": True,
        }
    }]
    r = requests.post(GRAPHQL_URL, headers=HEADERS, cookies=cookies, json=payload, timeout=30)
    r.raise_for_status()
    report_id = r.json()[0]["data"]["requestReport"]["id"]
    log_fn(f"보고서 생성 요청 완료: id={report_id}")
    return report_id


# ─────────────────────────────────────────────────────────────
# 3. 폴링 (완료 대기)
# ─────────────────────────────────────────────────────────────
def poll_ad_report(cookies, report_id: str, timeout: int = 120, log_fn=print):
    """status가 'completed'될 때까지 폴링"""
    query = """query ($reportType: ReportType!, $page: Int!, $pageSize: Int!, $duration: Int, $onlyScheduledReport: Boolean) {
  reportList(reportType: $reportType, page: $page, pageSize: $pageSize, duration: $duration, onlyScheduledReport: $onlyScheduledReport) {
    page
    pageSize
    total
    reports {
      id
      status
      __typename
    }
    __typename
  }
}"""
    payload = [{
        "query": query,
        "variables": {"reportType": "pa", "page": 1, "pageSize": 10, "duration": 90, "onlyScheduledReport": False}
    }]

    start = time.time()
    while time.time() - start < timeout:
        r = requests.post(GRAPHQL_URL, headers=HEADERS, cookies=cookies, json=payload, timeout=30)
        r.raise_for_status()
        reports = r.json()[0]["data"]["reportList"]["reports"]
        for rep in reports:
            if rep["id"] == report_id:
                status = rep["status"]
                elapsed = int(time.time() - start)
                log_fn(f"폴링 [{elapsed}s] id={report_id} status={status}")
                if status == "completed":
                    return True
                if status in ("failed", "error"):
                    log_fn(f"보고서 생성 실패: {status}")
                    return False
                break
        time.sleep(2)
    log_fn(f"타임아웃 ({timeout}s)")
    return False


# ─────────────────────────────────────────────────────────────
# 4. 엑셀 다운로드
# ─────────────────────────────────────────────────────────────
def download_ad_excel(cookies, report_id: str, dest_dir: str, log_fn=print) -> str:
    """엑셀 파일 다운로드, 저장된 파일 경로 반환"""
    r = requests.get(f"{EXCEL_URL}?id={report_id}", headers=HEADERS, cookies=cookies, timeout=120)
    r.raise_for_status()

    cd = r.headers.get("content-disposition", "")
    m = re.search(r'filename=([^;]+)', cd)
    filename = m.group(1).strip().strip('"') if m else f"ad_report_{report_id}.xlsx"

    dest_path = Path(dest_dir) / filename
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(r.content)
    log_fn(f"다운로드 완료: {filename} ({len(r.content):,} bytes)")
    return str(dest_path)


# ─────────────────────────────────────────────────────────────
# 통합 실행 함수
# ─────────────────────────────────────────────────────────────
STATUS = {'state': 'idle', 'message': '', 'logs': [], 'file': None}


def _log(msg):
    print(msg)
    STATUS['logs'].append(msg)
    STATUS['message'] = msg


def run_ad_download(start_date: int, end_date: int):
    """Flask 스레드에서 호출되는 진입점"""
    STATUS.update({'state': 'running', 'message': '시작 중...', 'logs': [], 'file': None})
    try:
        from wing_api import load_cookie_file
        cookie_list = load_cookie_file()
        cookies = {c['name']: c['value'] for c in cookie_list} if cookie_list else None
        if not cookies:
            _log("광고 쿠키를 찾을 수 없습니다. 광고센터에 로그인해 주세요.")
            STATUS['state'] = 'error'
            return

        dest_dir = str(Path.home() / 'Downloads' / 'ad_reports')
        campaign_ids = get_campaign_ids(cookies, start_date, end_date, _log)
        if not campaign_ids:
            _log("활성 캠페인이 없습니다")
            STATUS['state'] = 'done'
            return

        report_id = queue_ad_report(cookies, start_date, end_date, campaign_ids, _log)
        if not poll_ad_report(cookies, report_id, log_fn=_log):
            _log("보고서 생성 실패 또는 타임아웃")
            STATUS['state'] = 'error'
            return

        filepath = download_ad_excel(cookies, report_id, dest_dir, _log)
        STATUS.update({'state': 'done', 'file': filepath})
    except Exception as e:
        _log(f"오류: {e}")
        STATUS['state'] = 'error'
