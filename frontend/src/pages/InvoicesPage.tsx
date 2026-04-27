import React, { useCallback, useEffect, useState } from 'react'
import client from '../api/client'

interface LineItem {
  product_name: string
  quantity: number
  unit_price: string
  supplier_ref: string
}

interface Invoice {
  id: string
  supplier_ref: string
  invoice_ref: string
  invoice_date: string | null
  approved_by: string
  approved_at: string
  line_item_count: number
  net_total: number
  line_items_json: string
}

interface InvoiceListResponse {
  invoices: Invoice[]
  total: number
  page: number
  page_size: number
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString()
}

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const pageSize = 25
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const fetchInvoices = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await client.get<InvoiceListResponse>('/api/invoices', {
        params: { page, page_size: pageSize },
      })
      setInvoices(data.invoices)
      setTotal(data.total)
    } catch (e: any) {
      setError(e.response?.data?.detail ?? e.message ?? 'Failed to load invoices')
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => { fetchInvoices() }, [fetchInvoices])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="bg-gray-50 min-h-full">
      {/* Sub-header */}
      <div className="bg-white border-b px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Approved Invoices</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {total.toLocaleString()} invoice{total !== 1 ? 's' : ''} on record
          </p>
        </div>
        <button onClick={fetchInvoices} className="text-sm text-blue-600 hover:underline">
          ↻ Refresh
        </button>
      </div>

      <div className="px-6 py-4">
        <div className="bg-white rounded-lg shadow overflow-hidden">
          {error && (
            <div className="px-4 py-3 bg-red-50 border-b border-red-200 text-red-700 text-sm">
              ⚠ {error}
            </div>
          )}
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Supplier</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Invoice ref</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Invoice date</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Approved at</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">Items</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">Net total</th>
                <th className="px-4 py-3 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400">Loading…</td>
                </tr>
              )}
              {!loading && invoices.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-gray-400">
                    No approved invoices yet. Upload and approve an invoice on the Dashboard.
                  </td>
                </tr>
              )}
              {!loading && invoices.map(inv => {
                const isExpanded = expandedId === inv.id
                let lineItems: LineItem[] = []
                try { lineItems = JSON.parse(inv.line_items_json) } catch { /* ignore */ }

                return (
                  <React.Fragment key={inv.id}>
                    <tr
                      className="border-b hover:bg-gray-50 cursor-pointer"
                      onClick={() => setExpandedId(isExpanded ? null : inv.id)}
                    >
                      <td className="px-4 py-3 font-medium text-gray-800">{inv.supplier_ref}</td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-600">{inv.invoice_ref}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">
                        {inv.invoice_date || '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                        {formatDate(inv.approved_at)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600">{inv.line_item_count}</td>
                      <td className="px-4 py-3 text-right font-bold text-gray-800">
                        {inv.net_total.toLocaleString('hu-HU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3 text-center text-gray-400 text-xs">
                        {isExpanded ? '▲' : '▼'}
                      </td>
                    </tr>

                    {isExpanded && (
                      <tr key={`${inv.id}-detail`} className="bg-gray-50 border-b">
                        <td colSpan={7} className="px-6 py-4">
                          <p className="text-xs text-gray-400 mb-3">
                            Approved by actor <span className="font-mono">{inv.approved_by.slice(0, 8)}…</span>
                          </p>
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-gray-500 border-b">
                                <th className="text-left pb-1">Product</th>
                                <th className="text-right pb-1 w-16">Qty</th>
                                <th className="text-right pb-1 w-24">Unit price</th>
                                <th className="text-right pb-1 w-28">Line total</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                              {lineItems.map((li, i) => (
                                <tr key={i}>
                                  <td className="py-1 text-gray-700">{li.product_name}</td>
                                  <td className="py-1 text-right">{li.quantity}</td>
                                  <td className="py-1 text-right font-mono">
                                    {Number(li.unit_price).toLocaleString('hu-HU', { minimumFractionDigits: 2 })}
                                  </td>
                                  <td className="py-1 text-right font-mono font-medium">
                                    {(Number(li.unit_price) * li.quantity).toLocaleString('hu-HU', { minimumFractionDigits: 2 })}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex justify-between items-center mt-4 text-sm text-gray-600">
          <span>
            {total === 0 ? 'No invoices' : (
              `Showing ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total.toLocaleString()}`
            )}
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
