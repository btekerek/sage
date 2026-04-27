import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

export default function NavBar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const isManager = user?.role === 'manager' || user?.role === 'admin'
  const isAdmin = user?.role === 'admin'

  function navClass(path: string) {
    const active = location.pathname === path
    return `text-sm px-3 py-1.5 rounded transition font-medium ${
      active
        ? 'bg-blue-600 text-white'
        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
    }`
  }

  return (
    <nav className="bg-white border-b shadow-sm px-6 py-3 flex items-center justify-between sticky top-0 z-50">
      {/* Brand */}
      <span
        className="font-bold text-lg tracking-tight cursor-pointer select-none"
        onClick={() => navigate(isManager ? '/dashboard' : '/pos')}
      >
        SAGE
      </span>

      {/* Navigation links */}
      <div className="flex items-center gap-1">
        {isManager && (
          <>
            <button onClick={() => navigate('/dashboard')} className={navClass('/dashboard')}>
              Dashboard
            </button>
            <button onClick={() => navigate('/inventory')} className={navClass('/inventory')}>
              Inventory
            </button>
            <button onClick={() => navigate('/invoices')} className={navClass('/invoices')}>
              Invoices
            </button>
            <button onClick={() => navigate('/audit')} className={navClass('/audit')}>
              Audit Trail
            </button>
            <button onClick={() => navigate('/replay')} className={navClass('/replay')}>
              Replay
            </button>
            <button onClick={() => navigate('/settings')} className={navClass('/settings')}>
              Settings
            </button>
          </>
        )}
        <button onClick={() => navigate('/pos')} className={navClass('/pos')}>
          POS
        </button>
        {isAdmin && (
          <button onClick={() => navigate('/admin')} className={navClass('/admin')}>
            Users
          </button>
        )}
      </div>

      {/* User + logout */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-400">{user?.email}</span>
        <button
          onClick={handleLogout}
          className="text-xs text-red-500 hover:text-red-700 hover:underline"
        >
          Log out
        </button>
      </div>
    </nav>
  )
}
