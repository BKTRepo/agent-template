export default function PlatformAccount() {
  // 右上角沿用原型展示；接口权限仍由平台 token 的真实用户决定。
  return <>
    <div className="team-selector">
      <span>当前团队：</span><strong>测试一组</strong><span className="team-chevron" aria-hidden="true">∨</span>
    </div>
    <span className="platform-avatar" aria-label="用户头像">何</span>
  </>
}
