/**
 * 좌표를 사람이 읽는 표기로 (`#1913`).
 *
 * 개략도(`PositionChart`)가 자기 밑에 적던 함수를 꺼냈다. 선박 상세가 **개략도와 지도를
 * 같은 자리에서 갈아 끼우므로**(자산·WebGL 유무), 두 쪽의 좌표 표기가 갈리면 화면이
 * 바뀔 때 **바뀐 것이 위치인지 표기인지** 알 수 없다. 같은 함수를 쓰게 둔다.
 *
 * 컴포넌트 파일에 두지 않는 이유는 lint 규칙(`react/only-export-components`)이다 —
 * 컴포넌트 파일이 함수를 함께 내보내면 fast refresh가 깨진다.
 */

/**
 * 위도 — `37.4°N` · `35.1°S`.
 *
 * 부호 대신 방위 문자를 쓰는 것이 해도의 관행이고, **음수 부호는 「남위」보다 읽는 데
 * 한 단계가 더 든다.** 소수 1자리는 개략도의 축척(최소 0.5°)에서 의미가 남는 마지막 자리다.
 */
export function formatLat(v: number): string {
  return `${Math.abs(v).toFixed(1)}°${v >= 0 ? 'N' : 'S'}`
}

/** 경도 — `126.5°E` · `74.0°W`. 규칙은 `formatLat`과 같다. */
export function formatLon(v: number): string {
  return `${Math.abs(v).toFixed(1)}°${v >= 0 ? 'E' : 'W'}`
}
