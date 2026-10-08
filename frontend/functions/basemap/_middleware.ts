// 지도 Function이 새로 만드는 206·416에서도 보안 헤더가 빠지지 않는다 (#2111).
export { attachSecurityHeaders as onRequest } from '../_securityHeaders'
