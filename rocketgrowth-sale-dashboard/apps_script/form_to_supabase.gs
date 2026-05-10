/**
 * 구글폼 제출 → Supabase vendors 테이블 자동 INSERT
 *
 * 설치 방법:
 * 1. 구글폼 편집 화면 → 우상단 점 3개(⋮) → Apps Script
 * 2. 이 파일 내용 전체 복사 붙여넣기
 * 3. Ctrl+S 저장
 * 4. 좌측 시계 아이콘(트리거) → 트리거 추가
 *    - 함수: onFormSubmit
 *    - 이벤트 소스: 설문지에서
 *    - 이벤트 유형: 양식 제출 시
 * 5. Google 권한 승인 (팝업 차단 해제 필요)
 *
 * 주의:
 * - 폼 필드 제목에 "vendor"(대소문자 무관) 들어가야 매칭됨
 */

const SUPABASE_URL = "https://idtcsayclkxsfakouaww.supabase.co";
const SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlkdGNzYXljbGt4c2Zha291YXd3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgzMzMzOTYsImV4cCI6MjA5MzkwOTM5Nn0.QIS2vgBacmkBwJu0l_pALNP5ZyDBA-mme5KT1uffx4Q";

function onFormSubmit(e) {
  const responses = e.response.getItemResponses();

  for (const r of responses) {
    const item = r.getItem();
    console.log("ID:", item.getId(), "TITLE:", JSON.stringify(item.getTitle()), "VALUE:", JSON.stringify(r.getResponse()));
  }

  let vendorId = "", name = "";
  for (const r of responses) {
    const title = r.getItem().getTitle().toLowerCase();
    const value = r.getResponse();
    if (title.includes("vendor")) vendorId = String(value).trim();
    else if (title.includes("이름") || title.includes("name")) name = String(value).trim();
  }

  console.log("PARSED → vendorId:", vendorId, "name:", name);
  if (!vendorId) {
    console.log("vendorId 비어있어서 종료");
    return;
  }

  const res = UrlFetchApp.fetch(`${SUPABASE_URL}/rest/v1/vendors`, {
    method: "POST",
    headers: {
      "apikey": SUPABASE_KEY,
      "Authorization": `Bearer ${SUPABASE_KEY}`,
      "Content-Type": "application/json",
      "Prefer": "resolution=ignore-duplicates"
    },
    payload: JSON.stringify({ vendor_id: vendorId, name: name, status: "pending" }),
    muteHttpExceptions: true
  });
  console.log("Supabase status:", res.getResponseCode(), "body:", res.getContentText());
}
