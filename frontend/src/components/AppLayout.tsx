import NavBar, { ROLE_THEME } from './NavBar'
import { useAuthStore } from '../store/authStore'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore()

  const pageBg =
    user?.role === 'admin'   ? ROLE_THEME.admin.pageBg :
    user?.role === 'manager' ? ROLE_THEME.manager.pageBg :
                               ROLE_THEME.cashier.pageBg

  return (
    <div className={`min-h-screen flex flex-col ${pageBg}`}>
      <NavBar />
      <div className="flex-1 flex flex-col">
        {children}
      </div>
    </div>
  )
}
