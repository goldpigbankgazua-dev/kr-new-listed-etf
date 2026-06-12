#!/usr/bin/env python3
"""KIND 신규상장 ETF 스크래퍼 — 맥 launchd 에서 매일 실행.

KIND 의 진짜 AJAX endpoint (Chrome MCP 로 캡쳐):
    POST https://kind.krx.co.kr/disclosure/disclosurebystocktype.do
    form: method=searchDisclosureByStockTypeEtfSub
          forward=disclosurebystocktype_etf_sub
          reportNm=신규상장
          fromDate=YYYY-MM-DD, toDate=YYYY-MM-DD
          currentPageSize=100, pageIndex=1, orderMode=1, orderStat=D
          (etfIsuSrtCd, reportCd, reportTmp, etfIsuSrtNm 은 빈 값)

응답 HTML 에 패턴:
    신규상장(<운용사브랜드> <종목명>증권상장지수투자신탁[주식|채권|...], 상장일 YYYY.MM.DD)
"""
import http.cookiejar
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

URL_INIT = "https://kind.krx.co.kr/disclosure/disclosurebystocktype.do?method=searchDisclosureByStockTypeEtf"
URL_POST = "https://kind.krx.co.kr/disclosure/disclosurebystocktype.do"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "kind_listings.json"))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# macOS Apple-system Python 의 SSL CERTIFICATE_VERIFY_FAILED 회피
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

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
    "DB": "DB자산운용",
    "MIDAS": "마이다스에셋자산운용",
    "마이다스": "마이다스에셋자산운용",
}

# 운용사명 prefix → op (브랜드보다 앞에 등장하는 한글 운용사명)
KOR_OP_PREFIX = {
    "신한": "신한자산운용",
    "삼성": "삼성자산운용",
    "미래에셋": "미래에셋자산운용",
    "한국투자": "한국투자신탁운용",
    "한화": "한화자산운용",
    "키움": "키움투자자산운용",
    "하나": "하나자산운용",
    "우리": "우리자산운용",
    "신영": "신영자산운용",
    "대신": "대신자산운용",
    "NH-Amundi": "NH아문디자산운용",
    "NH": "NH아문디자산운용",
    "KB": "KB자산운용",
    "IBK": "IBK자산운용",
    "BNK": "BNK자산운용",
    "DB": "DB자산운용",
    "타임폴리오": "타임폴리오자산운용",
    "브이아이": "브이아이자산운용",
    "유리": "유리자산운용",
    "유경피에스지": "유경피에스지자산운용",
    "현대": "현대자산운용",
    "코레이트": "코레이트자산운용",
    "교보악사": "교보악사자산운용",
    "디비": "DB자산운용",
    "피델리티": "피델리티자산운용",
}


def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=SSL_CTX),
    )


def fetch_kind(days_back: int = 30) -> str:
    """KIND ETF 신규상장 공시 검색 — 응답 HTML 문자열."""
    opener = make_opener()

    # Step 1: 초기 GET (cookie/session)
    req1 = urllib.request.Request(URL_INIT, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    opener.open(req1, timeout=30).read()

    # Step 2: POST 검색
    today = datetime.now().date()
    fromDate = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    toDate = today.strftime("%Y-%m-%d")

    form = {
        "method": "searchDisclosureByStockTypeEtfSub",
        "forward": "disclosurebystocktype_etf_sub",
        "currentPageSize": "100",
        "pageIndex": "1",
        "orderMode": "1",
        "orderStat": "D",
        "etfIsuSrtCd": "",
        "reportCd": "",
        "reportTmp": "",
        "etfIsuSrtNm": "",
        "reportNm": "신규상장",
        "fromDate": fromDate,
        "toDate": toDate,
    }
    body = urllib.parse.urlencode(form, encoding="utf-8").encode("utf-8")

    req2 = urllib.request.Request(URL_POST, data=body, headers={
        "User-Agent": UA,
        "Accept": "text/html,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": URL_INIT,
        "Origin": "https://kind.krx.co.kr",
    })
    resp = opener.open(req2, timeout=30)
    data = resp.read()
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def extract_brand_name(full: str) -> tuple:
    """공시 풀네임에서 (정리된 종목명, 운용사) 추출.

    예: "신한 SOL 우주항공밸류체인증권상장지수투자신탁[주식]"
        → ("SOL 우주항공밸류체인", "신한자산운용")
    """
    brands = sorted(BRAND_TO_OP.keys(), key=len, reverse=True)
    name = full
    op = ""
    for brand in brands:
        m = re.search(
            rf"(?:^|[\s\(])({re.escape(brand)}\s*[\w가-힣&\.\-\s]+?)"
            r"(?:증권상장지수투자신탁|증권상장지수증권|상장지수투자신탁|상장지수증권|ETF)",
            full,
        )
        if m:
            name = m.group(1).strip()
            op = BRAND_TO_OP[brand]
            break
    # 운용사 매핑 fallback — 풀네임의 한글 prefix 로 추정
    if not op:
        for prefix, op_name in sorted(KOR_OP_PREFIX.items(), key=lambda x: -len(x[0])):
            if full.startswith(prefix):
                op = op_name
                break
    name = re.sub(r"\[.*?\]\s*$", "", name).strip()
    name = re.sub(r"\(.*?\)\s*$", "", name).strip()
    return name, op


def parse_etfs(html: str) -> list:
    """HTML 에서 신규상장 ETF 공시 추출."""
    results = []
    seen = set()
    pattern = re.compile(
        r"신규상장\(\s*([^,]+?)\s*,\s*상장일\s+(\d{4}\.\d{2}\.\d{2})\s*\)"
    )
    for m in pattern.finditer(html):
        full = m.group(1).strip()
        full = full.replace("&amp;", "&").replace("&nbsp;", " ")
        date = m.group(2).replace(".", "-")
        key = f"{date}|{full}"
        if key in seen:
            continue
        seen.add(key)
        name, op = extract_brand_name(full)
        results.append({
            "date": date,
            "name": name,
            "ticker": "",
            "op": op,
            "fee": "",
            "source": "kind",
            "raw_title": full,
        })
    return results


def main():
    try:
        html = fetch_kind(days_back=30)
    except Exception as e:
        print(f"[KIND] HTTP 실패: {e}", file=sys.stderr)
        sys.exit(1)

    if len(html) < 200:
        print(f"[KIND] 응답 너무 짧음 ({len(html)} bytes)", file=sys.stderr)
        sys.exit(1)

    results = parse_etfs(html)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_url": URL_POST,
        "count": len(results),
        "etfs": results,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[KIND] {len(results)}건 저장 → {OUT}")
    for r in results:
        print(f"  {r['date']}  {r['name']:30s}  ({r['op']})")


if __name__ == "__main__":
    main()
