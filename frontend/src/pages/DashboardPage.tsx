import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'

interface Suggestion {
  product_id: string
  product_name: string
  current_stock: number
  daily_demand: string
  days_of_stock_remaining: string
  suggested_order_quantity: number
  estimated_cost: string
  priority: string
}

interface ReplenishmentResult {
  suggestions: Suggestion[]
  total_estimated_cost: string
  budget_used: string
  budget_remaining: string
  feasible: boolean
  solver_status: string
}

export default function DashboardPage() {
  const [replenishment, setReplenishment] = useState<ReplenishmentResult | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    async function fetchData() {
      try {
        const { data } = await client.get('/api/replenishment/suggestions')
        setReplenishment(data)
      } catch (e) {
        console.error('Failed to fetch replenishment data', e)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  function priorityColor(priority: string) {
    if (priority === 'critical') return 'bg-red-100 text-red-800'
    if (priority === 'low') return 'bg-yellow-100 text-yellow-800'
    return 'bg-green-100 text-green-800'
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow px-6 py-4 flex justify-between items-center">
        <h1 className="text-xl font-bold">SAGE</h1>
        <button
          onClick={() => navigate('/pos')}
          className="text-sm bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
        >
          Open POS
        </button>
      </nav>

      <div className="p-8 max-w-6xl mx-auto">
        <h2 className="text-2xl font-bold mb-6">Management Dashboard</h2>

        {/* KPI cards */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Budget remaining</p>
            <p className="text-2xl font-bold text-green-600">
              ${replenishment ? Number(replenishment.budget_remaining).toFixed(2) : '—'}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Estimated reorder cost</p>
            <p className="text-2xl font-bold text-blue-600">
              ${replenishment ? Number(replenishment.total_estimated_cost).toFixed(2) : '—'}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm text-gray-500">Solver status</p>
            <p className="text-2xl font-bold text-gray-700">
              {replenishment ? replenishment.solver_status : '—'}
            </p>
          </div>
        </div>

        {/* Replenishment table */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-6 py-4 border-b">
            <h3 className="font-bold text-lg">Replenishment Suggestions</h3>
          </div>
          {loading ? (
            <p className="p-6 text-gray-400">Loading...</p>
          ) : replenishment?.suggestions.length === 0 ? (
            <p className="p-6 text-gray-400">No replenishment needed.</p>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50 text-sm text-gray-500">
                <tr>
                  <th className="text-left px-6 py-3">Product</th>
                  <th className="text-left px-6 py-3">Stock</th>
                  <th className="text-left px-6 py-3">Daily demand</th>
                  <th className="text-left px-6 py-3">Days remaining</th>
                  <th className="text-left px-6 py-3">Order qty</th>
                  <th className="text-left px-6 py-3">Cost</th>
                  <th className="text-left px-6 py-3">Priority</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {replenishment?.suggestions.map(s => (
                  <tr key={s.product_id}>
                    <td className="px-6 py-4 font-medium">{s.product_name}</td>
                    <td className="px-6 py-4">{s.current_stock}</td>
                    <td className="px-6 py-4">{s.daily_demand}</td>
                    <td className="px-6 py-4">{s.days_of_stock_remaining}</td>
                    <td className="px-6 py-4 font-bold">{s.suggested_order_quantity}</td>
                    <td className="px-6 py-4">${Number(s.estimated_cost).toFixed(2)}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${priorityColor(s.priority)}`}>
                        {s.priority}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}