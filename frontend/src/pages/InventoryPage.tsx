import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useAuthStore } from '../store/authStore'

// ── Types ──────────────────────────────────────────────────────────────────

interface InventoryItem {
  product_id: string
  product_name: string
  category_id: string
  category_name: string | null
  base_price: string
  current_price: string
  current_stock: number
  stock_value: string
  last_intake_at: string | null
  last_price_override_at: string | null
}

interface Category {
  id: string
  name: string
}

interface RowEdit {
  name: string
  category_id: string
  price: string
  stock: string
  stock_reason: string
}

// ── Component ──────────────────────────────────────────────────────────────

export default function InventoryPage() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const [items, setItems] = useState<InventoryItem[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Search / filter
  const [search, setSearch] = useState('')
  const [filterCat, setFilterCat] = useState('')
  const [filterStock, setFilterStock] = useState<'all' | 'low' | 'zero'>('all')

  // Row-level edit state: keyed by product_id
  const [edits, setEdits] = useState<Record<string, RowEdit>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [saveMsg, setSaveMsg] = useState<Record<string, string>>({})

  // Add product form
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState('')
  const [newPrice, setNewPrice] = useState('')
  const [newCat, setNewCat] = useState('')
  const [addStatus, setAddStatus] = useState('')

  // ── Data loading ──────────────────────────────────────────────────────

  async function loadData() {
    setLoading(true)
    setError('')
    try {
      const [invRes, catRes] = await Promise.all([
        client.get<InventoryItem[]>('/api/inventory-mgmt/summary'),
        client.get<Category[]>('/api/inventory-mgmt/categories'),
      ])
      setItems(invRes.data)
      setCategories(catRes.data)
    } catch {
      setError('Failed to load inventory. Make sure the backend is running.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData() }, [])

  // ── Filtered view ─────────────────────────────────────────────────────

  const visible = useMemo(() => {
    return items.filter(item => {
      if (search && !item.product_name.toLowerCase().includes(search.toLowerCase())) return false
      if (filterCat && item.category_id !== filterCat) return false
      if (filterStock === 'zero' && item.current_stock !== 0) return false
      if (filterStock === 'low' && item.current_stock >= 10) return false
      return true
    })
  }, [items, search, filterCat, filterStock])

  // ── Stats ─────────────────────────────────────────────────────────────

  const stats = useMemo(() => ({
    totalSKUs: items.length,
    totalUnits: items.reduce((s, i) => s + i.current_stock, 0),
    totalValue: items.reduce((s, i) => s + Number(i.stock_value), 0),
    lowStock: items.filter(i => i.current_stock > 0 && i.current_stock < 10).length,
    zeroStock: items.filter(i => i.current_stock === 0).length,
  }), [items])

  // ── Row edit helpers ──────────────────────────────────────────────────

  function startEdit(item: InventoryItem) {
    setEdits(prev => ({
      ...prev,
      [item.product_id]: {
        name: item.product_name,
        category_id: item.category_id,
        price: item.current_price,
        stock: String(item.current_stock),
        stock_reason: 'Manual stock count correction',
      },
    }))
  }

  function cancelEdit(id: string) {
    setEdits(prev => { const n = { ...prev }; delete n[id]; return n })
    setSaveMsg(prev => { const n = { ...prev }; delete n[id]; return n })
  }

  function updateField(id: string, field: keyof RowEdit, value: string) {
    setEdits(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }))
  }

  async function saveRow(item: InventoryItem) {
    const edit = edits[item.product_id]
    if (!edit) return
    setSaving(prev => ({ ...prev, [item.product_id]: true }))
    setSaveMsg(prev => ({ ...prev, [item.product_id]: '' }))

    try {
      const priceChanged = edit.price !== item.current_price
      const nameChanged = edit.name !== item.product_name
      const catChanged = edit.category_id !== item.category_id
      const stockChanged = Number(edit.stock) !== item.current_stock

      // Product name / price / category update
      if (nameChanged || priceChanged || catChanged) {
        await client.patch(`/api/inventory-mgmt/products/${item.product_id}`, {
          ...(nameChanged ? { name: edit.name } : {}),
          ...(priceChanged ? { price: Number(edit.price) } : {}),
          ...(catChanged ? { category_id: edit.category_id } : {}),
        })
      }

      // Stock adjustment
      if (stockChanged) {
        await client.post('/api/inventory-mgmt/stock-adjustments', {
          product_id: item.product_id,
          new_quantity: Number(edit.stock),
          reason: edit.stock_reason || 'Manual stock count correction',
        })
      }

      setSaveMsg(prev => ({ ...prev, [item.product_id]: '✓ Saved' }))
      await loadData()
      cancelEdit(item.product_id)
    } catch (e: any) {
      setSaveMsg(prev => ({
        ...prev,
        [item.product_id]: e.response?.data?.detail || 'Save failed',
      }))
    } finally {
      setSaving(prev => ({ ...prev, [item.product_id]: false }))
    }
  }

  // ── Add product ───────────────────────────────────────────────────────

  async function handleAddProduct() {
    if (!newName.trim() || !newPrice || !newCat) {
      setAddStatus('Please fill in all fields.')
      return
    }
    setAddStatus('Creating…')
    try {
      await client.post('/api/inventory-mgmt/products', {
        name: newName.trim(),
        unit_price: Number(newPrice),
        category_id: newCat,
      })
      setAddStatus('✓ Product created')
      setNewName(''); setNewPrice(''); setNewCat('')
      setShowAdd(false)
      await loadData()
    } catch (e: any) {
      setAddStatus(e.response?.data?.detail || 'Failed to create product')
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────

  function stockBadge(qty: number) {
    if (qty === 0) return 'bg-red-100 text-red-700'
    if (qty < 10) return 'bg-yellow-100 text-yellow-700'
    return 'bg-green-100 text-green-700'
  }

  function fmt(n: string | number) {
    return Number(n).toLocaleString('hu-HU', { minimumFractionDigits: 2 })
  }

  function fmtDate(d: string | null) {
    if (!d) return '—'
    return new Date(d).toLocaleDateString('hu-HU')
  }

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="bg-gray-50">
      <div className="p-6 max-w-screen-xl mx-auto">

        {/* ── Stats bar ── */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          {[
            { label: 'Total SKUs', value: stats.totalSKUs, color: 'text-gray-800' },
            { label: 'Total units', value: stats.totalUnits.toLocaleString('hu-HU'), color: 'text-blue-600' },
            { label: 'Stock value', value: `${fmt(stats.totalValue)} Ft`, color: 'text-green-700' },
            { label: 'Low stock (< 10)', value: stats.lowStock, color: 'text-yellow-600' },
            { label: 'Out of stock', value: stats.zeroStock, color: 'text-red-600' },
          ].map(s => (
            <div key={s.label} className="bg-white rounded-lg shadow p-4">
              <p className="text-xs text-gray-500 uppercase tracking-wide">{s.label}</p>
              <p className={`text-2xl font-bold mt-1 ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>

        {/* ── Toolbar ── */}
        <div className="bg-white rounded-lg shadow px-4 py-3 mb-4 flex flex-wrap gap-3 items-center justify-between">
          <div className="flex gap-3 items-center flex-wrap">
            <input
              type="text"
              placeholder="Search by product name…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm w-64 focus:outline-none focus:border-blue-400"
            />
            <select
              value={filterCat}
              onChange={e => setFilterCat(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
            >
              <option value="">All categories</option>
              {categories.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <select
              value={filterStock}
              onChange={e => setFilterStock(e.target.value as any)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
            >
              <option value="all">All stock levels</option>
              <option value="low">Low stock (&lt; 10)</option>
              <option value="zero">Out of stock</option>
            </select>
            <span className="text-xs text-gray-400">{visible.length} of {items.length} products</span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => loadData()}
              className="text-sm px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50"
            >
              ↺ Refresh
            </button>
            <button
              onClick={() => setShowAdd(v => !v)}
              className="text-sm px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              + Add product
            </button>
          </div>
        </div>

        {/* ── Add product form ── */}
        {showAdd && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-5 py-4 mb-4 flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-xs text-gray-600 mb-1">Product name *</label>
              <input
                type="text"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm w-56 focus:outline-none focus:border-blue-400"
                placeholder="e.g. 1L Whole Milk"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">Category *</label>
              <select
                value={newCat}
                onChange={e => setNewCat(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
              >
                <option value="">Select…</option>
                {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-600 mb-1">Selling price (Ft) *</label>
              <input
                type="number"
                value={newPrice}
                onChange={e => setNewPrice(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm w-32 focus:outline-none focus:border-blue-400"
                placeholder="0.00"
                min="0"
                step="0.01"
              />
            </div>
            <button
              onClick={handleAddProduct}
              className="px-4 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700"
            >
              Create
            </button>
            <button
              onClick={() => { setShowAdd(false); setAddStatus('') }}
              className="px-4 py-1.5 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
            >
              Cancel
            </button>
            {addStatus && (
              <span className={`text-sm ${addStatus.startsWith('✓') ? 'text-green-600' : 'text-red-600'}`}>
                {addStatus}
              </span>
            )}
          </div>
        )}

        {/* ── Error ── */}
        {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

        {/* ── Main table ── */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          {loading ? (
            <p className="p-8 text-center text-gray-400">Loading inventory…</p>
          ) : visible.length === 0 ? (
            <p className="p-8 text-center text-gray-400">No products match your filters.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b text-xs text-gray-500 uppercase tracking-wide">
                  <tr>
                    <th className="text-left px-4 py-3 min-w-[200px]">Product name</th>
                    <th className="text-left px-4 py-3">Category</th>
                    <th className="text-right px-4 py-3">Base price</th>
                    <th className="text-right px-4 py-3">Selling price</th>
                    <th className="text-right px-4 py-3">Stock (units)</th>
                    <th className="text-right px-4 py-3">Stock value</th>
                    <th className="text-left px-4 py-3">Last intake</th>
                    <th className="text-left px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {visible.map(item => {
                    const edit = edits[item.product_id]
                    const isSaving = saving[item.product_id]
                    const msg = saveMsg[item.product_id]

                    return (
                      <tr
                        key={item.product_id}
                        className={`transition-colors ${edit ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                      >
                        {/* Product name */}
                        <td className="px-4 py-2.5">
                          {edit ? (
                            <input
                              type="text"
                              value={edit.name}
                              onChange={e => updateField(item.product_id, 'name', e.target.value)}
                              className="w-full border border-blue-300 rounded px-2 py-1 text-sm focus:outline-none focus:border-blue-500"
                            />
                          ) : (
                            <span className="font-medium text-gray-800">{item.product_name}</span>
                          )}
                        </td>

                        {/* Category */}
                        <td className="px-4 py-2.5">
                          {edit ? (
                            <select
                              value={edit.category_id}
                              onChange={e => updateField(item.product_id, 'category_id', e.target.value)}
                              className="border border-blue-300 rounded px-2 py-1 text-sm focus:outline-none focus:border-blue-500"
                            >
                              {categories.map(c => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                              ))}
                            </select>
                          ) : (
                            <span className="text-gray-600">{item.category_name ?? '—'}</span>
                          )}
                        </td>

                        {/* Base price */}
                        <td className="px-4 py-2.5 text-right text-gray-400 font-mono text-xs">
                          {fmt(item.base_price)}
                        </td>

                        {/* Selling price */}
                        <td className="px-4 py-2.5 text-right">
                          {edit ? (
                            <input
                              type="number"
                              value={edit.price}
                              onChange={e => updateField(item.product_id, 'price', e.target.value)}
                              step="0.01"
                              className="w-28 border border-blue-300 rounded px-2 py-1 text-sm text-right focus:outline-none focus:border-blue-500"
                            />
                          ) : (
                            <span className="font-medium">{fmt(item.current_price)} Ft</span>
                          )}
                        </td>

                        {/* Stock */}
                        <td className="px-4 py-2.5 text-right">
                          {edit ? (
                            <div className="flex flex-col items-end gap-1">
                              <input
                                type="number"
                                value={edit.stock}
                                onChange={e => updateField(item.product_id, 'stock', e.target.value)}
                                min="0"
                                className="w-20 border border-blue-300 rounded px-2 py-1 text-sm text-right focus:outline-none focus:border-blue-500"
                              />
                              <input
                                type="text"
                                value={edit.stock_reason}
                                onChange={e => updateField(item.product_id, 'stock_reason', e.target.value)}
                                placeholder="Reason for adjustment"
                                className="w-48 border border-gray-200 rounded px-2 py-0.5 text-xs text-gray-500 focus:outline-none focus:border-blue-400"
                              />
                            </div>
                          ) : (
                            <span className={`inline-block px-2 py-0.5 rounded font-bold text-sm ${stockBadge(item.current_stock)}`}>
                              {item.current_stock}
                            </span>
                          )}
                        </td>

                        {/* Stock value */}
                        <td className="px-4 py-2.5 text-right text-gray-600 font-mono text-xs">
                          {fmt(item.stock_value)} Ft
                        </td>

                        {/* Last intake */}
                        <td className="px-4 py-2.5 text-gray-400 text-xs">
                          {fmtDate(item.last_intake_at)}
                        </td>

                        {/* Actions */}
                        <td className="px-4 py-2.5">
                          {edit ? (
                            <div className="flex flex-col gap-1 items-start">
                              <div className="flex gap-1">
                                <button
                                  onClick={() => saveRow(item)}
                                  disabled={isSaving}
                                  className="text-xs bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700 disabled:opacity-50"
                                >
                                  {isSaving ? 'Saving…' : 'Save'}
                                </button>
                                <button
                                  onClick={() => cancelEdit(item.product_id)}
                                  disabled={isSaving}
                                  className="text-xs bg-gray-200 text-gray-700 px-3 py-1 rounded hover:bg-gray-300"
                                >
                                  Cancel
                                </button>
                              </div>
                              {msg && (
                                <span className={`text-xs ${msg.startsWith('✓') ? 'text-green-600' : 'text-red-500'}`}>
                                  {msg}
                                </span>
                              )}
                            </div>
                          ) : (
                            <button
                              onClick={() => startEdit(item)}
                              className="text-xs text-blue-600 hover:underline px-1"
                            >
                              Edit
                            </button>
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

        <p className="text-xs text-gray-400 mt-3 text-center">
          Prices shown in HUF · Stock value = current selling price × units on hand ·
          Click <strong>Edit</strong> on any row to change name, category, price, or stock count
        </p>
      </div>
    </div>
  )
}
