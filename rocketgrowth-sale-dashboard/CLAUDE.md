# 로켓그로스 마진 대시보드

쿠팡 Wing 정산 파일 자동 다운로드 + 마진 분석 대시보드.

## 실행
```
실행.bat  # Chrome(포트 9222) + Flask 서버 동시 시작
```
브라우저: http://localhost:5000

## 구조
- `wing_api.py` — Wing API 호출 전체 (인증/큐잉/폴링/다운로드)
- `app.py` — Flask 라우트
- `coupon_manager.py` — 쿠폰 갱신 자동화
- `wing_downloader.py` — Selenium 모달 조작 (현재 미사용, 보조)
- `wing_download_legacy.py` — 기존 Selenium 방식 백업

## Wing API 핵심 (F12로 확인한 실제 엔드포인트)
- 목록 조회: `POST /tenants/rfm/v2/settlements/download-list/api`
- URL 조회 payload: `{requestTime: str, locale: "ko"}` (requestId 아님!)
- 큐잉 시 settlementGroupKeys는 **주차별로 각각 1개씩** 호출해야 함

## 인증
- `wing_cookies.json` 저장/재사용
- 만료 시 포트 9222 Chrome에서 자동 추출
- Chrome은 `실행.bat`이 `--remote-debugging-port=9222`로 실행

## 주의
- `wing_cookies.json`, `ad_cookies.json` — 민감 정보, 커밋 금지 (.gitignore 처리됨)
- 쿠키 유효기간: 수일~수주 (만료 시 Chrome에서 자동 재취득)

## 라이선스 시스템 (수강생 vendorId 화이트리스트)

### 구조
- Supabase `vendors` 테이블 (vendor_id, name, status, created_at)
- status: `pending` | `approved`
- vendorId: Wing `sc_vid` 쿠키에서 추출 (Coupang 셀러 고유 ID)

### 신청 → 승인 흐름
1. 수강생이 앱 실행 → Wing 로그인 → "수강생 등록 신청" 버튼
2. 구글폼이 vendorId 자동 입력된 채로 열림 (entry.1452200275)
3. 구글폼 제출 → Apps Script 트리거 → Supabase INSERT (status='pending')
4. 운영자가 Supabase에서 승인:
   ```sql
   UPDATE vendors SET status = 'approved' WHERE vendor_id = 'A01234567';
   ```
5. 수강생 앱 새로고침 → 정상 진입

### Apps Script 설치 위치
- 백업: `apps_script/form_to_supabase.gs`
- 이벤트 소스: **"설문지에서"** (스프레드시트에서 X)
- 폼 편집 화면 점 3개(⋮) → Apps Script 에서 직접 열어야 "설문지에서" 옵션 나옴

### 일괄 승인 SQL
```sql
UPDATE vendors SET status = 'approved'
WHERE status = 'pending' AND created_at >= '2026-05-10';
```

### 구글폼 정보
- Form ID: `1FAIpQLSeSzCrNeH0ZzfEFHYD5KT1tnTle4-E8ET3j9ASXITv1C8Fbow`
- Vendor ID entry: `1452200275`
