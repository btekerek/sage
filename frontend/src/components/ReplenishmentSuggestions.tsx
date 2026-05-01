/**
 * ReplenishmentSuggestions — self-contained replenishment panel.
 *
 * Props:
 *   refreshKey?  — increment this from the parent to trigger a re-fetch
 *                  (e.g. after an invoice is approved)
 *   onLoad?      — called with the raw result after each successful fetch,
 *                  so parents can read total_estimated_cost for their own KPI cards
 */
import { useEffect, useState } from 'react'
import { v4 as uuidv4 } from 'uuid'
import client from '../api/client'

// ── Types ──────────────────────────────────────────────────────────────────

interface Suggestion {
  product_id: string
  product_name: string
  current_stock: number
  daily_demand: string
  days_of_stock_remaining: string
  suggested_order_quantity: number
  estimated_cost: string
  priority: string
  coverage_fraction: string
}

export interface ReplenishmentResult {
  suggestions: Suggestion[]
  total_estimated_cost: string
  feasible: boolean
  solver_status: string
  budget: string
  budget_used: string
  budget_constrained: boolean
}

// ── Helpers ────────────────────────────────────────────────────────────────

function priorityColor(priority: string) {
  if (priority === 'critical') return 'bg-red-100 text-red-800'
  if (priority === 'low') return 'bg-yellow-100 text-yellow-800'
  return 'bg-green-100 text-green-800'
}

function CoverageBar({ fraction }: { fraction: number }) {
  const pct = Math.round(fraction * 100)
  const color = pct >= 100 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-400' : 'bg-red-500'
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="text-xs text-gray-600 tabular-nums">{pct}%</span>
    </div>
  )
}

function BudgetBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0
  const color = pct >= 95 ? 'bg-red-500' : pct >= 75 ? 'bg-yellow-400' : 'bg-blue-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-32 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 tabular-nums">
        {used.toLocaleString('hu-HU')} / {total.toLocaleString('hu-HU')} Ft
        <span className="ml-1 text-gray-400">({Math.round(pct)}%)</span>
      </span>
    </div>
  )
}

// ── Component ──────────────────────────────────────────────────────────────

interface Props {
  refreshKey?: number
  onLoad?: (data: ReplenishmentResult) => void
}

