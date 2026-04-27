import { useEffect, useMemo, useState } from 'react'
import { api, Product, CartItem } from '../api/client'
import client from '../api/client'
import { v4 as uuidv4 } from 'uuid'

export default function POSPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [cart, setCart] = useState<CartItem[]>([])
  const [saleId, setSaleId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const [statusType, setStatusType] = useState<'success' | 'error' | 'info'>('info')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  async function loadProducts() {
    const fresh = await api.getProducts()
    setProducts(fresh)
  }

  useEffect(() => {
    async function init() {
      try {
        await loadProducts()
        const sale = await api.createDraftSale(uuidv4(), uuidv4())
        setSaleId(sale.aggregate_id)
      } catch {
        showStatus('Failed to connect to backend', 'error')
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [])

  function showStatus(msg: string, type: 'success' | 'error' | 'info' = 'info') {
    setStatus(msg)
    setStatusType(type)
  }

  async function startNewSale() {
    try {
      const sale = await api.createDraftSale(uuidv4(), uuidv4())
      setSaleId(sale.aggregate_id)
      setCart([])
      setStatus('')
    } catch {
      showStatus('Failed to start new sale', 'error')
    }
  }

  async function addToCart(product: Product) {
    if (!saleId) return
const existing = cart.find(i => i.product.id === product.id)
    const newQty = existing ? existing.quantity + 1 : 1
    try {
      await api.addLineItem(
        saleId, product.id, product.name,
        product.current_price, 1,
        product.current_stock   // real available stock
      )
      setCart(prev =>
        existing
          ? prev.map(i => i.product.id === product.id ? { ...i, quantity: newQty } : i)
          : [...prev, { product, quantity: 1 }]
      )
      setStatus('')
    } catch (e: any) {
      showStatus(e.response?.data?.detail || 'Failed to add item', 'error')
    }
  }

  async function removeFromCart(productId: string) {
    if (!saleId) return
    try {
      await client.delete(`/api/draft-sales/${saleId}/items/${productId}`)
      setCart(prev => prev.filter(i => i.product.id !== productId))
    } catch {
      showStatus('Failed to remove item', 'error')
    }
  }

  async function updateQty(productId: string, delta: number) {
    if (!saleId) return
    const item = cart.find(i => i.product.id === productId)
    if (!item) return
    const newQty = item.quantity + delta
    if (newQty <= 0) {
      await removeFromCart(productId)
      return
    }
    try {
      const product = cart.find(i => i.product.id === productId)?.product
      await client.patch(`/api/draft-sales/${saleId}/items/${productId}`, {
        quantity: newQty,
        available_stock: product?.current_stock ?? newQty,
      })
      setCart(prev =>
        prev.map(i => i.product.id === productId ? { ...i, quantity: newQty } : i)
      )
    } catch {
      showStatus('Failed to update quantity', 'error')
    }
  }

  function cartTotal() {
    return cart.reduce((sum, i) => sum + Number(i.product.current_price) * i.quantity, 0)
  }

  async function finalize(method: 'cash' | 'card') {
    if (!saleId || cart.length === 0) return
    try {
      await api.finalizeSale(saleId, method)
      showStatus(`✓ Sale finalized — ${method.toUpperCase()} $${cartTotal().toFixed(2)}`, 'success')
      await startNewSale()
      await loadProducts()
    } catch {
      showStatus('Failed to finalize sale', 'error')
    }
  }

  async function clearCart() {
    if (!saleId) return
    try {
      await client.post(`/api/draft-sales/${saleId}/void`, { reason: '' })
      await startNewSale()
    } catch {
      showStatus('Failed to clear cart', 'error')
    }
  }

  const statusColors = {
    success: 'text-green-600 bg-green-50',
    error: 'text-red-600 bg-red-50',
    info: 'text-gray-600 bg-gray-50',
  }

  // Derive sorted category list from products
  const categories = useMemo(() => {
    const map = new Map<string, { id: string; name: string; total: number; inStock: number }>()
    for (const p of products) {
      const name = p.category_name ?? p.category_id
      if (!map.has(p.category_id)) {
        map.set(p.category_id, { id: p.category_id, name, total: 0, inStock: 0 })
      }
      const cat = map.get(p.category_id)!
      cat.total++
      if (p.current_stock > 0) cat.inStock++
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name))
  }, [products])

  const visibleProducts = selectedCategory
    ? products.filter(p => p.category_id === selectedCategory)
    : []

  if (loading)
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-500">Loading...</p>
      </div>
    )

  return (
    <div className="flex flex-1 overflow-hidden" style={{ height: 'calc(100vh - 49px)' }}>
      {/* ── Left panel: categories or products ─────────────────────── */}
      <div className="flex-1 bg-gray-50 flex flex-col overflow-hidden">

        {/* Breadcrumb / back bar */}
        <div className="px-4 py-2 bg-white border-b flex items-center gap-3 flex-shrink-0">
          {selectedCategory ? (
            <>
              <button
                onClick={() => setSelectedCategory(null)}
                className="text-blue-600 hover:text-blue-800 text-sm font-medium"
              >
                ← Categories
              </button>
              <span className="text-gray-300">/</span>
              <span className="text-sm font-semibold text-gray-800">
                {categories.find(c => c.id === selectedCategory)?.name}
              </span>
            </>
          ) : (
            <span className="text-sm font-semibold text-gray-600">Select a category</span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {!selectedCategory ? (
            /* ── Category grid ── */
            <div className="grid grid-cols-3 gap-4">
              {categories.map(cat => {
                const cartUnitsInCat = cart
                  .filter(i => i.product.category_id === cat.id)
                  .reduce((s, i) => s + i.quantity, 0)
                return (
                  <button
                    key={cat.id}
                    onClick={() => setSelectedCategory(cat.id)}
                    className="bg-white rounded-lg p-5 shadow hover:shadow-md text-left transition"
                  >
                    <p className="font-semibold text-base">{cat.name}</p>
                    <p className="text-xs text-gray-400 mt-1">{cat.inStock}/{cat.total} items in stock</p>
                    {cartUnitsInCat > 0 && (
                      <span className="mt-2 inline-block text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">
                        {cartUnitsInCat} in cart
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          ) : (
            /* ── Product grid for selected category ── */
            <div className="grid grid-cols-3 gap-4">
              {visibleProducts.map(product => {
                const inCart = cart.find(i => i.product.id === product.id)?.quantity ?? 0
                const remaining = product.current_stock - inCart
                const outOfStock = remaining <= 0
                const lowStock = !outOfStock && remaining < 5
                return (
                  <button
                    key={product.id}
                    onClick={() => !outOfStock && addToCart(product)}
                    disabled={outOfStock}
                    className={`bg-white rounded-lg p-4 shadow text-left transition relative
                      ${outOfStock ? 'opacity-40 cursor-not-allowed grayscale' : 'hover:shadow-md cursor-pointer'}`}
                  >
                    {outOfStock && <div className="absolute inset-0 bg-gray-100 opacity-60 rounded-lg z-10" />}
                    <p className="font-medium text-sm">{product.name}</p>
                    <p className="text-blue-600 font-bold mt-1">
                      {Number(product.current_price).toLocaleString('hu-HU')} Ft
                    </p>
                    {outOfStock && (
                      <span className="absolute top-2 right-2 text-xs bg-gray-200 text-gray-500 px-1.5 py-0.5 rounded z-20">
                        Out of stock
                      </span>
                    )}
                    {lowStock && (
                      <span className="absolute top-2 right-2 text-xs bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded">
                        {remaining} left
                      </span>
                    )}
                    {inCart > 0 && (
                      <span className="absolute bottom-2 right-2 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full font-bold">
                        ×{inCart}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {status && (
          <div className={`mx-4 mb-4 px-4 py-2 rounded text-sm font-medium flex-shrink-0 ${statusColors[statusType]}`}>
            {status}
          </div>
        )}
      </div>

      {/* ── Cart panel ────────────────────────────────────────────────── */}
      <div className="w-80 bg-white shadow-lg flex flex-col">
        <div className="p-4 border-b flex justify-between items-center">
          <h2 className="font-bold text-lg">Cart</h2>
          {saleId && (
            <span className="text-xs text-gray-400 font-mono truncate max-w-[140px]" title={saleId}>
              #{saleId.slice(0, 8)}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {cart.length === 0 && (
            <p className="text-gray-400 text-sm">No items yet</p>
          )}
          {cart.map(item => (
            <div key={item.product.id} className="flex justify-between items-center gap-2">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{item.product.name}</p>
                <p className="text-xs text-gray-400">
                  ${Number(item.product.current_price).toFixed(2)} each
                </p>
              </div>
              {/* Quantity stepper */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => updateQty(item.product.id, -1)}
                  className="w-6 h-6 rounded bg-gray-100 hover:bg-gray-200 text-gray-600 font-bold text-sm flex items-center justify-center"
                >
                  −
                </button>
                <span className="w-6 text-center text-sm font-medium">{item.quantity}</span>
                <button
                  onClick={() => updateQty(item.product.id, +1)}
                  className="w-6 h-6 rounded bg-gray-100 hover:bg-gray-200 text-gray-600 font-bold text-sm flex items-center justify-center"
                >
                  +
                </button>
              </div>
              <p className="text-sm font-bold w-14 text-right">
                ${(Number(item.product.current_price) * item.quantity).toFixed(2)}
              </p>
              <button
                onClick={() => removeFromCart(item.product.id)}
                className="text-red-400 hover:text-red-600 text-sm font-bold"
              >
                ✕
              </button>
            </div>
          ))}
        </div>

        <div className="p-4 border-t">
          <div className="flex justify-between mb-4">
            <span className="font-bold">Total</span>
            <span className="font-bold text-lg">${cartTotal().toFixed(2)}</span>
          </div>

          {/* Finalize buttons */}
          <div className="grid grid-cols-2 gap-2 mb-2">
            <button
              onClick={() => finalize('cash')}
              disabled={cart.length === 0}
              className="bg-green-500 text-white py-2 rounded font-medium hover:bg-green-600 disabled:opacity-40"
            >
              Cash
            </button>
            <button
              onClick={() => finalize('card')}
              disabled={cart.length === 0}
              className="bg-blue-500 text-white py-2 rounded font-medium hover:bg-blue-600 disabled:opacity-40"
            >
              Card
            </button>
          </div>

          {/* Clear cart — only visible when there are items */}
          {cart.length > 0 && (
            <button
              onClick={clearCart}
              className="w-full text-gray-400 hover:text-gray-600 py-1 text-sm"
            >
              Clear cart
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
