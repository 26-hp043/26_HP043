// 상류 API 응답과 이 Function의 설정 오류 응답에 같은 정책을 적용한다 (#2111).
export { attachSecurityHeaders as onRequest } from '../_securityHeaders'
