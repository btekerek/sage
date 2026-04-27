import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore, AuthUser, UserRole } from '../store/authStore'

interface LoginResponse {
  access_token: string
  user_id: string
  email: string
  role: UserRole
}

const ROLE_HOME: Record<UserRole, string> = {
  admin: '/dashboard',
  manager: '/dashboard',
  staff: '/pos',
}

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await client.post<LoginResponse>('/api/auth/login', { email, password })
      const user: AuthUser = { id: data.user_id, email: data.email, role: data.role }
      login(data.access_token, user)
      navigate(ROLE_HOME[data.role] ?? '/pos')
    } catch (err: any) {
      const detail = err.response?.data?.detail
      setError(detail ?? 'Login failed — please check your credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-lg shadow w-full max-w-sm">
        <h1 className="text-3xl font-bold text-center mb-2">SAGE</h1>
        <p className="text-center text-sm text-gray-500 mb-8">
          Sales, Availability &amp; Growth Engine
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Email address
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full border border-gray-300 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Password
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full border border-gray-300 rounded px-3 py-2 pr-10 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-400 hover:text-gray-600"
                tabIndex={-1}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M3.707 2.293a1 1 0 00-1.414 1.414L5.586 7H4a1 1 0 000 2h.586l1.5 1.5A5.001 5.001 0 0010 15a5.001 5.001 0 004.95-4.293L16.414 12.12a1 1 0 001.414-1.414l-14.12-14.12zM10 13a3 3 0 01-2.83-2H10a1 1 0 000-2H7.17A3 3 0 0110 7c.35 0 .687.06 1 .17V5.07A5.001 5.001 0 005 10a5 5 0 005 5 5.001 5.001 0 004.93-4.27l1.363 1.363A5 5 0 0110 13z" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M10 3C5 3 1.73 7.11 1.06 8a1 1 0 000 1.11C1.73 10.11 5 14.22 10 14.22S18.27 10.11 18.94 9.11a1 1 0 000-1.11C18.27 7.11 15 3 10 3zm0 9a3 3 0 110-6 3 3 0 010 6z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white py-2 rounded font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  )
}
