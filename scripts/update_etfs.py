#!/usr/bin/env python3
"""
신규상장 ETF 자동 업데이트 스크립트.

- unjena.com ETF 카테고리에서 "[신규상장 ETF]" 글을 찾아
- 각 글의 표(| 종목명 | 티커명 | 총보수 | 특징 |)에서 ETF를 추출
- 기존 index.html의 ETFS 배열에 없는 티커만 추가
- 변경이 있으면 index.html을 다시 쓴다 (GitHub Actions가 커밋/푸시)
"""

import datetime
import html as html_lib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

# KIND 스크래퍼 (선택적 — fetch_kind_etfs.py 가 같은 폴더에 있어야 함)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from fetch_kind_etfs import fetch_kind_etfs
except Exception as _e:
    print(f"[update_etfs] KIND 모듈 로드 실패: {_e}")
    fetch_kind_etfs = None

CATEGORY_URL = "https://unjena.com/category/" + urllib.parse.quote("언제나 이티에프..", safe="")
INDEX_HTML = os.path.join(os.path.dirname(__file__), "..", "index.html")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
}

# 운용사 이름 매핑 (브랜드 → 정식명)
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
}

# 테마 키워드 (우선순위 순서대로 매칭)
THEME_RULES = [
    ("레버리지", ["레버리지", "인버스", "단일종목", "선물단일"]),
    ("커버드콜", ["커버드콜"]),
    ("채권혼합", ["채권혼합", "국채혼합", "채권 혼합"]),
    ("반도체", ["반도체", "삼성전자", "SK하이닉스", "HBM", "메모리반도체"]),
    ("AI",     ["AI", "인공지능", "광통신", "데이터센터"]),
    ("로봇",   ["로봇", "휴머노이드", "피지컬AI", "피지컬 AI"]),
    ("우주",   ["우주", "스페이스", "뉴스페이스", "위성"]),
    ("바이오", ["바이오", "헬스케어", "신약", "제약"]),
]

EXTRA_TAGS = [
    ("월배당", ["월배당", "위클리", "분배금"]),
    ("고배당", ["고배당"]),
    ("액티브", ["액티브", "Active"]),
    ("미국",   ["미국", "US ", "S&P", "나스닥"]),
    ("코스닥", ["코스닥"]),
    ("코스피200", ["코스피200"]),
    ("은",     ["은액티브", "은채권", "Silver", "은 현물"]),
]


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    # 우선 utf-8 시도
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("euc-kr", errors="replace")


def detect_op(name: str) -> str:
    head = name.split()[0] if name else ""
    return BRAND_TO_OP.get(head, "기타운용사")


def detect_theme(name: str, desc: str) -> str:
    text = f"{name} {desc}"
    for theme, keywords in THEME_RULES:
        if any(k in text for k in keywords):
            return theme
    return "기타"


def detect_extra_tags(name: str, desc: str, primary: str) -> list:
    text = f"{name} {desc}"
    tags = [primary]
    for tag, keywords in EXTRA_TAGS:
        if any(k in text for k in keywords) and tag not in tags:
            tags.append(tag)
    return tags


def find_post_urls(category_html: str) -> list:
    """카테고리 페이지에서 [신규상장 ETF] 글 URL 추출"""
    urls = re.findall(r'href="(https?://unjena\.com/\d+)"[^>]*>\s*\[?신규상장', category_html)
    # 중복 제거 + 순서 유지
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


TITLE_DATE_RE = re.compile(r"\[신규상장\s*ETF\]\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")


def parse_post(post_html: str):
    """글에서 (상장일, [{name, ticker, fee, desc}, ...]) 추출"""
    # 제목에서 날짜 파싱
    title_match = TITLE_DATE_RE.search(post_html)
    if not title_match:
        return None, []
    y, m, d = map(int, title_match.groups())
    listing_date = f"{y:04d}-{m:02d}-{d:02d}"

    # 본문 텍스트(태그 제거 + entity 디코드)
    body = re.sub(r"<script.*?</script>", "", post_html, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)

    # 표 행에서 ETF 추출 (마크다운 또는 HTML 표 모두 대응)
    # 패턴 1: "| 종목명 | 티커명 | 총보수 | 특징 |" 다음에 오는 행들
    rows = []
    # HTML <tr><td>..</td></tr> 패턴
    tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", flags=re.S | re.I)
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", flags=re.S | re.I)
    for tr_match in tr_pattern.finditer(body):
        tds = td_pattern.findall(tr_match.group(1))
        if len(tds) < 4:
            continue
        cells = [clean_html(t) for t in tds[:4]]
        if validate_etf_row(cells):
            rows.append(cells)

    # 마크다운 표 (| ... | ... |) 패턴
    md_pattern = re.compile(r"\|\s*([^|\n]+?)\s*\|\s*(\d{6}|[\dA-Z]{6})\s*\|\s*([\d.]+%)\s*\|\s*([^\n|][^\n]*?)\s*\|")
    for m_match in md_pattern.finditer(re.sub(r"<[^>]+>", "", body)):
        name, ticker, fee, desc = m_match.groups()
        cells = [clean_html(name), ticker.strip(), fee.strip(), clean_html(desc)]
        if validate_etf_row(cells):
            rows.append(cells)

    # 중복 제거 (티커 기준)
    seen_tickers, unique_rows = set(), []
    for r in rows:
        if r[1] in seen_tickers:
            continue
        seen_tickers.add(r[1])
        unique_rows.append({
            "name": r[0],
            "ticker": r[1],
            "fee": r[2],
            "desc": r[3],
        })

    return listing_date, unique_rows


def clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


TICKER_RE = re.compile(r"^[\dA-Z]{6}$")


def validate_etf_row(cells: list) -> bool:
    if len(cells) < 4:
        return False
    name, ticker, fee, desc = cells[:4]
    if not name or len(name) < 3:
        return False
    if not TICKER_RE.match(ticker):
        return False
    if "%" not in fee:
        return False
    return True


def read_existing_etfs(index_path: str):
    """index.html에서 ETFS 배열을 추출 (티커 집합 + 원본 텍스트 + 삽입 지점)"""
    with open(index_path, encoding="utf-8") as f:
        html = f.read()
    match = re.search(r"const ETFS = \[\s*\n([\s\S]*?)\n\];", html)
    if not match:
        raise RuntimeError("index.html에서 ETFS 배열을 찾지 못했습니다.")
    body = match.group(1)
    tickers = set(re.findall(r'ticker:"([^"]+)"', body))
    return html, match, tickers


def js_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def make_entry(etf: dict, listing_date: str, today: str) -> str:
    name = etf["name"]
    desc = etf["desc"]
    primary_theme = detect_theme(name, desc)
    themes = detect_extra_tags(name, desc, primary_theme)
    op = detect_op(name)
    if listing_date > today:
        desc = desc.rstrip(". ") + " (상장예정)"
    # idx (기초지수)는 자동 추론 어려우니 비워두고, 운용사 페이지 검색에 위임
    idx = ""
    return (
        f'  {{date:"{listing_date}", '
        f'name:"{js_escape(name)}", '
        f'ticker:"{etf["ticker"]}", '
        f'op:"{js_escape(op)}", '
        f'fee:"{etf["fee"]}", '
        f'theme:"{primary_theme}", '
        f'themes:[{", ".join(json.dumps(t, ensure_ascii=False) for t in themes)}], '
        f'idx:"{js_escape(idx)}", '
        f'desc:"{js_escape(desc)}"}}'
    )


def main():
    today = datetime.date.today().isoformat()
    print(f"[update_etfs] 시작 {today}")

    # 1) 기존 ETFS 로드
    html, etfs_match, existing_tickers = read_existing_etfs(INDEX_HTML)
    print(f"  기존 ETF 수: {len(existing_tickers)}")

    # 2) 카테고리에서 신규상장 글 URL 수집
    cat_html = http_get(CATEGORY_URL)
    post_urls = find_post_urls(cat_html)
    print(f"  발견된 신규상장 글 수: {len(post_urls)}")

    # 3) 각 글에서 ETF 파싱, 신규 티커만 모음
    new_entries = []
    for url in post_urls[:6]:  # 최신 6건만 확인 (성능)
        try:
            post_html = http_get(url)
        except Exception as e:
            print(f"  [skip] {url}: {e}")
            continue
        listing_date, etfs = parse_post(post_html)
        if not listing_date:
            continue
        for etf in etfs:
            if etf["ticker"] in existing_tickers:
                continue
            existing_tickers.add(etf["ticker"])
            new_entries.append((listing_date, etf))
            print(f"  + {listing_date} {etf['ticker']} {etf['name']}")

    # 3b) KIND 추가 — unjena 가 빠뜨린 신규 상장 ETF 잡기
    if fetch_kind_etfs is not None:
        try:
            existing_names = {entry["name"] for _, entry in new_entries}
            # 기존 ETFS 의 종목명도 확인 (ticker 없는 KIND 데이터의 중복 방지)
            existing_names_full = set()
            for m in re.finditer(r'name:"([^"]+)"', html):
                existing_names_full.add(m.group(1))
            existing_names_full |= existing_names

            kind_rows = fetch_kind_etfs(days_back=14)
            print(f"  KIND 발견: {len(kind_rows)}건")
            for row in kind_rows:
                name = row.get("name", "").strip()
                if not name or name in existing_names_full:
                    continue
                # ticker 있으면 ticker 기반 중복도 체크
                tk = row.get("ticker", "").strip()
                if tk and tk in existing_tickers:
                    continue
                etf = {
                    "name": name,
                    "ticker": tk,
                    "op": row.get("op", "").strip(),
                    "fee": row.get("fee", "").strip(),
                    "themes_extra": [],
                    "desc": row.get("desc", "(상장예정)").strip() or "(상장예정)",
                }
                listing_date = row.get("date", today)
                if tk:
                    existing_tickers.add(tk)
                existing_names_full.add(name)
                new_entries.append((listing_date, etf))
                print(f"  + [KIND] {listing_date} {tk or '(no-ticker)'} {name}")
        except Exception as e:
            print(f"  [KIND] 실패: {e}")

    if not new_entries:
        print("[update_etfs] 추가할 신규 ETF 없음. 종료.")
        return 0

    # 4) ETFS 배열 맨 위에 새 항목 삽입 (날짜 desc 정렬)
    new_entries.sort(key=lambda x: x[0], reverse=True)
    new_lines = [make_entry(e, d, today) for d, e in new_entries]
    new_block = ",\n".join(new_lines) + ",\n"
    original_body = etfs_match.group(1)
    updated_body = new_block + original_body
    updated_html = html[: etfs_match.start(1)] + updated_body + html[etfs_match.end(1):]

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(updated_html)

    print(f"[update_etfs] {len(new_entries)}건 추가 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
