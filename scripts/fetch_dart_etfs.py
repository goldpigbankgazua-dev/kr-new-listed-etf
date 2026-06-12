#!/usr/bin/env python3
"""
DART (전자공시시스템) Open API 로 신규상장 ETF 공시 가져오기.

KIND 와 같은 한국공시 시스템의 두 채널. DART 는 무료 open API + JSON 응답으로
GitHub Actions 에서도 안정적으로 동작한다.

환경변수:
    DART_API_KEY    — opendart.fss.or.kr 에서 발급받은 인증키 (40자리 hex)

API 문서: https://opendart.fss.or.kr/guide/main.do
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

# update_etfs.py 와 동일한 운용사 매핑 (브랜드 → 정식명)
BRAND_TO_OP = {
    "KODEX": "삼성자산운용",
    "TIGER": "미래에셋자산운용",
    "ACE": "한국투자신탁운용",
    "KoAct": "삼성액티브자산운용",
    "RISE": "KB자산운용",
    "SOL": "신한자산운용",
    "HANARO": "NH아문디자산운용",
    "PLUS": "한화자산운용",
    "KIWOOM": "키움투자자산운용",
    "1Q": "하나자산운용",
    "WON": "우리자산운용",
    "FOCUS": "브이아이자산운용",
    "TIME": "타임폴리오자산운용",
    "DAISHIN343": "대신자산운용",
    "DAISHIN": "대신자산운용",
    "UNICORN": "현대자산운용",
    "IBK": "IBK자산운용",
    "BNK": "BNK자산운용",
}

# DART 공시검색 API
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# ETF 식별 키워드 (report_nm 또는 corp_name 에 포함되어야 함)
ETF_KEYWORDS = ["ETF", "상장지수투자신탁", "상장지수증권", "투자신탁"]
# 신규상장/발행 관련 키워드 — DART 는 report_nm 에 "신규상장" 직접 안 나오므로 확장
LISTING_KEYWORDS = [
    "신규상장", "상장신청", "상장예비심사", "증권신고",
    "투자설명서",  # ETF 발행 시 필수 공시
    "증권발행실적보고서",  # 상장 완료 후 공시
    "신탁계약",  # 신탁계약 설정/체결/변경
    "(신규)",  # 일부 공시명에 신규 표시
    "신규 설정",
    "발행조건확정",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_dart_etfs(days_back: int = 14) -> list:
    """DART 공시검색에서 최근 N일 신규상장 ETF 공시 추출.

    Returns: list of dict
        {date, name, ticker, op, fee, source, report}
    """
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        print("[fetch_dart] DART_API_KEY 환경변수 없음 — DART 스킵")
        return []

    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=days_back)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    # pblntf_ty 코드:
    #   A=정기공시 B=주요사항보고 C=발행공시 D=지분공시
    #   E=기타공시 F=외부감사 G=펀드공시 H=자산유동화 I=거래소공시
    # 신규상장 ETF 는 보통 거래소공시 (I) 또는 발행공시 (C) 또는 펀드공시 (G).
    # 안전하게 여러 type 다 시도.
    all_items = []
    for pblntf in ["I", "C", "G"]:
        page = 1
        while True:
            params = {
                "crtfc_key": api_key,
                "bgn_de": start_date,
                "end_de": end_date,
                "pblntf_ty": pblntf,
                "page_no": str(page),
                "page_count": "100",
            }
            query = urllib.parse.urlencode(params)
            full_url = f"{DART_LIST_URL}?{query}"

            try:
                req = urllib.request.Request(
                    full_url, headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8")
                data = json.loads(raw)
            except Exception as e:
                print(f"[fetch_dart] type={pblntf} page={page} 실패: {e}")
                break

            status = data.get("status")
            # 010=등록되지않은키, 011=사용할수없는키, 012=접근할수없는IP,
            # 013=조회된 데이타가 없습니다, 020=요청제한 초과
            if status == "013":
                # 데이터 없음 — 정상
                break
            if status != "000":
                print(f"[fetch_dart] type={pblntf} API 오류 status={status} msg={data.get('message')}")
                break

            items = data.get("list", [])
            all_items.extend(items)
            print(f"[fetch_dart] type={pblntf} page={page}: {len(items)}건")

            total_page = data.get("total_page", 1)
            if page >= total_page or not items:
                break
            page += 1

    print(f"[fetch_dart] 전체 수집: {len(all_items)}건")

    # ETF + 신규상장 필터링
    results = []
    seen_names = set()
    for item in all_items:
        report = item.get("report_nm", "").strip()
        corp = item.get("corp_name", "").strip()
        if not report or not corp:
            continue

        # 신규상장 관련 공시만
        if not any(k in report for k in LISTING_KEYWORDS):
            continue

        # ETF 식별: report_nm 또는 corp_name 에 ETF 키워드 또는 브랜드명 포함
        is_etf = (
            any(k in report for k in ETF_KEYWORDS)
            or any(k in corp for k in ETF_KEYWORDS)
            or any(brand in corp for brand in BRAND_TO_OP)
            or any(brand in report for brand in BRAND_TO_OP)
        )
        if not is_etf:
            continue

        # 종목명 추정 — report_nm 에서 ETF 명 추출 (예: "[신규상장] 신한 SOL 우주항공밸류체인...")
        # 또는 corp_name 그대로
        name = corp
        # report 안에 [신규상장(...)] 형태에서 종목명 추출 시도
        import re
        m = re.search(r"신규상장\(([^)]+)\)", report)
        if m:
            name = m.group(1).strip()
        m = re.search(r"신규상장\s*[:\(]?\s*([^,\)\[]+?(?:ETF|투자신탁|증권))", report)
        if m and "투자신탁" in m.group(1):
            name = m.group(1).strip()

        # 운용사 추정
        op = item.get("flr_nm", "").strip()  # 신고인 (제출인)
        if not op:
            for brand, oop in BRAND_TO_OP.items():
                if brand in name or brand in corp:
                    op = oop
                    break

        if name in seen_names:
            continue
        seen_names.add(name)

        ticker = item.get("stock_code", "").strip()

        # 상장일 추정 — report_nm 의 (상장일:YYYY.MM.DD) 또는 (상장일 YYYY-MM-DD)
        listing_date = ""
        m = re.search(r"상장일[:\s]*(\d{4})[.\-/](\d{2})[.\-/](\d{2})", report)
        if m:
            listing_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            # 공시일을 fallback 으로
            rcept = item.get("rcept_dt", "")  # YYYYMMDD
            if len(rcept) == 8:
                listing_date = f"{rcept[:4]}-{rcept[4:6]}-{rcept[6:]}"

        results.append({
            "date": listing_date,
            "name": name,
            "ticker": ticker,
            "op": op,
            "fee": "",  # DART 공시 PDF 내부에 있어서 추출 어려움
            "source": "dart",
            "report": report,
        })
        print(f"[fetch_dart] ✓ {listing_date} {ticker or '(no-ticker)'} {name} ({op})")

    return results


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    print(f"=== DART 신규상장 ETF 검색 (최근 {days}일) ===")
    rows = fetch_dart_etfs(days_back=days)
    print(f"\n=== 결과 {len(rows)}건 ===")
    for r in rows:
        print(json.dumps(r, ensure_ascii=False, indent=2))
