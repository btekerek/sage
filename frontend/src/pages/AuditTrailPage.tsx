import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'

interface AuditEvent {
  id: number
  event_id: string
  aggregate_type: string
  aggregate_id: string
  event_type: string
  sequence_number: number
  occurred_at_utc: string
  actor_id: string | null
  payload: Record<string, unknown>
}

interface AuditTrailResponse {
  events: AuditEvent[]
  total: number
  page: number
  page_size: number
}

const EVENT_TYPES = [
  '',
  'SaleEvent',
  'VoidEvent',
  'DraftSaleCreatedEvent',
  'LineItemAddedEvent',
  'LineItemRemovedEvent',
  'ProductCreatedEvent',
  'PriceChangedEvent',
  'InventoryLayerCreatedEvent',
  'InvoiceApprovedEvent',
  'ReplenishmentOrderCreatedEvent',
]

const AGGREGATE_TYPES = [
  '',
  'DraftSale',
  'Product',
  'Category',
  'InventoryLayer',
  'Invoice',
  'ReplenishmentOrder',
]

const EVENT_TYPE_COLORS: Record<string, string> = {
  SaleEvent: 'bg-green-100 text-green-800',
  VoidEvent: 'bg-red-100 text-red-800',
  DraftSaleCreatedEvent: 'bg-blue-100 text-blue-800',
  LineItemAddedEvent: 'bg-sky-100 text-sky-800',
  LineItemRemovedEvent: 'bg-orange-100 text-orange-800',
  ProductCreatedEvent: 'bg-purple-100 text-purple-800',
  PriceChangedEvent: 'bg-yellow-100 text-yellow-800',
  InventoryLayerCreatedEvent: 'bg-teal-100 text-teal-800',
  InvoiceApprovedEvent: 'bg-indigo-100 text-indigo-800',
  ReplenishmentOrderCreatedEvent: 'bg-pink-100 text-pink-800',
}

function eventBadgeClass(eventType: string) {
  return EVENT_TYPE_COLORS[eventType] ?? 'bg-gray-100 text-gray-700'
}

function formatDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString()
}

export default function AuditTrailPage() {
  const navigate = useNavigate()
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(25)
  const [filterEventType, setFilterEventType] = useState('')
  const [filterAggregateType, setFilterAggregateType] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchEvents = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize }
      if (filterEventType) params.event_type = filterEventType
      if (filterAggregateType) params.aggregate_type = filterAggregateType
      const res = await client.get<AuditTrailResponse>('/api/events', { params })
      setEvents(res.data.events)
      setTotal(res.data.total)
    } catch {
      // silently fail — table stays empty
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, filterEventType, filterAggregateType])

  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  // reset to page 1 when filters change
  useEffect(() => {
    setPage(1)
  }, [filterEventType, filterAggregateType])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="bg-gray-50">
      {/* Sub-header with page title + refresh */}
      <div className="bg-white border-b px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Audit Trail</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Append-only event store — {total.toLocaleString()} event{total !== 1 ? 's' : ''}
          </p>
        </div>
        <button onClick={fetchEvents} className="text-sm text-blue-600 hover:underline">
          ↻ Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="px-6 py-3 bg-white border-b flex flex-wrap gap-4 items-center">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-gray-600">Event type</label>
          <select
            value={filterEventType}
            onChange={e => setFilterEventType(e.target.value)}
            className="text-sm border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            {EVENT_TYPES.map(t => (
              <option key={t} value={t}>{t || 'All'}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-gray-600">Aggregate</label>
          <select
            value={filterAggregateType}
            onChange={e => setFilterAggregateType(e.target.value)}
            className="text-sm border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            {AGGREGATE_TYPES.map(t => (
              <option key={t} value={t}>{t || 'All'}</option>
            ))}
          </select>
        </div>
        {(filterEventType || filterAggregateType) && (
          <button
            onClick={() => { setFilterEventType(''); setFilterAggregateType('') }}
            className="text-xs text-red-500 hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Table */}
      <div className="px-6 py-4">
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-gray-600 w-8 text-xs" title="Per-aggregate sequence number">Seq</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Event type</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Aggregate</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600 font-mono">Aggregate ID</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Occurred at</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Actor</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600 w-16">Payload</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400">Loading…</td>
                </tr>
              )}
              {!loading && events.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400">No events found</td>
                </tr>
              )}
              {!loading && events.map(ev => (
                <>
                  <tr
                    key={ev.id}
                    className="border-b hover:bg-gray-50 cursor-pointer"
                    onClick={() => setExpandedId(expandedId === ev.id ? null : ev.id)}
                  >
                    <td className="px-4 py-2.5 text-gray-400 font-mono text-xs">{ev.sequence_number}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${eventBadgeClass(ev.event_type)}`}>
                        {ev.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-600">{ev.aggregate_type}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-500" title={ev.aggregate_id}>
                      {ev.aggregate_id.slice(0, 8)}…
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">{formatDate(ev.occurred_at_utc)}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-400">
                      {ev.actor_id ? ev.actor_id.slice(0, 8) + '…' : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <span className="text-gray-400 text-xs">
                        {expandedId === ev.id ? '▲' : '▼'}
                      </span>
                    </td>
                  </tr>
                  {expandedId === ev.id && (
                    <tr key={`${ev.id}-payload`} className="bg-gray-50 border-b">
                      <td colSpan={7} className="px-4 py-3">
                        <div className="text-xs font-mono text-gray-700 bg-gray-100 rounded p-3 overflow-x-auto whitespace-pre">
                          {JSON.stringify(ev.payload, null, 2)}
                        </div>
                        <div className="mt-1 text-xs text-gray-400">
                          event_id: {ev.event_id}
                          {ev.actor_id ? ` · actor: ${ev.actor_id}` : ''}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex justify-between items-center mt-4 text-sm text-gray-600">
          <span>
            Showing {events.length === 0 ? 0 : (page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total.toLocaleString()}
          </span>
          <div className="flex gap-2 items-center">
            <button
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 rounded border hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ← Prev
            </button>
            <span className="px-2">Page {page} of {totalPages}</span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 rounded border hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