export default function ReplenishmentSuggestions({ refreshKey = 0, onLoad }: Props) {
  const [result, setResult] = useState<ReplenishmentResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [acceptedRows, setAcceptedRows] = useState<Set<string>>(new Set())
  const [dismissedRows, setDismissedRows] = useState<Set<string>>(new Set())
  const [statusMsg, setStatusMsg] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    client.get<ReplenishmentResult>('/api/replenishment/suggestions')
      .then(res => {
        if (cancelled) return
        setResult(res.data)
        onLoad?.(res.data)
        setAcceptedRows(new Set())
        setDismissedRows(new Set())
        setStatusMsg('')
      })
      .catch(() => {
        if (!cancelled) setResult(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  async function handleAccept(s: Suggestion) {
    try {
      await client.post('/api/replenishment/accept', {
        orders: [{ product_id: s.product_id, quantity: s.suggested_order_quantity }],
        approved_by: uuidv4(),
      })
      setAcceptedRows(prev => new Set([...prev, s.product_id]))
      setStatusMsg(`✓ Purchase order accepted for ${s.product_name}`)
    } catch {
      setStatusMsg(`Failed to accept order for ${s.product_name}`)
    }
  }

  function handleDismiss(s: Suggestion) {
    setDismissedRows(prev => new Set([...prev, s.product_id]))
    setStatusMsg(`Dismissed suggestion for ${s.product_name}`)
  }

  const visible = result?.suggestions.filter(s => !dismissedRows.has(s.product_id)) ?? []
  const budgetUsed = result ? Number(result.budget_used) : 0
  const budget = result ? Number(result.budget) : 0

  return (
    <div className="bg-white rounded-lg shadow mb-6">

      {/* ── Header ── */}
      <div className="px-6 py-4 border-b">
        <div className="flex justify-between items-start flex-wrap gap-2">
          <div>
            <h3 className="font-bold text-lg">Replenishment Suggestions</h3>
            {result && (
              <p className="text-xs text-gray-400 mt-0.5">
                Solver: <span className="font-medium text-gray-600">{result.solver_status}</span>
              </p>
            )}
          </div>
          {result && (
            <div className="text-right space-y-1">
              <p className="text-sm text-gray-500">
                Est. cost:{' '}
                <span className="font-semibold text-blue-600">
                  {Number(result.total_estimated_cost).toLocaleString('hu-HU')} Ft
                </span>
              </p>
              <BudgetBar used={budgetUsed} total={budget} />
            </div>
          )}
        </div>
      </div>

      {/* ── Budget-constrained warning ── */}
      {result?.budget_constrained && (
        <div className="px-6 py-2 bg-amber-50 border-b border-amber-200 flex items-center gap-2 text-sm text-amber-800">
          <span className="text-base">⚠</span>
          <span>
            <strong>Budget constrained</strong> — some products could not be fully covered within the weekly budget.
            Items below are prioritised by urgency (days of stock remaining).
          </span>
        </div>
      )}

      {/* ── Status toast ── */}
      {statusMsg && (
        <div className={`px-6 py-2 text-sm border-b ${
          statusMsg.startsWith('✓') ? 'bg-green-50 text-green-700' : 'bg-blue-50 text-blue-700'
        }`}>
          {statusMsg}
        </div>
      )}

      {/* ── Table ── */}
      {loading ? (
        <p className="p-6 text-gray-400 text-sm">Loading…</p>
      ) : visible.length === 0 ? (
        <p className="p-6 text-gray-400 text-sm">No replenishment needed.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="text-left px-6 py-3">Product</th>
                <th className="text-right px-6 py-3">Stock</th>
                <th className="text-right px-6 py-3">Daily demand</th>
                <th className="text-right px-6 py-3">Days left</th>
                <th className="text-right px-6 py-3">Order qty</th>
                <th className="text-right px-6 py-3">Est. cost (Ft)</th>
                <th className="text-left px-6 py-3">Coverage</th>
                <th className="text-left px-6 py-3">Priority</th>
                <th className="text-left px-6 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {visible.map(s => {
                const accepted = acceptedRows.has(s.product_id)
                const coverage = Number(s.coverage_fraction)
                return (
                  <tr key={s.product_id} className={accepted ? 'bg-green-50' : 'hover:bg-gray-50'}>
                    <td className="px-6 py-3 font-medium text-gray-800">{s.product_name}</td>
                    <td className="px-6 py-3 text-right">{s.current_stock}</td>
                    <td className="px-6 py-3 text-right font-mono text-xs">{Number(s.daily_demand).toFixed(2)}</td>
                    <td className="px-6 py-3 text-right">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
                        Number(s.days_of_stock_remaining) < 7
                          ? 'bg-red-100 text-red-700'
                          : Number(s.days_of_stock_remaining) < 14
                          ? 'bg-yellow-100 text-yellow-700'
                          : 'bg-green-100 text-green-700'
                      }`}>
                        {Number(s.days_of_stock_remaining).toFixed(1)}d
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right font-bold">{s.suggested_order_quantity}</td>
                    <td className="px-6 py-3 text-right font-mono text-xs">
                      {Number(s.estimated_cost).toLocaleString('hu-HU', { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-6 py-3">
                      <CoverageBar fraction={coverage} />
                    </td>
                    <td className="px-6 py-3">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${priorityColor(s.priority)}`}>
                        {s.priority}
                      </span>
                    </td>
                    <td className="px-6 py-3">
                      {accepted ? (
                        <span className="text-green-600 text-xs font-medium">✓ Order placed</span>
                      ) : (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleAccept(s)}
                            className="text-xs bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700"
                          >
                            Accept
                          </button>
                          <button
                            onClick={() => handleDismiss(s)}
                            className="text-xs bg-gray-200 text-gray-700 px-3 py-1 rounded hover:bg-gray-300"
                          >
                            Dismiss
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
