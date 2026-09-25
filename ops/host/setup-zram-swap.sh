#!/usr/bin/env bash
# setup-zram-swap.sh -- OCI VM.Standard.E2.1.Micro (1GB RAM) 메모리 최적화.
#
# our-tax에서 가져온 스크립트. 두 프로젝트가 같은 VM을 공유하므로
# 이미 적용되어 있을 수 있다 -- 멱등하게 동작한다.
#
# 구성:
#   - 디스크 스왑파일 2GB: **재부팅을 견디는 스왑** (/etc/fstab)
#   - zram 스왑: RAM의 50% (lz4, ~2:1 압축) -- 있으면 더 빠른 계층으로 얹는다
#   - sysctl: swappiness=10, vfs_cache_pressure=50
#
# ## 왜 zram만으로는 안 되는가 (#1911)
#
# **zram은 재부팅하면 사라진다.** 이 스크립트가 만드는 zram0에는 systemd 유닛이
# 없어 다음 부팅에서 다시 만들어지지 않는다. 종전 구성은 zram이 되면 스왑파일을
# 만들지 않았으므로, 한 번 재부팅하면 **스왑이 0인 호스트로 돌아갔다.**
#
# 2026-09-25에 app-01이 그 상태(스왑 0)에서 배포 중 메모리가 말라 **호스트째 멈췄다** --
# sshd가 배너조차 돌려주지 못해 배포가 `Broken pipe`로 끊겼고, 같은 시각 API는
# 터널 커넥터가 죽어 Cloudflare `error 1033`이었다. 1GB VM에 두 프로젝트 백엔드가
# 살고 배포가 거기에 이미지 풀과 `migrate` 컨테이너를 얹는 구조라, 여유가 사라지면
# **배포가 실패하는 것이 아니라 호스트가 멈춘다.**
#
# 그래서 순서를 뒤집었다 -- **먼저 재부팅을 견디는 스왑파일**을 두고, zram은
# 있으면 얹는다.
#
# 사용법:
#   sudo ./ops/host/setup-zram-swap.sh
#
# 확인 (재부팅 뒤에도 같아야 한다):
#   swapon --show    # /swapfile 이 보여야 한다
#   free -m

set -euo pipefail

echo "==> 스왑 설정 (1GB RAM VM용)"

# 1) 재부팅을 견디는 스왑파일 -- 이것이 본체다.
SWAPFILE=/swapfile
if swapon --show=NAME --noheadings | grep -qx "${SWAPFILE}"; then
  echo "   ${SWAPFILE}: 이미 활성화됨"
else
  if [ ! -f "${SWAPFILE}" ]; then
    fallocate -l 2G "${SWAPFILE}"
    chmod 600 "${SWAPFILE}"
    mkswap "${SWAPFILE}" >/dev/null
    echo "   ${SWAPFILE}: 2GB 생성"
  fi
  swapon "${SWAPFILE}"
fi
# fstab 등록이 **재부팅을 견디게 하는 유일한 부분**이다. 빠지면 위 swapon은 이번
# 부팅에만 산다 -- 종전 구성이 정확히 그렇게 사라졌다.
grep -q "^${SWAPFILE}" /etc/fstab 2>/dev/null || \
  echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab

# 2) zram -- 있으면 더 빠른 계층으로 얹는다(우선순위 100 > 스왑파일 -2).
#    없어도 1)이 이미 섰으므로 실패로 보지 않는다.
if modprobe zram 2>/dev/null; then
  if [ ! -e /dev/zram0 ] || ! swapon --show=NAME --noheadings | grep -q zram0; then
    ZRAM_SIZE=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') * 1024 / 2 ))
    echo lz4 > /sys/block/zram0/comp_algorithm 2>/dev/null || true
    echo "${ZRAM_SIZE}" > /sys/block/zram0/disksize
    mkswap /dev/zram0 >/dev/null
    swapon -p 100 /dev/zram0
    echo "   zram0: $(( ZRAM_SIZE / 1024 / 1024 ))MB (lz4) -- ⚠️ 재부팅하면 사라진다"
  else
    echo "   zram0: 이미 활성화됨"
  fi
else
  echo "   zram 미지원 -- 스왑파일만 쓴다"
fi

# sysctl 튜닝
sysctl -w vm.swappiness=10
sysctl -w vm.vfs_cache_pressure=50

# 영구 적용
grep -q 'vm.swappiness' /etc/sysctl.conf 2>/dev/null || \
  echo 'vm.swappiness=10' >> /etc/sysctl.conf
grep -q 'vm.vfs_cache_pressure' /etc/sysctl.conf 2>/dev/null || \
  echo 'vm.vfs_cache_pressure=50' >> /etc/sysctl.conf

echo "==> 완료"
swapon --show
free -h
