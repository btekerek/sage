/**
 * ReplayPage — deterministic time-travel viewer.
 *
 * The manager picks any past moment with the datetime picker and the system
 * rebuilds the complete state (products, stock, prices, categories) from the
 * raw event log — no live read models involved.
 */

import { useEffect, useRef, useState } from 'react'
import client from '../api/client'

// ── Types ──────────────────────────────────────────────────────────────────

interface Bounds {
  first_event_at: string | null
  last_event_at: string | null
  total_events: number
}

interface ProductItem {
  id: string
  name: string
  category_id: string
  category_name: string | null
  base_price: number
  current_price: number
  stock: number
}

interface TimelineEntry {
  occurred_at: string
  event_type: string
  aggregate_type: string
  aggregate_id: string
  summary: string
}

interface Snapshot {
  as_of: string
  categories: { id: string; name: string }[]
  products: ProductItem[]
  event_timeline: TimelineEntry[]
  events_replayed: number
  first_event_at: string | null
  last_event_at: string | null
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function isoToLocal(iso: string): string {
  // Convert ISO-8601 to datetime-local input format (YYYY-MM-DDTHH:mm)
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatTs(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('hu-HU', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const EVENT_COLOUR: Record<string, string> = {
  ProductCreatedEvent:           'bg-blue-100 text-blue-700',
  PriceOverrideEvent:            'bg-purple-100 text-purple-700',
  CategoryCreatedEvent:          'bg-gray-100 text-gray-600',
  InventoryLayerCreatedEvent:    'bg-green-100 text-green-700',
  InventoryIntakeEvent:          'bg-emerald-100 text-emerald-700',
  SaleEvent:                     'bg-orange-100 text-orange-700',
  VoidEvent:                     'bg-red-100 text-red-600',
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ReplayPage() {
  const [bounds, setBounds] = useState<Bounds | null>(null)
  const [pickedAt, setPickedAt] = useState<string>('')          // datetime-local value
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [rangePos, setRangePos] = useState(100)                 // 0–100 slider position
  const didInit = useRef(false)

  // Load bounds on mount so we can initialise the picker
  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    client.get('/api/replay/bounds').then(r => {
      const b: Bounds = r.data
      setBounds(b)
      // Default the picker to the latest event
      if (b.last_event_at) setPickedAt(isoToLocal(b.last_event_at))
    }).catch(() => {})
  }, [])

  // Keep picker in sync when slider moves
  function handleSlider(pos: number) {
    setRangePos(pos)
    if (!bounds?.first_event_at || !bounds?.last_event_at) return
    const t0 = new Date(bounds.first_event_at).getTime()
    const t1 = new Date(bounds.last_event_at).getTime()
    const t = t0 + (t1 - t0) * (pos / 100)
    setPickedAt(isoToLocal(new Date(t).toISOString()))
  }

  // Keep slider in sync when picker changes manually
  function handlePickerChange(val: string) {
    setPickedAt(val)
    if (!bounds?.first_event_at || !bounds?.last_event_at) return
    const t0 = new Date(bounds.first_event_at).getTime()
    const t1 = new Date(bounds.last_event_at).getTime()
    const t = new Date(val).getTime()
    setRangePos(Math.max(0, Math.min(100, ((t - t0) / (t1 - t0)) * 100)))
  }

  async function handleLoad() {
    if (!pickedAt) return
    setLoading(true)
    setError(null)
    try {
      const iso = new Date(pickedAt).toISOString()
      const r = await client.get(`/api/replay/snapshot?as_of=${encodeURIComponent(iso)}`)
      setSnapshot(r.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Failed to load snapshot')
    } finally {
      setLoading(false)
    }
  }

  const filteredProducts = (snapshot?.products ?? []).filter(p =>
    !search || p.name.toLowerCase().includes(search.toLowerCase()) ||
    (p.category_name ?? '').toLowerCase().includes(search.toLowerCase())
  )

  // Group filtered products by category for the table
  const grouped: Record<string, ProductItem[]> = {}
  for (const p of filteredProducts) {
    const key = p.category_name ?? 'Uncategorised'
    ;(grouped[key] = grouped[key] ?? []).push(p)
  }

  return (
    <div className="flex flex-col h-full">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="bg-white border-b px-6 py-4">
        <div className="max-w-7xl mx-auto">
          <h1 className="text-xl font-bold text-gray-900 mb-1">
            System Replay
          </h1>
          <p className="text-sm text-gray-500 mb-4">
            Reconstruct the exact state of every product, price, and stock level at any past moment —
            replayed deterministically from the raw event log.
          </p>

          {/* Slider */}
          {bounds?.first_event_at && bounds?.last_event_at && (
            <div className="mb-3">
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>{formatTs(bounds.first_event_at)}</span>
                <span className="font-medium text-gray-600">
                  {bounds.total_events.toLocaleString()} events in log
                </span>
                <span>{formatTs(bounds.last_event_at)}</span>
              </div>
              <input
                type="range" min={0} max={100} step={0.1}
                value={rangePos}
                onChange={e => handleSlider(Number(e.target.value))}
                className="w-full accent-indigo-600"
              />
            </div>
          )}

          {/* Picker row */}
          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-sm font-medium text-gray-700 whitespace-nowrap">
              View state as of:
            </label>
            <input
              type="datetime-local"
              value={pickedAt}
              onChange={e => handlePickerChange(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <button
              onClick={handleLoad}
              disabled={loading || !pickedAt}
              className="bg-indigo-600 text-white px-5 py-1.5 rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? 'Replaying…' : 'Replay'}
            </button>
            {snapshot && (
              <button
                onClick={() => setSnapshot(null)}
                className="text-sm text-gray-500 hover:text-gray-700 underline"
              >
                Clear
              </button>
            )}
          </div>

          {error && (
            <div className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
              ⚠ {error}
            </div>
          )}
        </div>
      </div>

      {/* ── Replay banner ──────────────────────────────────────────────────── */}
      {snapshot && (
        <div className="bg-amber-50 border-b border-amber-200 px-6 py-2 text-sm text-amber-800 font-medium flex items-center gap-3">
          <span className="text-amber-500 text-lg">⏪</span>
          Viewing state as of {formatTs(snapshot.as_of)}
          <span className="text-amber-600 font-normal">
            — {snapshot.events_replayed} event{snapshot.events_replayed !== 1 ? 's' : ''} replayed
            · {snapshot.products.length} product{snapshot.products.length !== 1 ? 's' : ''}
            · {snapshot.categories.length} categor{snapshot.categories.length !== 1 ? 'ies' : 'y'}
          </span>
        </div>
      )}

      {/* ── Empty state ─────────────────────────────────────────────────────── */}
      {!snapshot && !loading && (
        <div className="flex-1 flex items-center justify-center text-gray-400">
          <div className="text-center">
            <div className="text-5xl mb-4">⏳</div>
            <div className="text-lg font-medium">Pick a moment in time</div>
            <div className="text-sm mt-1">Use the slider or date picker above, then press Replay</div>
          </div>
        </div>
      )}

      {/* ── Main content ────────────────────────────────────────────────────── */}
      {snapshot && (
        <div className="flex-1 overflow-hidden flex gap-0 min-h-0">

          {/* ── Left: Products & Stock ───────────────────────────────────────── */}
          <div className="flex-1 flex flex-col min-w-0 border-r overflow-hidden">
            {/* Search */}
            <div className="px-4 py-2 bg-white border-b flex items-center gap-2">
              <input
                type="text"
                placeholder="Search products…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="flex-1 border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
              <span className="text-xs text-gray-400">{filteredProducts.length} products</span>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0 z-10">
                  <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b">
                    <th className="px-4 py-2 font-medium">Product</th>
                    <th className="px-4 py-2 font-medium text-right">Base price</th>
                    <th className="px-4 py-2 font-medium text-right">Price at time</th>
                    <th className="px-4 py-2 font-medium text-right">Stock</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(grouped).map(([cat, items]) => (
                    <>
                      <tr key={`cat-${cat}`} className="bg-gray-50 border-t border-b">
                        <td colSpan={4} className="px-4 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                          {cat}
                        </td>
                      </tr>
                      {items.map(p => {
                        const priceChanged = p.current_price !== p.base_price
                        return (
                          <tr key={p.id} className="border-b hover:bg-gray-50 transition-colors">
                            <td className="px-4 py-2 font-medium text-gray-900">{p.name}</td>
                            <td className="px-4 py-2 text-right font-mono text-gray-500">
                              {p.base_price.toLocaleString('hu-HU')} Ft
                            </td>
                            <td className="px-4 py-2 text-right font-mono">
                              <span className={priceChanged ? 'text-purple-700 font-semibold' : 'text-gray-700'}>
                                {p.current_price.toLocaleString('hu-HU')} Ft
                              </span>
                              {priceChanged && (
                                <span className="ml-1 text-xs text-purple-500">↑</span>
                              )}
                            </td>
                            <td className="px-4 py-2 text-right">
                              <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
                                p.stock === 0
                                  ? 'bg-red-100 text-red-700'
                                  : p.stock <= 5
                                  ? 'bg-yellow-100 text-yellow-700'
                                  : 'bg-green-100 text-green-700'
                              }`}>
                                {p.stock} units
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </>
                  ))}
                  {filteredProducts.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-gray-400">
                        No products matched
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── Right: Event Timeline ────────────────────────────────────────── */}
          <div className="w-96 flex flex-col min-w-0 overflow-hidden bg-white">
            <div className="px-4 py-2 bg-gray-50 border-b">
              <h2 className="text-sm font-semibold text-gray-700">
                Event timeline
                <span className="ml-2 text-xs font-normal text-gray-400">
                  newest first
                </span>
              </h2>
            </div>
            <div className="flex-1 overflow-auto divide-y divide-gray-100">
              {snapshot.event_timeline.map((entry, i) => (
                <div key={i} className="px-4 py-2.5 hover:bg-gray-50">
                  <div className="flex items-start gap-2">
                    <span className={`mt-0.5 shrink-0 text-xs px-1.5 py-0.5 rounded font-medium ${
                      EVENT_COLOUR[entry.event_type] ?? 'bg-gray-100 text-gray-600'
                    }`}>
                      {entry.aggregate_type}
                    </span>
                    <div className="min-w-0">
                      <div className="text-xs text-gray-500 mb-0.5">
                        {formatTs(entry.occurred_at)}
                      </div>
                      <div className="text-sm text-gray-800 break-words">
                        {entry.summary}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
              {snapshot.event_timeline.length === 0 && (
                <div className="px-4 py-8 text-center text-gray-400 text-sm">
                  No events before this time
                </div>
              )}
            </div>
          </div>

        </div>
      )}
    </div>
  )
}
