#!/usr/bin/env python3
"""
KIND(한국거래소 기업공시채널)에서 신규상장 ETF 공시를 가져온다.

unjena.com 블로그보다 빠르고 빠짐없는 1차 소스. KIND는 상장일 며칠 전에
"ETF 신규상장 신청서" / "신규상장(ETF)" 공시를 올린다.

KIND의 ETF 공시 페이지는 AJAX로 로드되므로 다음 두 endpoint를 사용:

1) https://kind.krx.co.kr/disclosure/disclosurebystocktype.do
   - method=searchDisclosureByStockTypeSub (AJAX, table partial 반환)
   - searchCodeType=13 (ETF)
   - searchCorpName / fromDate / toDate / pageIndex / currentPageSize

2) 폴백: https://data.krx.co.kr (KRX Data Marketplace)
   - bld=dbms/MDC/STAT/standard/MDCSTAT04601 (ETF 전종목 — 상장일 포함)

사용 예:
    python fetch_kind_etfs.py
    -> 최근 30일 신규상장 ETF JSON 출력

update_etfs.py 에서 import:
    from fetch_kind_etfs import fetch_kind_etfs
    kind_rows = fetch_kind_etfs(days_back=30)
"""

import datetime
import html as html_lib
import json
import re
import sys
import urllib.parse
import urllib.request

# ---- 운용사 매핑 (update_etfs.py와 동일) ----
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
    "ITF": "IBK자산운용",
    "BNK": "BNK자산운용",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

KIND_BASE = "https://kind.krx.co.kr"
KIND_ETF_AJAX = f"{KIND_BASE}/disclosure/disclosurebystocktype.do"
KIND_REFERER = (
    f"{KIND_BASE}/disclosure/disclosurebystocktype.do"
    "?method=searchDisclosureByStockTypeEtf"
)
KRX_DATA_JSON = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

# 신규상장 관련 보고서명에 들어가는 키워드
NEW_LIST_KEYWORDS = ("신규상장", "신규 상장", "상장신청", "신규(ETF)")


def detect_op(name: str) -> str:
    head = name.split()[0] if name else ""
    return BRAND_TO_OP.get(head, "기타운용사")


def http_post(url: str, data: dict, referer: str = "") -> str:
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "text/html, */*; q=0.01",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("euc-kr", errors="replace")


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("euc-kr", errors="replace")


def clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# 소스 1: KIND ETF 공시 (AJAX)
# ---------------------------------------------------------------------------
def fetch_kind_disclosures(days_back: int = 30) -> list:
    """KIND ETF 공시 페이지에서 최근 N일 공시 목록 가져오기.

    Returns: list of dict
        {acpt_no, date(공시일), name, report_name, submitter}
    """
    today = datetime.date.today()
    from_date = (today - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    # KIND ETF 공시 AJAX 파라미터 (브라우저 DevTools에서 확인한 form data 기반)
    params = {
        "method": "searchDisclosureByStockTypeSub",
        "currentPageSize": "100",
        "pageIndex": "1",
        "orderMode": "1",
        "orderStat": "D",
        "forward": "disclosurebystocktype_sub",
        "searchCodeType": "13",   # 13 = ETF
        "isurCd": "",
        "stockTypeKind": "etf",
        "searchCorpName": "",
        "fromDate": from_date,
        "toDate": to_date,
        "reportNm": "",
        "reportCd": "",
        "kindReportType": "0",
    }

    try:
        html = http_post(KIND_ETF_AJAX, params, referer=KIND_REFERER)
        print(f"[fetch_kind] KIND 응답 길이: {len(html)} 글자, 첫 200자: {html[:200]!r}")
    except Exception as e:
        print(f"[fetch_kind] KIND HTTP 실패: {e}")
        return []

    # 응답은 <table> partial. 각 <tr> 안에:
    #   td[0]: 공시일 (yyyy-mm-dd 또는 hh:mm)
    #   td[1]: 회사명/종목명 (a 태그 안)
    #   td[2]: 보고서명 (a 태그 안, acptno javascript 링크 포함)
    #   td[3]: 제출인
    results = []
    tr_pat = re.compile(r"<tr[^>]*>(.*?)</tr>", flags=re.S | re.I)
    td_pat = re.compile(r"<td[^>]*>(.*?)</td>", flags=re.S | re.I)
    acpt_pat = re.compile(r"acptno=(\d+)|openDisclsViewer\('(\d+)'")

    for tr_match in tr_pat.finditer(html):
        tds = td_pat.findall(tr_match.group(1))
        if len(tds) < 4:
            continue
        date_raw = clean_text(tds[0])
        name = clean_text(tds[1])
        report = clean_text(tds[2])
        submitter = clean_text(tds[3])
        if not name or not report:
            continue

        # 신규상장 관련 공시만 필터
        if not any(k in report for k in NEW_LIST_KEYWORDS):
            continue

        acpt = ""
        am = acpt_pat.search(tds[2])
        if am:
            acpt = am.group(1) or am.group(2) or ""

        # 날짜 정규화 (yyyy-mm-dd 형태 추출)
        dm = re.search(r"(\d{4})[-./](\d{2})[-./](\d{2})", date_raw)
        if dm:
            date = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
        else:
            date = today.strftime("%Y-%m-%d")

        results.append({
            "acpt_no": acpt,
            "disclosure_date": date,
            "name": name,
            "report_name": report,
            "submitter": submitter,
        })

    return results


# ---------------------------------------------------------------------------
# 소스 2: KRX Data Marketplace (전체 ETF 상장일) — KIND가 막혔을 때 폴백
# ---------------------------------------------------------------------------
def fetch_krx_etf_master() -> list:
    """KRX 정보데이터시스템에서 전체 ETF 마스터(상장일 포함)를 가져온다.

    Returns: list of dict
        {ticker, name, op(운용사), listing_date(상장일 yyyy-mm-dd), fee}
    """
    today = datetime.date.today().strftime("%Y%m%d")
    params = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT04601",
        "locale": "ko_KR",
        "share": "1",
        "csvxls_isNo": "false",
        "trdDd": today,
    }
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        KRX_DATA_JSON,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC020103010901",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    rows = data.get("output", []) or data.get("OutBlock_1", []) or []
    result = []
    for r in rows:
        ticker = r.get("ISU_SRT_CD") or r.get("ticker") or ""
        name = r.get("ISU_ABBRV") or r.get("ISU_NM") or ""
        listed = r.get("LIST_DD") or r.get("LISTNG_DT") or ""
        op = r.get("COM_ABBRV") or r.get("COM_NM") or ""
        # LIST_DD는 보통 "yyyy/mm/dd" 또는 "yyyymmdd"
        if re.match(r"^\d{8}$", listed):
            listed_iso = f"{listed[0:4]}-{listed[4:6]}-{listed[6:8]}"
        elif re.match(r"^\d{4}[/.-]\d{2}[/.-]\d{2}$", listed):
            listed_iso = re.sub(r"[/.]", "-", listed)
        else:
            listed_iso = ""
        result.append({
            "ticker": ticker,
            "name": name,
            "op": op,
            "listing_date": listed_iso,
            "fee": "",
        })
    return result


