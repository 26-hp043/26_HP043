#!/usr/bin/env bash
# SSH argv에는 값 대신 목적지·bash -s만 둔다 (#2117).
# 호출: ssh_stdin user@host VARIABLE_NAME ... <<'ENDSSH'
# 값은 Bash 내장 printf %q로 인용해 원격 스크립트의 stdin 앞에 붙인다.

ssh_stdin() {
  set +x
  local destination="$1"
  shift
  local variable
  for variable in "$@"; do
    if [[ ! "$variable" =~ ^[A-Z][A-Z0-9_]*$ ]] || [[ ! -v "$variable" ]]; then
      builtin printf 'SSH 입력 변수 이름이 잘못됐거나 값이 없습니다: %s\n' "$variable" >&2
      return 2
    fi
  done
  {
    # 값의 할당이 추적 로그에 나오지 않게 한다. 실제 값/전체 payload를 출력하지 않는다.
    builtin printf 'set +x\n'
    for variable in "$@"; do
      builtin printf '%s=%q\n' "$variable" "${!variable}"
    done
    cat
  } | command ssh -i ~/.ssh/id_oci -o StrictHostKeyChecking=yes "$destination" bash -s
}
