# frontend — CII 플랫폼 웹 UI

React · Vite · TypeScript로 만든 프론트엔드입니다. 백엔드(`src/cii_platform/**`)와 같은
저장소에 두어 이슈·PR·CI를 한곳에서 관리합니다(#133).

## 요구 환경

| 항목 | 최소 버전 |
|---|---|
| Node.js | **22.22.0** |
| React | **19.2.8** |

설치는 `package-lock.json` 기준 `npm ci`로 합니다.

## 실행

```bash
cd frontend
npm ci          # 최초 1회 (package-lock.json 기준 재현 설치)
npm run dev     # 개발 서버
npm run build   # 타입 검사(tsc -b) + 프로덕션 빌드
npm run lint    # oxlint
```

기본 진입 경로는 대시보드(선대 계층)입니다. `/`로 들어오면 `/dashboard`로 이동합니다(#348).

## 디렉터리

```
frontend/
├── index.html
├── src/
│   ├── main.tsx            ← 진입점. 토큰·전역 CSS 로드
│   ├── App.tsx             ← 라우트 정의 (UIFLOW §1·§2 화면)
│   ├── screens.ts          ← 화면 메타 (ID → 메타 · 사이드바 순서 · 폭 정책)
│   ├── api/                ← API 기준 주소·응답 필드 처리
│   ├── auth/               ← 세션·라우트 가드
│   ├── layout/             ← 공통 셸 (좌측 사이드바 + 상단바)
│   ├── components/         ← 공통 컴포넌트 (면책 배너, 준비 중, 등급 패턴 defs)
│   ├── design/tokens/      ← Figma 내보내기 토큰(JSON) — `npm run build:tokens`의 입력
│   ├── display/            ← DESIGN_SYSTEM §4 구현 (자릿수 · 구분자 · 단위) [#392]
│   ├── download/           ← 파일 내려받기
│   ├── features/           ← 기능 단위 (fleet · vessel-detail · voyage-cii · scenario-comparison · annual-simulation 등)
│   ├── i18n/               ← 한국어·영어 문구와 언어 전환
│   ├── pages/              ← 화면별 컴포넌트
│   ├── theme/              ← 라이트·다크 모드 상태와 전환 토글
│   ├── test/               ← 테스트 공용 도구
│   └── styles/
│       ├── tokens.css          ← DESIGN_SYSTEM.md §15 토큰 (별칭)
│       ├── tokens.generated.css ← `design/tokens/*.json`에서 생성한 토큰
│       └── global.css          ← reset · 타이포그래피 기본
├── e2e/ · functions/ · scripts/   ← Playwright 검사 · Pages Function · 빌드·검사 스크립트
└── public/
```

## 기준 문서

**프론트엔드의 화면 구조와 시각 표현은 디자인 문서가 소유합니다.**

| 영역 | 기준 |
|---|---|
| 화면 목록·계층·흐름·진입 조건 | `UIFLOW.md` §1 · §2 |
| 색·타이포·간격·컴포넌트·레이아웃·접근성 | `DESIGN_SYSTEM.md` |
| 면책·경고 문구 원문 | `PRD.md` §6.3 (DESIGN_SYSTEM §13이 문구 정의를 PRD로 넘김) |
| 계산·검증 규칙·API 요청/응답 계약 | `PRD.md` · `TECH_SPEC.md` · `API_SPEC.md` |

> `PRD v4.0`(#343)·`UIFLOW v2.0`(#344)가 같은 3계층 구조로 확정되면서 종전의
> PRD ↔ UIFLOW 화면 정의 불일치는 해소됐습니다. 화면 구조는 `UIFLOW.md`를 따릅니다.

## 구현 제약 (8/8까지)

`#133` 본문의 제약을 따릅니다. 벗어나야 할 이유가 생기면 이슈에 근거를 남기고 판단을 받습니다.

- **상태 관리·폼 라이브러리를 설치하지 않습니다** — Redux · Zustand · react-hook-form · zod 등.
  React 기본 상태(`useState`)와 자바스크립트 내장 메서드로 구현합니다.
- **스타일링은 순수 CSS 파일만 사용합니다** — Tailwind · styled-components 등을 도입하지 않습니다.
- **색·간격·반경 값은 `styles/tokens.css`의 커스텀 프로퍼티로만 참조합니다.**
  하드코딩 hex는 금지입니다(`DESIGN_SYSTEM.md` §15).
- 라이트·다크 두 모드를 모두 지원합니다. 색 토큰은 두 값을 함께 정의하고(`DESIGN_SYSTEM.md` §0.2 · §2.2),
  모드 전환은 `src/theme/`가 맡습니다. 레이아웃은 1920 프레임 기준이며, 주·부 영역이 좁은 폭에서
  스스로 한 단으로 접는 화면이 있습니다(`DESIGN_SYSTEM.md` §7.1).

## 참조 문서

- `PRD.md` §6.1(네비게이션) · §6.2(화면 목록) · §6.3(공통 UX 문구)
- `DESIGN_SYSTEM.md` §3(타이포) · §5~§8(형태·간격·레이아웃·컴포넌트) · §13(면책) · §14(접근성) · §15(토큰)
- `TECH_SPEC.md` §16.2(디렉터리 구조)
