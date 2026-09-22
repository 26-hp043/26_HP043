import { posix, relative as nativeRelative, sep as nativeSep } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * 소스 스캔 가드가 쓰는 경로 두 가지 (`#1615`).
 *
 * ## 파일 I/O 경로와 비교 키를 가른다
 *
 * - **파일 I/O 경로** — `readdirSync`·`readFileSync`에 넘기는 OS 경로. `fileURLToPath()`로 만든다.
 *   종전 `new URL('.', import.meta.url).pathname`은 Windows에서 `/C:/…`가 되고, `join()`에 넘기면
 *   `C:\C:\…`가 되어 `readdirSync`가 `ENOENT`로 끝났다 — 가드가 **실행 전에** 죽었다.
 * - **비교 키** — 테스트가 목록과 대조하는 `src` 기준 상대경로. **POSIX(`/`) 하나로** 맞춘다.
 *   OS 경로만 고치면 Windows의 키가 `auth\session.ts`가 되어 `'auth/session.ts'`와 어긋난다.
 */

/** `import.meta.url` 기준 디렉터리의 OS 경로. 끝에 구분자를 붙인다(종전 `pathname`과 같은 모양). */
export function dirOf(url: string | URL, relativeDir = '.'): string {
  const path = fileURLToPath(new URL(relativeDir, url))
  return path.endsWith(nativeSep) ? path : path + nativeSep
}

/** `root` 기준 상대경로를 POSIX 키로. `pathImpl`은 검사가 Windows 규칙을 끼우는 자리다. */
export function srcKey(
  root: string,
  file: string,
  pathImpl: { relative: (from: string, to: string) => string; sep: string } = {
    relative: nativeRelative,
    sep: nativeSep,
  },
): string {
  return pathImpl.relative(root, file).split(pathImpl.sep).join(posix.sep)
}
