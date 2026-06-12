#!/usr/bin/env python3
"""자산운용사 (Asset Management Company) 14개 사이트 신규상장 ETF 스크래퍼.

KIND 가 GitHub Actions IP 를 차단하고 DART 는 발행공시 위주라 신규상장 ETF 검출
부적합. 각 운용사 공식 사이트의 공지/뉴스 페이지에서 직접 추출.

전략:
- 단계적 구현 — KODEX/TIGER 1차, 나머지 점진적 추가
- 디버그 모드 (AMC_DEBUG=1) 로 raw HTML 일부 print 해서 구조 파악
- 정규식 기반 — JS 렌더링 안 한다고 가정 (안 되면 AJAX endpoint 직접)

운용사 14개 우선순위:
1. 삼성자산운용 (KODEX) — 시장점유율 약 40%
2. 미래에셋자산운용 (TIGER) — 약 35%
3. 한국투자신탁운용 (ACE)
4. KB자산운용 (RISE)
5. 신한자산운용 (SOL)
6. NH아문디 (HANARO)
7. 한화자산운용 (PLUS)
8. 키움투자자산운용 (KIWOOM)
9-14. 추후 추가
"""

import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEBUG = os.environ.get("AMC_DEBUG", "0") == "1"


def http_get(url: str, timeout: int = 20, referer: str = "") -> str:
    """일반 GET — 빈 응답 또는 에러 시 빈 문자열 반환."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if referer:
        headers["Referer"] = referer
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            # 인코딩: utf-8 기본, 실패 시 euc-kr
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="ignore")
    except Exception as e:
        if DEBUG:
            print(f"[http_get] {url[:50]} 실패: {e}")
        return ""


def http_post(url: str, params: dict, timeout: int = 20, referer: str = "", is_json: bool = False) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html,*/*",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    if is_json:
        headers["Content-Type"] = "application/json;charset=UTF-8"
        body = json.dumps(params).encode("utf-8")
    else:
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        body = urllib.parse.urlencode(params).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="ignore")
    except Exception as e:
        if DEBUG:
            print(f"[http_post] {url[:50]} 실패: {e}")
        return ""


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_etf_name(text: str) -> str:
    """공지 제목/뉴스 텍스트에서 ETF 명 추출.

    예: "KODEX 미국S&P500ETF 신규상장 안내" → "KODEX 미국S&P500"
    """
    # 브랜드 키워드 시작 + ETF 또는 상장지수 끝
    pattern = r"((?:KODEX|TIGER|ACE|KoAct|RISE|SOL|HANARO|PLUS|KIWOOM|1Q|WON|FOCUS|TIME|DAISHIN|UNICORN|IBK|BNK)\s*[가-힣A-Za-z0-9&\.\s\-]+?)\s*(?:ETF|상장지수투자신탁|상장지수증권|상장지수펀드)"
    m = re.search(pattern, text)
    if m:
        return (m.group(1) + " ETF").strip()
    return ""


# ============================================================
# 1. KODEX (삼성자산운용)
# ============================================================

def fetch_kodex() -> list:
    """삼성자산운용 공지사항에서 신규상장 KODEX ETF 추출."""
    url = "https://www.samsungfund.com/etf/lounge/notice.do"
    html = http_get(url)
    if DEBUG and html:
        print(f"[KODEX] HTML 길이 {len(html)} 첫 1000자:")
        print(html[:1000])
        print("...")
    if not html:
        print("[KODEX] 빈 응답")
        return []

    rows = []
    # 패턴 1: 공지 목록의 <a> 태그 — onclick="view(...)" 또는 href
    # KODEX 공지는 보통 onclick 으로 상세 페이지로 이동
    # title 텍스트에서 "신규상장" 키워드 + ETF 명 추출

    # 일반 패턴: <a ...>제목</a> 옆에 날짜
    for m in re.finditer(r'<a[^>]*>([^<]*신규상장[^<]*)</a>', html):
        title = _strip_tags(m.group(1))
        if not title:
            continue
        name = _extract_etf_name(title)
        if name:
            rows.append({"date": "", "name": name, "ticker": "", "op": "삼성자산운용", "fee": "", "source": "kodex", "raw": title[:100]})
            print(f"[KODEX] ✓ {name} ← {title[:80]}")

    # 추가 패턴 — newsroom 의 신규상장 글
    for m in re.finditer(r'\[신규상장[^\]]*\]\s*([^<\n]{5,100})', html):
        title = _strip_tags(m.group(1))
        name = _extract_etf_name(title) or title.strip()
        if name and "KODEX" in name:
            rows.append({"date": "", "name": name, "ticker": "", "op": "삼성자산운용", "fee": "", "source": "kodex", "raw": title[:100]})
            print(f"[KODEX] ✓ {name}")

    print(f"[KODEX] {len(rows)}건")
    return rows


# ============================================================
# 2. TIGER (미래에셋자산운용)
# ============================================================

def fetch_tiger() -> list:
    """미래에셋 TIGER ETF 뉴스/공지에서 신규상장 추출."""
    # 모바일 newsList 가 더 간단할 수 있음
    candidates = [
        "https://www.tigeretf.com/ko/insight/etf-insight/list.do",
        "https://www.tigeretf.com/ko/notification/list.do",
        "https://m.tigeretf.com/new/content/newsList.do",
    ]

    rows = []
    for url in candidates:
        html = http_get(url)
        if DEBUG and html:
            print(f"[TIGER] {url} HTML 길이 {len(html)} 첫 500자:")
            print(html[:500])
        if not html:
            continue

        # 신규상장 키워드 들어간 텍스트 추출
        for m in re.finditer(r'>([^<]*신규상장[^<]*TIGER[^<]*)<', html):
            title = _strip_tags(m.group(1))
            name = _extract_etf_name(title)
            if name and name not in [r["name"] for r in rows]:
                rows.append({"date": "", "name": name, "ticker": "", "op": "미래에셋자산운용", "fee": "", "source": "tiger", "raw": title[:100]})
                print(f"[TIGER] ✓ {name}")

        for m in re.finditer(r'>([^<]*TIGER[^<]*신규상장[^<]*)<', html):
            title = _strip_tags(m.group(1))
            name = _extract_etf_name(title)
            if name and name not in [r["name"] for r in rows]:
                rows.append({"date": "", "name": name, "ticker": "", "op": "미래에셋자산운용", "fee": "", "source": "tiger", "raw": title[:100]})
                print(f"[TIGER] ✓ {name}")

        if rows:
            break  # 첫 동작하는 URL 에서 멈춤

    print(f"[TIGER] {len(rows)}건")
    return rows


# ============================================================
# 통합
# ============================================================

def fetch_all_amc_etfs() -> list:
    """모든 운용사 사이트에서 신규상장 ETF 수집."""
    results = []
    for fn in [fetch_kodex, fetch_tiger]:
        try:
            results.extend(fn())
        except Exception as e:
            print(f"[AMC] {fn.__name__} 예외: {e}")
    print(f"[AMC] 전체: {len(results)}건")
    return results


if __name__ == "__main__":
    os.environ.setdefault("AMC_DEBUG", "1")
    print(f"=== AMC 신규상장 ETF 스크래퍼 (현재 DEBUG={os.environ.get('AMC_DEBUG')}) ===")
    rows = fetch_all_amc_etfs()
    print(f"\n=== 결과 {len(rows)}건 ===")
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
