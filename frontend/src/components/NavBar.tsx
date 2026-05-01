import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

// ── Role colour themes ────────────────────────────────────────────��────────
// Full class strings kept literal so Tailwind's static scanner keeps them.

export const ROLE_THEME = {
  cashier: {
    nav:       'bg-sky-600 border-sky-700',
    active:    'bg-sky-800 text-white',
    hover:     'text-sky-100 hover:bg-sky-700 hover:text-white',
    brand:     'text-white',
    userChip:  'bg-sky-500 text-sky-100',
    roleLabel: 'bg-sky-800 text-sky-200',
    pageBg:    'bg-sky-100',
  },
  manager: {
    nav:       'bg-emerald-700 border-emerald-800',
    active:    'bg-emerald-900 text-white',
    hover:     'text-emerald-100 hover:bg-emerald-600 hover:text-white',
    brand:     'text-white',
    userChip:  'bg-emerald-600 text-emerald-100',
    roleLabel: 'bg-emerald-900 text-emerald-200',
    pageBg:    'bg-emerald-100',
  },
  admin: {
    nav:       'bg-violet-800 border-violet-900',
    active:    'bg-violet-950 text-white',
    hover:     'text-violet-100 hover:bg-violet-700 hover:text-white',
    brand:     'text-white',
    userChip:  'bg-violet-700 text-violet-100',
    roleLabel: 'bg-violet-950 text-violet-300',
    pageBg:    'bg-violet-100',
  },
} as const

type Role = keyof typeof ROLE_THEME

function getTheme(role: string | undefined) {
  if (role === 'admin') return ROLE_THEME.admin
  if (role === 'manager') return ROLE_THEME.manager
  return ROLE_THEME.cashier
}

export default function NavBar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()

  const theme = getTheme(user?.role)
  const isManager = user?.role === 'manager' || user?.role === 'admin'
  const isAdmin = user?.role === 'admin'

  function handleLogout() {
    logout()
    navigate('/login')
  }

  function navClass(path: string) {
    const active = location.pathname === path
    return `text-sm px-3 py-1.5 rounded transition font-medium ${
      active ? theme.active : theme.hover
    }`
  }

  const roleDisplay = user?.role
    ? user.role.charAt(0).toUpperCase() + user.role.slice(1)
    : ''

  return (
    <nav className={`${theme.nav} border-b shadow-sm px-6 py-3 flex items-center justify-between sticky top-0 z-50`}>
      {/* Brand */}
      <span
        className={`font-bold text-lg tracking-tight cursor-pointer select-none ${theme.brand}`}
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
            <button onClick={() => navigate('/replay')} className={navClass('/replay')}>
              Replay
            </button>
          </>
        )}
        {isAdmin && (
          <>
            <button onClick={() => navigate('/audit')} className={navClass('/audit')}>
              Audit Trail
            </button>
            <button onClick={() => navigate('/admin')} className={navClass('/admin')}>
              User Management
            </button>
          </>
        )}
        {isManager && (
          <button onClick={() => navigate('/settings')} className={navClass('/settings')}>
            Settings
          </button>
        )}
        {!isManager && (
          <button onClick={() => navigate('/pos')} className={navClass('/pos')}>
            POS
          </button>
        )}
      </div>

      {/* User + role badge + POS switch + logout */}
      <div className="flex items-center gap-3">
        {isManager && (
          <button
            onClick={() => navigate('/pos')}
            className="text-xs px-2.5 py-1 rounded font-medium bg-white/15 text-white hover:bg-white/25 transition border border-white/20"
          >
            POS
          </button>
        )}
        <span className={`text-xs px-2 py-0.5 rounded font-semibold uppercase tracking-wide ${theme.roleLabel}`}>
          {roleDisplay}
        </span>
        <span className="text-xs text-white/60">{user?.email}</span>
        <button
          onClick={handleLogout}
          className="text-xs text-white/50 hover:text-white hover:underline transition"
        >
          Log out
        </button>
      </div>
    </nav>
  )
}
