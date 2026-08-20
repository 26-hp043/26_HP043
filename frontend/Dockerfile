# 프론트엔드 프로덕션 이미지 (#240)
#
# 왜 nginx인가 — 서빙 방식 3안 중 ⑴
#   ⑴ nginx가 정적 자산 + /api 리버스 프록시   ← 채택
#   ⑵ FastAPI가 StaticFiles로 빌드 산출물 서빙
#   ⑶ 정적 호스팅 분리 + CORS
#
#   apiProvider.ts의 기본 base URL이 상대 경로 `/api/v1`이고, vite.config.ts 주석이
#   *"백엔드에 개발 전용 설정을 넣지 않는다"*로 CORS를 의도적으로 배제했다. 그 판단은
#   **같은 오리진에 서빙되는 프로덕션**을 전제로 한다. ⑶을 택하면 그 전제가 깨져
#   백엔드에 CORSMiddleware를 넣고 vite.config.ts 주석도 고쳐야 한다.
#
#   ⑵는 컨테이너가 하나로 줄지만 백엔드 이미지가 프론트엔드 빌드 산출물을 품게 되어,
#   화면만 고쳐도 API 이미지를 다시 굽는다. 계층 분리(TECH_SPEC §16)와도 어긋난다.
#
#   ⑴은 정적 자산 서빙을 nginx에 맡기고 같은 오리진을 유지한다 — 상대 경로 전제가
#   그대로 성립하고 CORS가 필요 없다.

# --- build stage --------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# 의존성 레이어를 소스와 분리해 캐시가 살아 있게 한다.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# ⚠️ Vite는 VITE_* 값을 **빌드 시점에 인라인**한다. 런타임 환경변수로는 바뀌지 않는다.
#    그래서 build-arg로 받아 빌드에 넣는다. 값을 바꾸려면 이미지를 다시 구워야 한다.
#    (README 「배포」 절에 이 제약을 적어 두었다.)
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# --- serve stage --------------------------------------------------------------------
FROM nginx:1.27-alpine AS prod

# 기본 설정을 지우고 우리 설정만 둔다 — default.conf가 남아 있으면 server 블록이
# 둘이 되어 어느 쪽이 뜨는지 순서에 의존한다.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx 이미지에 wget이 있어 그대로 쓴다(백엔드는 curl이 없어 python urllib를 썼다).
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://localhost/ || exit 1
