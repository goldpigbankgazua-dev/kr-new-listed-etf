#!/usr/bin/env python3
"""KIND 신규상장 ETF 스크래퍼 — 맥 launchd 에서 매일 1회 실행.

GitHub Actions IP 가 KIND 차단당해서 사용자 맥에서 fetch.
결과: modules/etf/data/kind_listings.json 에 저장 → auto-sync 가 GitHub push.
워크플로우 (KST 8시) 가 그 JSON 을 읽어서 ETFS 배열 갱신.

KIND 공시제목 공통 패턴 (이렌이 확인):
    신규상장(<운용사> <종목 풀네임>증권상장지수투자신탁[주식], 상장일 YYYY.MM.DD)
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

URL = "https://kind.krx.co.kr/disclosure/disclosurebystocktype.do?method=searchDisclosureByStockTypeEtf"

# 스크립트 경로 기준으로 출력 경로 결정 (어디서 실행해도 동작)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "kind_listings.json"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://kind.krx.co.kr/",
}

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


def extract_brand_name(full: str) -> tuple:
    """공시 풀네임에서 (정리된 종목명, 운용사) 추출.

    예: "신한 SOL 우주항공밸류체인증권상장지수투자신탁[주식]"
        → ("SOL 우주항공밸류체인", "신한자산운용")
    """
    # 브랜드 패턴 매칭 (긴 거 먼저 — DAISHIN343 이 DAISHIN 보다 우선)
    brands = sorted(BRAND_TO_OP.keys(), key=len, reverse=True)
    name = full
    op = ""
    for brand in brands:
        # 브랜드가 단어 단위로 등장하는지 확인
        m = re.search(rf"(?:^|[\s\(])({re.escape(brand)}\s*[\w가-힣&\.\-]+?)(?:증권상장지수투자신탁|증권상장지수증권|상장지수투자신탁|상장지수증권|ETF)", full)
        if m:
            name = m.group(1).strip()
            op = BRAND_TO_OP[brand]
            break
    # 끝부분 정리 — "[주식]", "(채권)" 등 제거
    name = re.sub(r"\[.*?\]\s*$", "", name).strip()
    name = re.sub(r"\(.*?\)\s*$", "", name).strip()
    return name, op


def main():
    # KIND fetch
    try:
        req = urllib.request.Request(URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[KIND] HTTP 실패: {e}", file=sys.stderr)
        sys.exit(1)

    if len(html) < 1000:
        print(f"[KIND] 응답 너무 짧음 ({len(html)} bytes) — IP 차단 가능성", file=sys.stderr)
        sys.exit(1)

    # 패턴 매칭: "신규상장(...상장일 YYYY.MM.DD)"
    # KIND 표 안의 공시제목 셀에 그대로 들어있음
    results = []
    seen_keys = set()

    # 패턴 1: 표준 형식 "신규상장(<풀네임>, 상장일 YYYY.MM.DD)"
    pattern = re.compile(r"신규상장\(\s*([^,]+?)\s*,\s*상장일\s+(\d{4}\.\d{2}\.\d{2})\s*\)")
    for m in pattern.finditer(html):
        full = m.group(1).strip()
        date = m.group(2).replace(".", "-")

        # HTML 엔티티 디코딩 (필요시)
        full = full.replace("&amp;", "&").replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")

        key = f"{date}|{full}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

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

    # 결과 저장
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_url": URL,
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
