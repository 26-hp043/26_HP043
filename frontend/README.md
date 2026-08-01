# frontend — CII 플랫폼 웹 UI

React · Vite · TypeScript로 만든 프론트엔드입니다. 백엔드(`src/cii_platform/**`)와 같은
저장소에 두어 이슈·PR·CI를 한곳에서 관리합니다(#133).

## 실행

```bash
cd frontend
npm ci          # 최초 1회 (package-lock.json 기준 재현 설치)
npm run dev     # 개발 서버
npm run build   # 타입 검사(tsc -b) + 프로덕션 빌드
npm run lint    # oxlint
```

기본 진입 경로는 기능①(항차 CII 추정) 화면입니다. `/`로 들어오면 `/voyage-cii`로 이동합니다.

## 디렉터리

```
frontend/
├── index.html
├── src/
│   ├── main.tsx            ← 진입점. 토큰·전역 CSS 로드
│   ├── App.tsx             ← 라우트 정의 (PRD §6.2 화면 7개)
│   ├── screens.ts          ← 화면 메타 정본 (경로·라벨·폭 정책)
│   ├── layout/             ← 공통 셸 (좌측 사이드바 + 상단바)
│   ├── components/         ← 공통 컴포넌트 (면책 배너, 준비 중, 등급 패턴 defs)
│   ├── pages/              ← 화면별 컴포넌트
│   └── styles/
│       ├── tokens.css      ← DESIGN_SYSTEM.md §15 토큰
│       └── global.css      ← reset · 타이포그래피 기본
└── public/
```

## 구현 제약 (8/8까지)

`#133` 본문의 제약을 따릅니다. 벗어나야 할 이유가 생기면 이슈에 근거를 남기고 판단을 받습니다.

- **상태 관리·폼 라이브러리를 설치하지 않습니다** — Redux · Zustand · react-hook-form · zod 등.
  React 기본 상태(`useState`)와 자바스크립트 내장 메서드로 구현합니다.
- **스타일링은 순수 CSS 파일만 사용합니다** — Tailwind · styled-components 등을 도입하지 않습니다.
- **색·간격·반경 값은 `styles/tokens.css`의 커스텀 프로퍼티로만 참조합니다.**
  하드코딩 hex는 금지입니다(`DESIGN_SYSTEM.md` §15).
- 데스크톱 1920 · Light Mode 기준입니다. 반응형·다크모드는 범위 밖입니다.

## 참조 문서

- `PRD.md` §6.1(네비게이션) · §6.2(화면 목록) · §6.3(공통 UX 문구)
- `DESIGN_SYSTEM.md` §3(타이포) · §5~§8(형태·간격·레이아웃·컴포넌트) · §13(면책) · §14(접근성) · §15(토큰)
- `TECH_SPEC.md` §16.2(디렉터리 구조)
