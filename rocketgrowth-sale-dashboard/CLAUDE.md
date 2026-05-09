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
