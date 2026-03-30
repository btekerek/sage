import axios from 'axios'

const client = axios.create({
  baseURL: 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface Product {
  id: string
  name: string
  current_price: number
  category_id: string
}

export interface CartItem {
  product: Product
  quantity: number
}

export const api = {
  getProducts: async (): Promise<Product[]> => {
    const { data } = await client.get('/api/products')
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