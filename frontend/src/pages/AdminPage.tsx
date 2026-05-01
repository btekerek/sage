import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore } from '../store/authStore'

type Role = 'admin' | 'manager' | 'staff'

interface User {
  id: string
  email: string
  role: Role
  is_active: boolean
  created_at: string
  updated_at: string
}

// ── Role config ───────────────────────────────────────────────────────────────

const ROLE_BADGE: Record<Role, string> = {
  admin:   'bg-violet-100 text-violet-800',
  manager: 'bg-emerald-100 text-emerald-800',
  staff:   'bg-sky-100 text-sky-700',
}

const ROLE_ACCESS: Record<Role, { label: string; color: string }[]> = {
  staff: [
    { label: 'POS', color: 'bg-sky-100 text-sky-700' },
  ],
  manager: [
    { label: 'POS',       color: 'bg-sky-100 text-sky-700' },
    { label: 'Dashboard', color: 'bg-emerald-100 text-emerald-700' },
    { label: 'Inventory', color: 'bg-emerald-100 text-emerald-700' },
    { label: 'Invoices',  color: 'bg-emerald-100 text-emerald-700' },
    { label: 'Replay',    color: 'bg-emerald-100 text-emerald-700' },
    { label: 'Settings',  color: 'bg-emerald-100 text-emerald-700' },
  ],
  admin: [
    { label: 'All screens',   color: 'bg-violet-100 text-violet-700' },
    { label: 'Audit Trail',   color: 'bg-violet-100 text-violet-700' },
    { label: 'User management', color: 'bg-violet-100 text-violet-700' },
  ],
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('hu-HU', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function fmtDateTime(iso: string) {
  return new Date(iso).toLocaleString('hu-HU', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const navigate = useNavigate()
  const currentUser = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Create user form
  const [showCreate, setShowCreate] = useState(false)
  const [newEmail, setNewEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<Role>('staff')
  const [createError, setCreateError] = useState('')
  const [creating, setCreating] = useState(false)

  // Edit inline
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editRole, setEditRole] = useState<Role>('staff')
  const [editActive, setEditActive] = useState(true)
  const [editPassword, setEditPassword] = useState('')
  const [saving, setSaving] = useState(false)

  async function fetchUsers() {
    try {
      const { data } = await client.get<User[]>('/api/users')
      setUsers(data)
    } catch {
      setError('Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchUsers() }, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreateError('')
    setCreating(true)
    try {
      await client.post('/api/users', { email: newEmail, password: newPassword, role: newRole })
      setNewEmail(''); setNewPassword(''); setNewRole('staff')
      setShowCreate(false)
      await fetchUsers()
    } catch (err: any) {
      const detail = err.response?.data?.detail
      const msg = Array.isArray(detail)
        ? detail.map((e: any) => e.msg ?? String(e)).join(' · ')
        : typeof detail === 'string' ? detail : 'Failed to create user'
      setCreateError(msg)
    } finally {
      setCreating(false)
    }
  }

  function startEdit(u: User) {
    setEditingId(u.id)
    setEditRole(u.role)
    setEditActive(u.is_active)
    setEditPassword('')
  }

  async function saveEdit(userId: string) {
    setSaving(true)
    try {
      const body: Record<string, unknown> = { role: editRole, is_active: editActive }
      if (editPassword) body.password = editPassword
      await client.patch(`/api/users/${userId}`, body)
      setEditingId(null)
      await fetchUsers()
    } catch (err: any) {
      const detail = err.response?.data?.detail
      const msg = Array.isArray(detail)
        ? detail.map((e: any) => e.msg ?? String(e)).join(' · ')
        : typeof detail === 'string' ? detail : 'Failed to save'
      alert(msg)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(userId: string, email: string) {
    if (!window.confirm(`Delete user ${email}? This cannot be undone.`)) return
    try {
      await client.delete(`/api/users/${userId}`)
      await fetchUsers()
    } catch (err: any) {
      alert(err.response?.data?.detail ?? 'Failed to delete user')
    }
  }

  const totalUsers = users.length
  const activeUsers = users.filter(u => u.is_active).length
  const byRole = {
    admin:   users.filter(u => u.role === 'admin').length,
    manager: users.filter(u => u.role === 'manager').length,
    staff:   users.filter(u => u.role === 'staff').length,
  }

  return (
    <div>
      <div className="px-6 py-6">

        {/* ── Page header ── */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">User Management</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Manage accounts, roles, and access permissions
            </p>
          </div>
          <button
            onClick={() => setShowCreate(v => !v)}
            className="bg-violet-700 text-white px-4 py-2 rounded-lg font-medium hover:bg-violet-800 text-sm shadow-sm"
          >
            + New User
          </button>
        </div>

        {/* ── Summary KPIs ── */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          {[
            { label: 'Total users',  value: totalUsers,        color: 'text-gray-800' },
            { label: 'Active',       value: activeUsers,       color: 'text-green-600' },
            { label: 'Admins',       value: byRole.admin,      color: 'text-violet-700' },
            { label: 'Managers',     value: byRole.manager,    color: 'text-emerald-700' },
            { label: 'Staff',        value: byRole.staff,      color: 'text-sky-700' },
          ].map(s => (
            <div key={s.label} className="bg-white rounded-lg shadow p-4">
              <p className="text-xs text-gray-500 uppercase tracking-wide">{s.label}</p>
              <p className={`text-2xl font-bold mt-1 ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>

        {/* ── Create user form ── */}
        {showCreate && (
          <form
            onSubmit={handleCreate}
            className="bg-white rounded-lg shadow p-5 flex flex-wrap gap-3 items-end mb-6 border border-violet-200"
          >
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Email</label>
              <input
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                required
                placeholder="user@example.com"
                className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400 w-56"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                placeholder="min 8 chars, A-Z 0-9 !@#…"
                className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400 w-52"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as Role)}
                className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400"
              >
                <option value="staff">Staff</option>
                <option value="manager">Manager</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={creating}
                className="bg-violet-700 text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-violet-800 disabled:opacity-50"
              >
                {creating ? 'Creating…' : 'Create user'}
              </button>
              <button
                type="button"
                onClick={() => { setShowCreate(false); setCreateError('') }}
                className="bg-gray-100 text-gray-600 px-4 py-1.5 rounded text-sm font-medium hover:bg-gray-200"
              >
                Cancel
              </button>
            </div>
            {createError && (
              <p className="w-full text-sm text-red-600">{createError}</p>
            )}
          </form>
        )}

        {/* ── Users table ── */}
        {loading ? (
          <p className="text-gray-400 text-sm">Loading…</p>
        ) : error ? (
          <p className="text-red-500 text-sm">{error}</p>
        ) : (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b text-xs text-gray-500 uppercase tracking-wide">
                <tr>
                  <th className="text-left px-5 py-3">User</th>
                  <th className="text-left px-5 py-3">Role</th>
                  <th className="text-left px-5 py-3">Screen access</th>
                  <th className="text-left px-5 py-3">Status</th>
                  <th className="text-left px-5 py-3">Created</th>
                  <th className="text-left px-5 py-3">Last modified</th>
                  <th className="px-5 py-3 w-32"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {users.map((u) => (
                  <tr key={u.id} className={`transition-colors ${editingId === u.id ? 'bg-violet-50' : 'hover:bg-gray-50'}`}>
                    {editingId === u.id ? (
                      /* ── Edit row ─────────────────────────────────────── */
                      <>
                        <td className="px-5 py-3">
                          <p className="font-medium text-gray-900">{u.email}</p>
                          <p className="text-xs font-mono text-gray-400 mt-0.5">{u.id.slice(0, 8)}…</p>
                          <input
                            type="password"
                            placeholder="New password (optional)"
                            value={editPassword}
                            onChange={(e) => setEditPassword(e.target.value)}
                            className="mt-2 border rounded px-2 py-1 text-xs w-48 focus:outline-none focus:ring-1 focus:ring-violet-400"
                          />
                        </td>
                        <td className="px-5 py-3">
                          <select
                            value={editRole}
                            onChange={(e) => setEditRole(e.target.value as Role)}
                            disabled={u.id === currentUser?.id}
                            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400"
                          >
                            <option value="staff">Staff</option>
                            <option value="manager">Manager</option>
                            <option value="admin">Admin</option>
                          </select>
                        </td>
                        <td className="px-5 py-3 text-gray-400 text-xs italic">
                          Changes with role
                        </td>
                        <td className="px-5 py-3">
                          <select
                            value={editActive ? 'active' : 'inactive'}
                            onChange={(e) => setEditActive(e.target.value === 'active')}
                            disabled={u.id === currentUser?.id}
                            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400"
                          >
                            <option value="active">Active</option>
                            <option value="inactive">Inactive</option>
                          </select>
                        </td>
                        <td className="px-5 py-3 text-gray-400 text-xs">{fmtDate(u.created_at)}</td>
                        <td className="px-5 py-3 text-gray-400 text-xs">—</td>
                        <td className="px-5 py-3">
                          <div className="flex gap-2">
                            <button
                              onClick={() => saveEdit(u.id)}
                              disabled={saving}
                              className="text-xs bg-violet-700 text-white px-3 py-1 rounded hover:bg-violet-800 disabled:opacity-50 font-medium"
                            >
                              {saving ? 'Saving…' : 'Save'}
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="text-xs bg-gray-100 text-gray-600 px-3 py-1 rounded hover:bg-gray-200"
                            >
                              Cancel
                            </button>
                          </div>
                        </td>
                      </>
                    ) : (
                      /* ── View row ─────────────────────────────────────── */
                      <>
                        {/* User */}
                        <td className="px-5 py-3">
                          <p className="font-semibold text-gray-900">
                            {u.email}
                            {u.id === currentUser?.id && (
                              <span className="ml-2 text-xs text-gray-400 font-normal">(you)</span>
                            )}
                          </p>
                          <p className="text-xs font-mono text-gray-400 mt-0.5">
                            {u.id.slice(0, 8)}…{u.id.slice(-4)}
                          </p>
                        </td>

                        {/* Role */}
                        <td className="px-5 py-3">
                          <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${ROLE_BADGE[u.role]}`}>
                            {u.role.charAt(0).toUpperCase() + u.role.slice(1)}
                          </span>
                        </td>

                        {/* Screen access */}
                        <td className="px-5 py-3">
                          <div className="flex flex-wrap gap-1">
                            {ROLE_ACCESS[u.role].map(a => (
                              <span
                                key={a.label}
                                className={`px-2 py-0.5 rounded text-xs font-medium ${a.color}`}
                              >
                                {a.label}
                              </span>
                            ))}
                          </div>
                        </td>

                        {/* Status */}
                        <td className="px-5 py-3">
                          <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                            u.is_active ? 'text-green-700' : 'text-gray-400'
                          }`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${
                              u.is_active ? 'bg-green-500' : 'bg-gray-300'
                            }`} />
                            {u.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>

                        {/* Created */}
                        <td className="px-5 py-3 text-gray-500 text-xs">
                          {fmtDate(u.created_at)}
                        </td>

                        {/* Last modified */}
                        <td className="px-5 py-3 text-gray-500 text-xs">
                          {fmtDateTime(u.updated_at)}
                        </td>

                        {/* Actions */}
                        <td className="px-5 py-3">
                          <div className="flex gap-3 justify-end">
                            <button
                              onClick={() => startEdit(u)}
                              className="text-xs text-violet-600 hover:text-violet-800 font-medium hover:underline"
                            >
                              Edit
                            </button>
                            {u.id !== currentUser?.id && (
                              <button
                                onClick={() => handleDelete(u.id, u.email)}
                                className="text-xs text-red-400 hover:text-red-600 font-medium hover:underline"
                              >
                                Delete
                              </button>
                            )}
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
