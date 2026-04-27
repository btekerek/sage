import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const client = axios.create({
  baseURL: 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Attach JWT on every request
client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// On 401, clear auth and redirect to login
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export interface Product {
  id: string
  name: string
  current_price: number
  category_id: string
  category_name: string | null
  current_stock: number   // live stock count from inventory_layer_read
}

export interface CartItem {
  product: Product
  quantity: number
}

export const api = {
  getProducts: async (): Promise<Product[]> => {
    const { data } = await client.get('/api/products/pos-catalog')
    return data
  },

  createDraftSale: async (operatorId: string, sessionId: string) => {
    const { data } = await client.post('/api/draft-sales', {
      operator_id: operatorId,
      session_id: sessionId,
    })
    return data
  },

  addLineItem: async (
    saleId: string,
    productId: string,
    productName: string,
    unitPrice: number,
    quantity: number,
    availableStock: number
  ) => {
    const { data } = await client.post(`/api/draft-sales/${saleId}/items`, {
      product_id: productId,
      product_name: productName,
      unit_price: unitPrice,
      quantity: quantity,
      available_stock: availableStock,
    })
    return data
  },

  finalizeSale: async (saleId: string, paymentMethod: string) => {
    const { data } = await client.post(`/api/draft-sales/${saleId}/finalize`, {
      payment_method: paymentMethod,
    })
    return data
  },
}

export default client