import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore } from '../store/authStore'
import InvoiceProcessor from '../components/InvoiceProcessor'
import ReplenishmentSuggestions, { ReplenishmentResult } from '../components/ReplenishmentSuggestions'

// ── Types ──────────────────────────────────────────────────────────────────

interface TxLineItem {
  product_id: string
  product_name: string
  quantity: number
  unit_price: string
  line_total: string
}

interface TxEntry {
  id: number
  event_type: 'SaleEvent' | 'VoidEvent'
  aggregate_id: string
  occurred_at_utc: string
  payload: {
    payment_method?: string
    total_amount?: string
    line_items?: TxLineItem[]
    reason?: string
    operator_id?: string
  }
}

interface KPISummary {
  today_revenue: number
  today_transactions: number
  today_units_sold: number
  total_revenue: number
  total_transactions: number
}

interface MarginSummary {
  portfolio_margin: number
  margin_target: number
  meets_target: boolean
}

export default function DashboardPage() {
  const [kpis, setKpis] = useState<KPISummary | null>(null)
  const [replenishment, setReplenishment] = useState<ReplenishmentResult | null>(null)
  const [margin, setMargin] = useState<MarginSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [replenishRefreshKey, setReplenishRefreshKey] = useState(0)

  // Live transactions feed
  const [transactions, setTransactions] = useState<TxEntry[]>([])
  const [txExpanded, setTxExpanded] = useState<number | null>(null)
  // Map of user id → email for resolving operator_id in transactions
  const [userMap, setUserMap] = useState<Record<string, string>>({})

  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  // ── Data fetching ──────────────────────────────────────────────────────

  useEffect(() => {
    async function fetchData() {
      try {
        const [kpiRes, marginRes, usersRes] = await Promise.all([
          client.get('/api/dashboard/kpis'),
          client.get('/api/dashboard/margin'),
          client.get<{ id: string; email: string; role: string }[]>('/api/users/directory').catch(() => ({ data: [] })),
        ])
        setKpis(kpiRes.data)
        setMargin(marginRes.data)
        const map: Record<string, string> = {}
        for (const u of usersRes.data) map[u.id] = u.email
        setUserMap(map)
      } catch (e) {
        console.error('Failed to fetch dashboard data', e)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  // ── Live transactions feed ─────────────────────────────────────────────

  useEffect(() => {
    // Load recent history first
    client.get<TxEntry[]>('/api/dashboard/recent-sales').then(res => {
      setTransactions(res.data)
    }).catch(() => {})

    // Open SSE stream — EventSource can't send headers so token goes in URL
    const token = useAuthStore.getState().token
    if (!token) return
    const es = new EventSource(
      `http://localhost:8000/api/dashboard/stream?token=${encodeURIComponent(token)}`
    )
    es.onmessage = (e) => {
      try {
        const tx: TxEntry = JSON.parse(e.data)
        // Prepend new transaction and keep KPIs fresh
        setTransactions(prev => [tx, ...prev].slice(0, 100))
        setKpis(prev => {
          if (!prev) return prev
          if (tx.event_type === 'SaleEvent') {
            const amt = Number(tx.payload.total_amount ?? 0)
            const units = (tx.payload.line_items ?? []).reduce(
              (sum, li) => sum + (li.quantity ?? 0), 0
            )
            return {
              ...prev,
              today_revenue: prev.today_revenue + amt,
              today_transactions: prev.today_transactions + 1,
              today_units_sold: prev.today_units_sold + units,
              total_revenue: prev.total_revenue + amt,
              total_transactions: prev.total_transactions + 1,
            }
          }
          return prev
        })
      } catch { /* ignore malformed frames */ }
    }
    es.onerror = () => { /* EventSource auto-reconnects */ }
    return () => es.close()
  }, [])

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div>
      <div className="p-8 max-w-7xl mx-auto">
        <h2 className="text-2xl font-bold mb-6">
          {user?.role === 'admin' ? 'Admin' : 'Manager'} Dashboard
        </h2>

        {/* ── KPI Cards ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Today's Revenue</p>
            <p className="text-2xl font-bold text-green-600 mt-1">
              {loading ? '—' : (kpis?.today_revenue ?? 0).toLocaleString('hu-HU')} Ft
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Today's Sales</p>
            <p className="text-2xl font-bold text-blue-600 mt-1">
              {loading ? '—' : kpis?.today_transactions ?? 0}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Units Sold Today</p>
            <p className="text-2xl font-bold text-indigo-600 mt-1">
              {loading ? '—' : kpis?.today_units_sold ?? 0}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">All-Time Revenue</p>
            <p className="text-2xl font-bold text-gray-700 mt-1">
              {loading ? '—' : (kpis?.total_revenue ?? 0).toLocaleString('hu-HU')} Ft
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Est. Reorder Cost</p>
            <p className="text-2xl font-bold text-purple-600 mt-1">
              {replenishment ? Number(replenishment.total_estimated_cost).toLocaleString('hu-HU') : '—'} Ft
            </p>
          </div>

          {/* Margin card */}
          {(() => {
            const pm = margin?.portfolio_margin ?? null
            const target = margin?.margin_target ?? null
            const meetsTarget = margin?.meets_target ?? false
            const gap = pm != null && target != null ? pm - target : null
            const color = pm == null
              ? 'text-gray-400'
              : meetsTarget
                ? 'text-green-600'
                : gap != null && gap >= -0.05
                  ? 'text-amber-500'
                  : 'text-red-600'
            return (
              <div className="bg-white rounded-lg shadow p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Portfolio Margin</p>
                <p className={`text-2xl font-bold mt-1 ${color}`}>
                  {pm == null ? '—' : `${(pm * 100).toFixed(1)}%`}
                </p>
                {target != null && (
                  <p className="text-xs text-gray-400 mt-0.5">
                    target {(target * 100).toFixed(0)}%
                    {gap != null && (
                      <span className={meetsTarget ? ' text-green-500' : ' text-red-400'}>
                        {' '}{gap >= 0 ? '+' : ''}{(gap * 100).toFixed(1)}pp
                      </span>
                    )}
                  </p>
                )}
              </div>
            )
          })()}
        </div>

        {/* ── Live Transactions Feed ─────────────────────────────────── */}
        <div className="bg-white rounded-lg shadow mb-8">
          <div className="px-6 py-4 border-b flex justify-between items-center">
            <div className="flex items-center gap-3">
              <h3 className="font-bold text-lg">Live Transactions</h3>
              <span className="flex items-center gap-1.5 text-xs text-green-600 font-medium">
                <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse inline-block" />
                Live
              </span>
            </div>
            <span className="text-xs text-gray-400">{transactions.length} transaction(s) shown</span>
          </div>

          {transactions.length === 0 ? (
            <p className="px-6 py-8 text-center text-gray-400 text-sm">
              No transactions yet today. Sales made at the POS will appear here in real time.
            </p>
          ) : (
            <div className="divide-y divide-gray-100 max-h-80 overflow-y-auto">
              {transactions.map(tx => {
                const isSale = tx.event_type === 'SaleEvent'
                const isVoid = tx.event_type === 'VoidEvent'
                const time = new Date(tx.occurred_at_utc).toLocaleTimeString('hu-HU', {
                  hour: '2-digit', minute: '2-digit', second: '2-digit',
                })
                const shortId = tx.aggregate_id.slice(0, 8).toUpperCase()
                const itemsSummary = tx.payload.line_items
                  ?.map(li => `${li.product_name} ×${li.quantity}`)
                  .join(', ') ?? ''
                const isExpanded = txExpanded === tx.id
                const operatorRaw = tx.payload.operator_id ? userMap[tx.payload.operator_id] : null
                const operatorName = operatorRaw
                  ? operatorRaw.split('@')[0]
                  : tx.payload.operator_id
                    ? 'staff' // operator_id exists but not resolved (old sale or directory unavailable)
                    : null

                return (
                  <div
                    key={tx.id}
                    className={`px-6 py-3 cursor-pointer transition-colors ${
                      isVoid ? 'bg-red-50 hover:bg-red-100' : 'hover:bg-gray-50'
                    }`}
                    onClick={() => setTxExpanded(isExpanded ? null : tx.id)}
                  >
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-3">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                          isSale ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                        }`}>
                          {isSale ? 'SALE' : 'VOID'}
                        </span>
                        <span className="font-mono text-xs text-gray-400">{shortId}</span>
                        <span className="text-sm text-gray-700 truncate max-w-xs">{itemsSummary}</span>
                      </div>
                      <div className="flex items-center gap-4 flex-shrink-0">
                        {isSale && (
                          <span className="font-bold text-gray-800">
                            {Number(tx.payload.total_amount).toLocaleString('hu-HU')} Ft
                          </span>
                        )}
                        {isSale && tx.payload.payment_method && (
                          <span className="text-xs px-2 py-0.5 bg-gray-100 rounded text-gray-600">
                            {tx.payload.payment_method}
                          </span>
                        )}
                        {operatorName && (
                          <span className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded font-medium hidden sm:inline-block" title="Cashier">
                            👤 {operatorName}
                          </span>
                        )}
                        <span className="text-xs text-gray-400 w-20 text-right">{time}</span>
                        <span className="text-gray-300 text-xs">{isExpanded ? '▲' : '▼'}</span>
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="mt-3 ml-16">
                        {isSale && tx.payload.line_items && (
                          <table className="text-xs w-full max-w-lg">
                            <thead className="text-gray-400">
                              <tr>
                                <th className="text-left py-0.5">Product</th>
                                <th className="text-right py-0.5 w-12">Qty</th>
                                <th className="text-right py-0.5 w-24">Unit price</th>
                                <th className="text-right py-0.5 w-24">Total</th>
                              </tr>
                            </thead>
                            <tbody>
                              {tx.payload.line_items.map((li, i) => (
                                <tr key={i} className="border-t border-gray-100">
                                  <td className="py-0.5 text-gray-700">{li.product_name}</td>
                                  <td className="py-0.5 text-right">{li.quantity}</td>
                                  <td className="py-0.5 text-right font-mono">
                                    {Number(li.unit_price).toLocaleString('hu-HU')} Ft
                                  </td>
                                  <td className="py-0.5 text-right font-mono font-medium">
                                    {Number(li.line_total).toLocaleString('hu-HU')} Ft
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                        {isVoid && (
                          <p className="text-xs text-red-600 italic">
                            Void reason: {tx.payload.reason || '(no reason given)'}
                          </p>
                        )}
                        {operatorName && (
                          <p className="text-xs text-gray-500 mt-2">
                            Cashier: <span className="font-medium text-gray-700">{operatorName}</span>
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── AI Invoice Processing ───────────────────────────────────── */}
        <InvoiceProcessor
          onApproved={() => setReplenishRefreshKey(k => k + 1)}
        />

        {/* ── Replenishment Suggestions ───────────────────────────────── */}
        <ReplenishmentSuggestions
          refreshKey={replenishRefreshKey}
          onLoad={setReplenishment}
        />
      </div>
    </div>
  )
}
