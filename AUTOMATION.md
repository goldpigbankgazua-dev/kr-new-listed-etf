# 자동 업데이트 동작 방식

## 아키텍처

```
매주 일요일 23:00 UTC (월요일 08:00 KST)
        ↓
GitHub Actions (.github/workflows/weekly-update.yml)
        ↓
scripts/update_etfs.py 실행
        ↓
unjena.com ETF 카테고리에서 [신규상장 ETF] 글 6개 스캔
        ↓
각 글의 표에서 종목명·티커·총보수·특징 추출
        ↓
index.html의 ETFS 배열과 비교 → 기존에 없는 티커만 추가
        ↓
변경이 있으면 자동 커밋 + 푸시
        ↓
GitHub Pages가 자동 재배포
```

## 노트북 OFF여도 작동

GitHub Actions는 GitHub 서버에서 실행되므로 사용자 환경과 무관합니다.

## 수동 실행

저장소 → Actions 탭 → **Weekly ETF update** → **Run workflow** 버튼

## 테마/운용사 자동 분류 규칙

`scripts/update_etfs.py`의 `BRAND_TO_OP`, `THEME_RULES`, `EXTRA_TAGS`에 정의.

- 운용사: ETF 이름의 첫 단어(예: `KODEX`, `TIGER`)로 매핑
- 주 테마: 이름·설명에서 키워드 매칭(우선순위: 레버리지 → 커버드콜 → 채권혼합 → 반도체 → AI → 로봇 → 우주 → 바이오)
- 보조 태그(themes 배열): 월배당·고배당·액티브·미국·코스닥·은 등 추가 키워드 매칭

오분류된 항목은 `index.html`에서 직접 수정해도 자동 업데이트에 영향이 없습니다 (티커가 같으면 스킵됨).

## 데이터 소스 변경 시

다른 블로그/사이트를 추가하려면 `find_post_urls`, `parse_post` 함수를 확장하세요.
