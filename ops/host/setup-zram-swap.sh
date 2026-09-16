#!/usr/bin/env bash
# setup-zram-swap.sh -- OCI VM.Standard.E2.1.Micro (1GB RAM) 메모리 최적화.
#
# our-tax에서 가져온 스크립트. 두 프로젝트가 같은 VM을 공유하므로
# 이미 적용되어 있을 수 있다 -- 멱등하게 동작한다.
#
# 구성:
#   - zram 스왑: RAM의 50% (lz4 압축, ~2:1 비율로 실효 ~1GB)
#   - 디스크 스왑파일: 1GB 폴백 (zram 미지원 시)
#   - sysctl: swappiness=10, vfs_cache_pressure=50
#
# 사용법:
#   sudo ./ops/host/setup-zram-swap.sh

set -euo pipefail

echo "==> zram 스왑 설정 (1GB RAM VM용)"

# zram 모듈 로드
if modprobe zram 2>/dev/null; then
  # 기존 zram0이 없을 때만 생성
  if [ ! -e /dev/zram0 ] || ! swapon --show=NAME --noheadings | grep -q zram0; then
    ZRAM_SIZE=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') * 1024 / 2 ))
    echo lz4 > /sys/block/zram0/comp_algorithm 2>/dev/null || true
    echo "${ZRAM_SIZE}" > /sys/block/zram0/disksize
    mkswap /dev/zram0
    swapon -p 100 /dev/zram0
    echo "   zram0: $(( ZRAM_SIZE / 1024 / 1024 ))MB (lz4)"
  else
    echo "   zram0: 이미 활성화됨"
  fi
else
  echo "   zram 미지원 -- 디스크 스왑파일로 폴백"
  SWAPFILE=/swapfile
  if [ ! -f "${SWAPFILE}" ]; then
    fallocate -l 1G "${SWAPFILE}"
    chmod 600 "${SWAPFILE}"
    mkswap "${SWAPFILE}"
    swapon "${SWAPFILE}"
    echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
    echo "   스왑파일 1GB 생성"
  else
    echo "   스왑파일 이미 존재"
  fi
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
free -h
