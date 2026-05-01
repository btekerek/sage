import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import AdminPage from './pages/AdminPage'
import AuditTrailPage from './pages/AuditTrailPage'
import DashboardPage from './pages/DashboardPage'
import InventoryPage from './pages/InventoryPage'
import InvoicesPage from './pages/InvoicesPage'
import LoginPage from './pages/LoginPage'
import POSPage from './pages/POSPage'
import ReplayPage from './pages/ReplayPage'
import SettingsPage from './pages/SettingsPage'
import AppLayout from './components/AppLayout'
import { UserRole, useAuthStore } from './store/authStore'

// ── Role-based guard ─────────────────────────────────────────────────────────

const ROLE_RANK: Record<UserRole, number> = { staff: 1, manager: 2, admin: 3 }

function ProtectedRoute({
  element,
  minRole,
}: {
  element: JSX.Element
  minRole: UserRole
}) {
  const { isAuthenticated, user } = useAuthStore()

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />
  }

  if (ROLE_RANK[user.role] < ROLE_RANK[minRole]) {
    // Redirect to the highest page the user is allowed to see
    const fallback = user.role === 'staff' ? '/pos' : '/dashboard'
    return <Navigate to={fallback} replace />
  }

  return element
}

// ── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const { isAuthenticated, user } = useAuthStore()

  // Redirect authenticated users away from /login to their home page
  const loginElement = isAuthenticated
    ? <Navigate to={user?.role === 'staff' ? '/pos' : '/dashboard'} replace />
    : <LoginPage />

  return (
    <Router>
      <Routes>
        <Route path="/login" element={loginElement} />

        {/* All authenticated users */}
        <Route
          path="/pos"
          element={<ProtectedRoute element={<AppLayout><POSPage /></AppLayout>} minRole="staff" />}
        />

        {/* Manager and above */}
        <Route
          path="/dashboard"
          element={<ProtectedRoute element={<AppLayout><DashboardPage /></AppLayout>} minRole="manager" />}
        />
        <Route
          path="/inventory"
          element={<ProtectedRoute element={<AppLayout><InventoryPage /></AppLayout>} minRole="manager" />}
        />
        <Route
          path="/audit"
          element={<ProtectedRoute element={<AppLayout><AuditTrailPage /></AppLayout>} minRole="admin" />}
        />
        <Route
          path="/replay"
          element={<ProtectedRoute element={<AppLayout><ReplayPage /></AppLayout>} minRole="manager" />}
        />
        <Route
          path="/invoices"
          element={<ProtectedRoute element={<AppLayout><InvoicesPage /></AppLayout>} minRole="manager" />}
        />
        <Route
          path="/settings"
          element={<ProtectedRoute element={<AppLayout><SettingsPage /></AppLayout>} minRole="manager" />}
        />

        {/* Admin only */}
        <Route
          path="/admin"
          element={<ProtectedRoute element={<AppLayout><AdminPage /></AppLayout>} minRole="admin" />}
        />

        {/* Catch-all */}
        <Route
          path="*"
          element={
            isAuthenticated
              ? <Navigate to={user?.role === 'staff' ? '/pos' : '/dashboard'} replace />
              : <Navigate to="/login" replace />
          }
        />
      </Routes>
    </Router>
  )
}
