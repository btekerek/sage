import { useEffect, useRef, useState } from 'react'
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
  const [invoiceResult, setInvoiceResult] = useState<any>(null)
  const [invoiceLoading, setInvoiceLoading] = useState(false)
  const [invoiceError, setInvoiceError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
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

  async function handleInvoiceUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setInvoiceLoading(true)
    setInvoiceError('')
    setInvoiceResult(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const { data } = await client.post('/api/invoices/process', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setInvoiceResult(data)
    } catch (e: any) {
      setInvoiceError(e.response?.data?.detail || 'Failed to process invoice')
    } finally {
      setInvoiceLoading(false)
    }
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

      <div className="p-8 max-w-7xl mx-auto">
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

        {/* Invoice pipeline */}
        <div className="bg-white rounded-lg shadow mb-8">
          <div className="px-6 py-4 border-b flex justify-between items-center">
            <h3 className="font-bold text-lg">AI Invoice Processing</h3>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={invoiceLoading}
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {invoiceLoading ? 'Processing...' : 'Upload Invoice'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.png,.jpg"
              className="hidden"
              onChange={handleInvoiceUpload}
            />
          </div>

          {invoiceError && (
            <p className="px-6 py-4 text-red-500 text-sm">{invoiceError}</p>
          )}

          {!invoiceResult && !invoiceError && (
            <p className="px-6 py-4 text-gray-400 text-sm">
              Upload a supplier invoice PDF to extract line items automatically.
            </p>
          )}

          {invoiceResult && (
            <div className="px-6 py-4">
              {/* Invoice summary */}
              <div className="flex gap-6 mb-4 text-sm flex-wrap">
                <span>
                  <strong>Supplier:</strong> {invoiceResult.header.supplier_name || '—'}
                </span>
                <span>
                  <strong>Ref:</strong> {invoiceResult.header.invoice_ref || '—'}
                </span>
                <span>
                  <strong>Date:</strong> {invoiceResult.header.invoice_date || '—'}
                </span>
                <span>
                  <strong>Confidence:</strong> {(invoiceResult.overall_confidence * 100).toFixed(0)}%
                </span>
                <span className={invoiceResult.requires_review ? 'text-yellow-600 font-medium' : 'text-green-600 font-medium'}>
                  {invoiceResult.requires_review
                    ? `${invoiceResult.flagged_count} items need review`
                    : 'All items auto-accepted'}
                </span>
              </div>

              {/* Footer total banner */}
              {invoiceResult.footer_discrepancy ? (
                <div className="mb-4 px-4 py-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                  ⚠️ Total mismatch: {invoiceResult.footer_discrepancy}
                </div>
              ) : (
                <div className="mb-4 px-4 py-2 bg-green-50 border border-green-200 rounded text-sm text-green-700">
                  ✓ Net total ${Number(invoiceResult.computed_net_total).toLocaleString('en-US', { minimumFractionDigits: 2 })} matches invoice
                </div>
              )}

              {/* Line items table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-500">
                    <tr>
                      <th className="text-left px-4 py-2">Product</th>
                      <th className="text-left px-4 py-2">Qty</th>
                      <th className="text-left px-4 py-2">Pack size</th>
                      <th className="text-left px-4 py-2">Unit price</th>
                      <th className="text-left px-4 py-2">Total</th>
                      <th className="text-left px-4 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {invoiceResult.line_items.map((item: any, i: number) => (
                      <tr
                        key={i}
                        className={item.flags.length > 0 ? 'bg-yellow-50' : ''}
                      >
                        <td className="px-4 py-2">
                          <input
                            type="text"
                            defaultValue={item.product_name}
                            onChange={(e) => { item.product_name = e.target.value }}
                            className="w-full border border-gray-200 rounded px-2 py-1 text-sm focus:border-blue-400 focus:outline-none"
                          />
                        </td>
                        <td className="px-4 py-2">
                          <input
                            type="number"
                            defaultValue={item.quantity}
                            min="1"
                            onChange={(e) => { item.quantity = Number(e.target.value) }}
                            className="w-20 border border-gray-200 rounded px-2 py-1 text-sm focus:border-blue-400 focus:outline-none"
                          />
                        </td>
                        <td className="px-4 py-2">
                          <input
                            type="number"
                            defaultValue={item.packaging_size || 1}
                            min="1"
                            onChange={(e) => { item.packaging_size = Number(e.target.value) }}
                            className="w-16 border border-gray-200 rounded px-2 py-1 text-sm focus:border-blue-400 focus:outline-none"
                          />
                        </td>
                        <td className="px-4 py-2">
                          <input
                            type="number"
                            defaultValue={Number(item.unit_price).toFixed(2)}
                            step="0.01"
                            onChange={(e) => { item.unit_price = e.target.value }}
                            className={`w-28 border rounded px-2 py-1 text-sm focus:outline-none ${
                              item.flags.includes('line_total_mismatch')
                                ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                : 'border-gray-200 focus:border-blue-400'
                            }`}
                          />
                        </td>
                        <td className="px-4 py-2 whitespace-nowrap">
                          ${Number(item.line_total).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </td>
                        <td className="px-4 py-2">
                          {item.flags.length === 0 ? (
                            <span className="text-green-600 text-xs">✓ accepted</span>
                          ) : (
                            <div className="flex flex-col gap-1">
                              {item.flags.includes('line_total_mismatch') && (() => {
                                const pack = item.packaging_size || 1
                                const expected = (Number(item.unit_price) * Number(item.quantity) * pack).toFixed(2)
                                return (
                                  <span className="text-yellow-600 text-xs">
                                    expected ${Number(expected).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                                    {' '}({item.quantity} × {pack} × ${Number(item.unit_price).toFixed(2)})
                                  </span>
                                )
                              })()}
                              {item.flags
                                .filter((f: string) => f !== 'line_total_mismatch')
                                .map((f: string, fi: number) => (
                                  <span key={fi} className="text-yellow-600 text-xs">{f}</span>
                                ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 flex justify-between items-center">
                <span className="text-sm text-gray-500">
                  Computed net total: <strong>${Number(invoiceResult.computed_net_total).toLocaleString('en-US', { minimumFractionDigits: 2 })}</strong>
                </span>
                <button
                  onClick={() => alert('Invoice approved — inventory intake events created')}
                  className="bg-green-600 text-white px-6 py-2 rounded font-medium hover:bg-green-700"
                >
                  Approve Invoice
                </button>
              </div>
            </div>
          )}
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
                {replenishment?.suggestions.map((s) => (
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