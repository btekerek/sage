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
}

const ROLE_LABELS: Record<Role, string> = {
  admin: 'Admin',
  manager: 'Manager',
  staff: 'Staff',
}

const ROLE_COLORS: Record<Role, string> = {
  admin: 'bg-purple-100 text-purple-800',
  manager: 'bg-blue-100 text-blue-800',
  staff: 'bg-gray-100 text-gray-700',
}

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
        : typeof detail === 'string'
          ? detail
          : 'Failed to create user'
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

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div className="bg-gray-50">
      <div className="px-6 py-6 max-w-4xl">
        {/* Create user */}
        <div className="mb-6">
          {!showCreate ? (
            <button
              onClick={() => setShowCreate(true)}
              className="bg-blue-600 text-white px-4 py-2 rounded font-medium hover:bg-blue-700 text-sm"
            >
              + New User
            </button>
          ) : (
            <form
              onSubmit={handleCreate}
              className="bg-white rounded-lg shadow p-5 flex flex-wrap gap-3 items-end"
            >
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Email</label>
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  required
                  placeholder="user@example.com"
                  className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400 w-56"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                  placeholder="min 6 characters"
                  className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400 w-44"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as Role)}
                  className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
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
                  className="bg-green-600 text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                >
                  {creating ? 'Creating…' : 'Create'}
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
        </div>

        {/* Users table */}
        {loading ? (
          <p className="text-gray-400 text-sm">Loading…</p>
        ) : error ? (
          <p className="text-red-500 text-sm">{error}</p>
        ) : (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">Email</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">Role</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">Status</th>
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">Created</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b last:border-0">
                    {editingId === u.id ? (
                      /* ── Edit row ── */
                      <>
                        <td className="px-4 py-3 font-medium text-gray-800">{u.email}</td>
                        <td className="px-4 py-3">
                          <select
                            value={editRole}
                            onChange={(e) => setEditRole(e.target.value as Role)}
                            disabled={u.id === currentUser?.id}
                            className="border rounded px-2 py-1 text-sm"
                          >
                            <option value="staff">Staff</option>
                            <option value="manager">Manager</option>
                            <option value="admin">Admin</option>
                          </select>
                        </td>
                        <td className="px-4 py-3">
                          <select
                            value={editActive ? 'active' : 'inactive'}
                            onChange={(e) => setEditActive(e.target.value === 'active')}
                            disabled={u.id === currentUser?.id}
                            className="border rounded px-2 py-1 text-sm"
                          >
                            <option value="active">Active</option>
                            <option value="inactive">Inactive</option>
                          </select>
                        </td>
                        <td className="px-4 py-3">
                          <input
                            type="password"
                            placeholder="New password (optional)"
                            value={editPassword}
                            onChange={(e) => setEditPassword(e.target.value)}
                            className="border rounded px-2 py-1 text-sm w-44"
                          />
                        </td>
                        <td className="px-4 py-3 flex gap-2">
                          <button
                            onClick={() => saveEdit(u.id)}
                            disabled={saving}
                            className="text-green-600 hover:underline text-xs font-medium"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setEditingId(null)}
                            className="text-gray-400 hover:underline text-xs"
                          >
                            Cancel
                          </button>
                        </td>
                      </>
                    ) : (
                      /* ── View row ── */
                      <>
                        <td className="px-4 py-3 font-medium text-gray-800">
                          {u.email}
                          {u.id === currentUser?.id && (
                            <span className="ml-2 text-xs text-gray-400">(you)</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_COLORS[u.role]}`}>
                            {ROLE_LABELS[u.role]}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs font-medium ${u.is_active ? 'text-green-600' : 'text-gray-400'}`}>
                            {u.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-500 text-xs">
                          {new Date(u.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3 flex gap-3 justify-end">
                          <button
                            onClick={() => startEdit(u)}
                            className="text-blue-600 hover:underline text-xs font-medium"
                          >
                            Edit
                          </button>
                          {u.id !== currentUser?.id && (
                            <button
                              onClick={() => handleDelete(u.id, u.email)}
                              className="text-red-400 hover:text-red-600 text-xs font-medium"
                            >
                              Delete
                            </button>
                          )}
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
