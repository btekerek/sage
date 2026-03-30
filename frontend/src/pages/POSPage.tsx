import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, Product, CartItem } from '../api/client'
import { v4 as uuidv4 } from 'uuid'

export default function POSPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [cart, setCart] = useState<CartItem[]>([])
  const [saleId, setSaleId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    async function init() {
      try {
        const products = await api.getProducts()
        setProducts(products)
        const sale = await api.createDraftSale(uuidv4(), uuidv4())
        setSaleId(sale.aggregate_id)
      } catch (e) {
        setStatus('Failed to connect to backend')
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [])

  async function addToCart(product: Product) {
    if (!saleId) return
    const existing = cart.find(i => i.product.id === product.id)
    const newQty = existing ? existing.quantity + 1 : 1
    try {
      await api.addLineItem(
        saleId,
        product.id,
        product.name,
        product.current_price,
        1,
        999
      )
      setCart(prev => existing
        ? prev.map(i => i.product.id === product.id
            ? { ...i, quantity: newQty }
            : i)
        : [...prev, { product, quantity: 1 }]
      )
    } catch (e) {
      setStatus('Failed to add item')
    }
  }

  function cartTotal() {
    return cart.reduce((sum, i) => sum + i.product.current_price * i.quantity, 0)
  }

  async function finalize(method: 'cash' | 'card') {
    if (!saleId || cart.length === 0) return
    try {
      await api.finalizeSale(saleId, method)
      setStatus(`Sale finalized with ${method}!`)
      setCart([])
      const sale = await api.createDraftSale(uuidv4(), uuidv4())
      setSaleId(sale.aggregate_id)
    } catch (e) {
      setStatus('Failed to finalize sale')
    }
  }

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center">
      <p className="text-gray-500">Loading...</p>
    </div>
  )

  return (
    <div className="min-h-screen flex">
      {/* Product grid */}
      <div className="flex-1 p-6 bg-gray-50">
        <div className="flex justify-between items-center mb-4">
          <h1 className="text-xl font-bold">SAGE POS</h1>
          <button
            onClick={() => navigate('/dashboard')}
            className="text-sm text-blue-600 hover:underline"
          >
            Dashboard →
          </button>
        </div>
        <div className="grid grid-cols-3 gap-4">
          {products.map(product => (
            <button
              key={product.id}
              onClick={() => addToCart(product)}
              className="bg-white rounded-lg p-4 shadow text-left hover:shadow-md transition"
            >
              <p className="font-medium">{product.name}</p>
              <p className="text-blue-600 font-bold mt-1">
                ${Number(product.current_price).toFixed(2)}
              </p>
            </button>
          ))}
        </div>
        {status && (
          <p className="mt-4 text-sm text-green-600">{status}</p>
        )}
      </div>

      {/* Cart panel */}
      <div className="w-80 bg-white shadow-lg flex flex-col">
        <div className="p-4 border-b">
          <h2 className="font-bold text-lg">Cart</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {cart.length === 0 && (
            <p className="text-gray-400 text-sm">No items yet</p>
          )}
          {cart.map(item => (
            <div key={item.product.id} className="flex justify-between items-center">
              <div>
                <p className="text-sm font-medium">{item.product.name}</p>
                <p className="text-xs text-gray-500">x{item.quantity}</p>
              </div>
              <p className="text-sm font-bold">
                ${(Number(item.product.current_price) * item.quantity).toFixed(2)}
              </p>
            </div>
          ))}
        </div>
        <div className="p-4 border-t">
          <div className="flex justify-between mb-4">
            <span className="font-bold">Total</span>
            <span className="font-bold text-lg">${cartTotal().toFixed(2)}</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
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
        </div>
      </div>
    </div>
  )
}