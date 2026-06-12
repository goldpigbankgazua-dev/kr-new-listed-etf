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

# ETF 직접 명시 키워드 (반드시 report_nm 에 있어야 함)
ETF_STRICT_KEYWORDS = ["ETF", "상장지수투자신탁", "상장지수증권", "상장지수펀드"]
# 신규상장 관련 키워드 (강한 신호만 — "투자설명서/신탁계약" 같은 광범위 키워드 제외)
LISTING_KEYWORDS = [
    "신규상장",
    "상장신청",
    "상장예비심사",
    "(신규)",
    "최초상장",
    "신규 설정",
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

    # 통계: 어떤 corp_name 이 많은지 확인 (운용사 인지)
    from collections import Counter
    corp_counter = Counter()
    for item in all_items:
        c = item.get("corp_name", "").strip()
        if c:
            corp_counter[c] += 1
    print("[fetch_dart] 상위 corp_name 10개:")
    for name, cnt in corp_counter.most_common(10):
        print(f"  {cnt:4d}건  {name}")

    # ETF + 신규상장 필터링
    results = []
    seen_names = set()
    # 디버깅 통계
    stat_no_listing = 0
    stat_no_etf = 0
    stat_pass = 0
    # 운용사 매칭된 샘플 (디버깅용)
    op_samples = []

    # 자산운용사 패턴 (정확한 매칭만 — BNK캐피탈/BNK금융지주 같은 false positive 제외)
    def is_asset_mgmt(corp_name: str) -> bool:
        """corp_name 이 자산운용사인지 판정 (BNK캐피탈/BNK투자증권 같은 거 제외)."""
        return corp_name.endswith("자산운용") or corp_name.endswith("투신운용") or corp_name.endswith("자산운용(주)")

    for item in all_items:
        report = item.get("report_nm", "").strip()
        corp = item.get("corp_name", "").strip()
        if not report or not corp:
            continue

        # 디버깅: 자산운용사 공시 샘플 수집 (최대 30건)
        if is_asset_mgmt(corp) and len(op_samples) < 30:
            op_samples.append(f"  {corp[:20]:20s} | {report[:80]}")

        # 1단계: corp_name 이 자산운용사 (정확 매칭)
        if not is_asset_mgmt(corp):
            stat_no_etf += 1
            continue

        # 2단계: report_nm 에 ETF/상장지수 명시 (반드시)
        has_etf_kw = any(k in report for k in ETF_STRICT_KEYWORDS)
        if not has_etf_kw:
            stat_no_etf += 1
            continue

        # 3단계: 신규상장 관련 키워드 (강한 신호만)
        is_new_listing = any(k in report for k in LISTING_KEYWORDS)
        if not is_new_listing:
            stat_no_listing += 1
            continue

        stat_pass += 1

        # 종목명 추정 — report_nm 에서 ETF 명 추출
        import re
        name = None
        # 패턴 1: "신규상장(종목명)"
        m = re.search(r"신규상장\(([^)]+)\)", report)
        if m:
            name = m.group(1).strip()
        # 패턴 2: "[신규상장] 종목명" 또는 "신규상장 종목명"
        if not name:
            m = re.search(r"신규상장\]?\s*[:：]?\s*([A-Za-z가-힣0-9]+\s*[A-Za-z가-힣0-9 ]+?(?:ETF|상장지수투자신탁|상장지수증권|상장지수펀드))", report)
            if m:
                name = m.group(1).strip()
        # 패턴 3: report 안의 ETF 명 직접 추출 — "삼성KODEX미국S&P500ETF" 같은 형태
        if not name:
            m = re.search(r"([A-Za-z가-힣][\w가-힣 ]*?(?:ETF|상장지수투자신탁|상장지수증권|상장지수펀드))", report)
            if m:
                name = m.group(1).strip()

        # 종목명 추출 실패 또는 운용사명 그대로면 skip (false positive 차단)
        if not name or is_asset_mgmt(name) or name == corp:
            stat_pass -= 1
            stat_no_etf += 1
            continue

        # 운용사 추정 — corp_name 그대로 사용 (이미 자산운용사임)
        op = corp

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

    # 디버깅 통계 출력
    print(f"[fetch_dart] 필터링 결과: 신규상장키워드없음={stat_no_listing}, ETF아님={stat_no_etf}, 통과={stat_pass}")
    if op_samples:
        print(f"[fetch_dart] 운용사 매칭된 공시 샘플 (최대 30건):")
        for s in op_samples:
            print(s)

    return results


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    print(f"=== DART 신규상장 ETF 검색 (최근 {days}일) ===")
    rows = fetch_dart_etfs(days_back=days)
    print(f"\n=== 결과 {len(rows)}건 ===")
    for r in rows:
        print(json.dumps(r, ensure_ascii=False, indent=2))