# ---------------------------------------------------------------------------
# 최종 함수: 두 소스 통합
# ---------------------------------------------------------------------------
def fetch_kind_etfs(days_back: int = 30) -> list:
    """최근 N일 신규상장 ETF 목록.

    KIND ETF 공시(신규상장 키워드 필터) → 폴백으로 KRX 마스터에서
    days_back 이내 상장일 ETF.

    Returns: list of dict
        {date, name, ticker, op, fee, source}
    """
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days_back)
    horizon = today + datetime.timedelta(days=days_back)  # 미래 상장 예정도 포함
    seen_names = set()
    out = []

    # 1) KIND 시도
    try:
        kind_rows = fetch_kind_disclosures(days_back=days_back)
    except Exception as e:
        print(f"[fetch_kind_etfs] KIND 실패: {e}", file=sys.stderr)
        kind_rows = []

    # KIND 보고서명에서 "상장일" 추출 시도 (예: "신규상장(상장일:2026-06-16)")
    date_in_report = re.compile(r"상장일[:\s]*(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
    for r in kind_rows:
        name = r["name"]
        if not name or name in seen_names:
            continue
        listing_date = r["disclosure_date"]
        m = date_in_report.search(r["report_name"])
        if m:
            listing_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        op = r["submitter"] or detect_op(name)
        # 운용사 후미 "자산운용" 정규화
        if op and not op.endswith("자산운용") and op != "기타운용사":
            # submitter가 "삼성자산운용(주)" 같은 형태일 수 있음
            op = re.sub(r"\([주]\)|주식회사|\s+", "", op)
            if not op.endswith("자산운용") and not op.endswith("운용"):
                op = detect_op(name)
        seen_names.add(name)
        out.append({
            "date": listing_date,
            "name": name,
            "ticker": "",
            "op": op,
            "fee": "",
            "source": "kind",
        })

    # 2) KRX 마스터 폴백 — 상장된 ETF 중 days_back 이내
    if not out:
        try:
            master = fetch_krx_etf_master()
        except Exception as e:
            print(f"[fetch_kind_etfs] KRX 마스터 실패: {e}", file=sys.stderr)
            master = []
        for r in master:
            ld = r["listing_date"]
            if not ld:
                continue
            try:
                d = datetime.date.fromisoformat(ld)
            except ValueError:
                continue
            if not (cutoff <= d <= horizon):
                continue
            name = r["name"]
            if name in seen_names:
                continue
            seen_names.add(name)
            op = r["op"] or detect_op(name)
            out.append({
                "date": ld,
                "name": name,
                "ticker": r["ticker"],
                "op": op,
                "fee": "",
                "source": "krx",
            })

    # 상장일 desc
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    rows = fetch_kind_etfs(days_back=days)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\n총 {len(rows)}건", file=sys.stderr)
