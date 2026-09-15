# ops/cubrid/conf -- CUBRID ACL 설정

이 디렉토리의 파일은 `docker-compose.prod.db.yml`에서 read-only bind-mount된다.

## ACL 템플릿 치환

`broker_access.conf`에 `REPLACE_ME_APP_PRIVATE_IP` 플레이스홀더가 있다.
배포 전 app-01의 VCN 사설 IP로 바꿔야 한다.

```bash
# 자동 (deploy 워크플로가 수행)
sed -i "s/REPLACE_ME_APP_PRIVATE_IP/10.0.1.216/g" \
  ops/cubrid/conf/broker_access.conf \
  ops/cubrid/conf/server_access.conf

# 수동 (편집기로 직접)
vi ops/cubrid/conf/broker_access.conf
```

## dba 비밀번호 설정

cubrid/cubrid:11.4 이미지는 환경 변수와 무관하게 dba를 빈 비밀번호로 생성한다.
첫 부트 후 수동으로 설정한다:

```bash
docker compose -f docker-compose.prod.db.yml exec -T cubrid \
  csql -u dba cii -c "ALTER USER dba PASSWORD 'YOUR_PASSWORD';"

# 비밀번호 적용 후 브로커 재시작 (CAS 워커가 인증 상태를 캐시하므로)
docker compose -f docker-compose.prod.db.yml restart cubrid
```

## 런타임 ACL 재로드 (재시작 불필요)

```bash
# 브로커 ACL
docker exec cii-cubrid broker_changer BROKER1 access_control reload

# 서버 ACL
docker exec cii-cubrid cubrid server acl reload cii
```

## 4층 방어 구조

| 층 | 위치 | 파일/설정 |
|----|------|-----------|
| 1 | OCI Security List | OCI 콘솔에서 설정 |
| 2 | Host ufw | `ops/host/ufw-db-01.sh` |
| 3 | CUBRID broker ACL | `broker_access.conf` |
| 4 | CUBRID server ACL | `server_access.conf` |
