import { LogOut } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'

export default function PlatformAccount() {
  const session = useAuthStore(state => state.session)
  const name = session?.alias || session?.username || '未登录'
  return <div className="platform-account">
    <span className="platform-avatar" aria-label="用户头像">{Array.from(name)[0]}</span>
    <div className="platform-account-name"><strong>{name}</strong><span>{session?.username}</span></div>
    <button type="button" className="button small account-logout" onClick={() => useAuthStore.getState().clearSession()}><LogOut size={16} />退出登录</button>
  </div>
}
