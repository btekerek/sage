import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { v4 as uuidv4 } from 'uuid'
import { useAuthStore } from '../store/authStore'

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
  }
}

interface KPISummary {
  today_revenue: number
  today_transactions: number
  today_void_count: number
  total_revenue: number
  total_transactions: number
}

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
  const [kpis, setKpis] = useState<KPISummary | null>(null)
  const [replenishment, setReplenishment] = useState<ReplenishmentResult | null>(null)
  const [loading, setLoading] = useState(true)

  const [invoiceResult, setInvoiceResult] = useState<any>(null)
  const [invoiceFileUrl, setInvoiceFileUrl] = useState<string | null>(null)
  const [invoiceIsImage, setInvoiceIsImage] = useState(false)
  const [invoiceLoading, setInvoiceLoading] = useState(false)
  const [invoiceError, setInvoiceError] = useState('')
  const [approveStatus, setApproveStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')

  const [acceptedRows, setAcceptedRows] = useState<Set<string>>(new Set())
  const [dismissedRows, setDismissedRows] = useState<Set<string>>(new Set())
  const [replenishStatus, setReplenishStatus] = useState('')
  const [loadingPhrase, setLoadingPhrase] = useState(0)

  // Live transactions feed
  const [transactions, setTransactions] = useState<TxEntry[]>([])
  const [txExpanded, setTxExpanded] = useState<number | null>(null)

  // PDF viewer state
  const [pdfPage, setPdfPage] = useState(1)
  const [pdfTotalPages, setPdfTotalPages] = useState(0)
  const [pdfjsReady, setPdfjsReady] = useState(false)
  const [highlightedRow, setHighlightedRow] = useState<number | null>(null)
  const [pdfHighlight, setPdfHighlight] = useState<{ page: number; y: number; h: number } | null>(null)
  // Increments every time a new document is loaded — forces the render effect
  // to re-fire even when pdfPage stays at 1 across uploads.
  const [pdfDocVersion, setPdfDocVersion] = useState(0)
  // CSS-transform based zoom + pan (canvas always renders at fit-scale)
  const [viewZoom, setViewZoom] = useState(1.0)
  const [viewPan, setViewPan] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragStartRef = useRef({ mouseX: 0, mouseY: 0, panX: 0, panY: 0 })

  const fileInputRef = useRef<HTMLInputElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const overlayRef = useRef<HTMLCanvasElement>(null)
  const pdfContainerRef = useRef<HTMLDivElement>(null)
  const pdfDocRef = useRef<any>(null)
  const renderTaskRef = useRef<any>(null)

  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  // ── Data fetching ──────────────────────────────────────────────────────

  useEffect(() => {
    async function fetchData() {
      try {
        const [kpiRes, repRes] = await Promise.all([
          client.get('/api/dashboard/kpis'),
          client.get('/api/replenishment/suggestions'),
        ])
        setKpis(kpiRes.data)
        setReplenishment(repRes.data)
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
            return {
              ...prev,
              today_revenue: prev.today_revenue + amt,
              today_transactions: prev.today_transactions + 1,
              total_revenue: prev.total_revenue + amt,
              total_transactions: prev.total_transactions + 1,
            }
          }
          if (tx.event_type === 'VoidEvent') {
            return { ...prev, today_void_count: prev.today_void_count + 1 }
          }
          return prev
        })
      } catch { /* ignore malformed frames */ }
    }
    es.onerror = () => { /* EventSource auto-reconnects */ }
    return () => es.close()
  }, [])

  // ── PDF.js: load library once ──────────────────────────────────────────

  useEffect(() => {
    const win = window as any
    if (win.pdfjsLib) {
      setPdfjsReady(true)
      return
    }
    const script = document.createElement('script')
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'
    script.onload = () => {
      win.pdfjsLib.GlobalWorkerOptions.workerSrc =
        'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
      setPdfjsReady(true)
    }
    document.head.appendChild(script)
  }, [])

  // ── PDF.js: load document when URL changes ─────────────────────────────

  useEffect(() => {
    if (!pdfjsReady || !invoiceFileUrl) return
    const pdfjsLib = (window as any).pdfjsLib
    pdfjsLib.getDocument(invoiceFileUrl).promise.then((doc: any) => {
      pdfDocRef.current = doc
      setPdfTotalPages(doc.numPages)
      setPdfPage(1)
      setViewZoom(1.0)
      setViewPan({ x: 0, y: 0 })
      setPdfHighlight(null)
      setHighlightedRow(null)
      setPdfDocVersion(v => v + 1)   // always triggers the render effect
    })
  }, [pdfjsReady, invoiceFileUrl])

  // ── PDF.js: re-render when invoiceResult arrives (canvas just mounted) ─
  // The PDF can finish loading before the API returns, at which point
  // canvasRef.current is still null (the canvas lives inside {invoiceResult && …}).
  // This effect fires when invoiceResult is finally set — if pdfDocRef is
  // already populated we bump pdfDocVersion to kick off the render now that
  // the canvas is actually in the DOM.
  useEffect(() => {
    if (invoiceResult && pdfDocRef.current) {
      setPdfDocVersion(v => v + 1)
    }
  }, [invoiceResult])

  // ── PDF.js: render current page + highlight overlay ────────────────────

  useEffect(() => {
    async function renderPage() {
      if (!pdfDocRef.current || !canvasRef.current || !overlayRef.current) return

      if (renderTaskRef.current) {
        try { renderTaskRef.current.cancel() } catch { /* ignore */ }
        renderTaskRef.current = null
      }

      const page = await pdfDocRef.current.getPage(pdfPage)

      // Wait one animation frame so the browser has finished layout before
      // we read clientWidth — without this the first render fires when the
      // container hasn't been painted yet (clientWidth === 0) and fitScale
      // becomes negative, producing a blank canvas.
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))

      // Fit to container width — zoom is handled via CSS transform, not re-render
      const containerWidth = pdfContainerRef.current?.clientWidth || 480
      const baseViewport = page.getViewport({ scale: 1 })
      const fitScale = (containerWidth - 16) / baseViewport.width
      const viewport = page.getViewport({ scale: fitScale })

      const canvas = canvasRef.current
      canvas.width = viewport.width
      canvas.height = viewport.height

      const overlay = overlayRef.current
      overlay.width = viewport.width
      overlay.height = viewport.height

      const ctx = canvas.getContext('2d')!
      const task = page.render({ canvasContext: ctx, viewport })
      renderTaskRef.current = task

      try {
        await task.promise
      } catch {
        return // render was cancelled — bail silently
      }
      renderTaskRef.current = null

      const overlayCtx = overlay.getContext('2d')!
      overlayCtx.clearRect(0, 0, overlay.width, overlay.height)

      if (pdfHighlight && pdfHighlight.page === pdfPage) {
        // PDF Y coords are bottom-up; convertToViewportPoint converts to canvas coords
        const [, canvasYBottom] = viewport.convertToViewportPoint(0, pdfHighlight.y)
        const [, canvasYTop] = viewport.convertToViewportPoint(0, pdfHighlight.y + pdfHighlight.h)
        const rectY = Math.min(canvasYBottom, canvasYTop) - 4
        const rectH = Math.abs(canvasYBottom - canvasYTop) + 8
        overlayCtx.fillStyle = 'rgba(255, 215, 0, 0.45)'
        overlayCtx.fillRect(0, rectY, overlay.width, rectH)
        overlayCtx.strokeStyle = 'rgba(200, 130, 0, 0.85)'
        overlayCtx.lineWidth = 2
        overlayCtx.strokeRect(0, rectY, overlay.width, rectH)
      }
    }

    renderPage()
  }, [pdfPage, pdfHighlight, pdfDocVersion])

  // ── PDF viewer: scroll-to-zoom ────────────────────────────────────────
  // Attached once to window on mount — checks the ref at event time so
  // conditional rendering of the container never causes a timing issue.

  useEffect(() => {
    const handleWheel = (e: WheelEvent) => {
      const el = pdfContainerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const isOver = e.clientX >= rect.left && e.clientX <= rect.right
                  && e.clientY >= rect.top  && e.clientY <= rect.bottom
      if (!isOver) return
      if (e.ctrlKey) return          // let browser handle Ctrl+scroll page zoom
      e.preventDefault()             // stop the page scrolling under the invoice
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
      setViewZoom(z => {
        const newZoom = Math.min(6, Math.max(0.3, z * factor))
        setViewPan(p => ({
          x: mouseX - (mouseX - p.x) * (newZoom / z),
          y: mouseY - (mouseY - p.y) * (newZoom / z),
        }))
        return newZoom
      })
    }
    window.addEventListener('wheel', handleWheel, { passive: false })
    return () => window.removeEventListener('wheel', handleWheel)
  }, [])

  // ── Invoice loading phrases ────────────────────────────────────────────

  const _LOADING_PHRASES = [
    'Rendering invoice pages…',
    'Sending to Claude Vision…',
    'Reading product names…',
    'Extracting quantities and prices…',
    'Identifying ÁFA rates…',
    'Calculating brutto totals…',
    'Validating line item math…',
    'Checking footer totals…',
    'Routing flagged items…',
    'Almost done…',
  ]

  useEffect(() => {
    if (!invoiceLoading) return
    setLoadingPhrase(0)
    const id = setInterval(() => {
      setLoadingPhrase(p => Math.min(p + 1, _LOADING_PHRASES.length - 1))
    }, 2200)
    return () => clearInterval(id)
  }, [invoiceLoading])

  // ── Invoice pipeline ───────────────────────────────────────────────────

  async function handleInvoiceUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setInvoiceLoading(true)
    setInvoiceError('')
    setInvoiceResult(null)
    setApproveStatus('idle')
    if (invoiceFileUrl) URL.revokeObjectURL(invoiceFileUrl)
    const isImage = file.type.startsWith('image/')
    setInvoiceIsImage(isImage)
    setInvoiceFileUrl(URL.createObjectURL(file))
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
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleApproveInvoice() {
    if (!invoiceResult) return
    setApproveStatus('loading')
    try {
      const payload = {
        supplier_ref: invoiceResult.header.supplier_name || 'UNKNOWN',
        invoice_ref: invoiceResult.header.invoice_ref || `INV-${Date.now()}`,
        invoice_date: invoiceResult.header.invoice_date || null,
        approved_by: uuidv4(),
        line_items: invoiceResult.line_items.map((item: any) => ({
          product_name: item.product_name,
          quantity: Number(item.quantity),
          unit_price: Number(item.unit_price),
          supplier_ref: invoiceResult.header.supplier_name || 'UNKNOWN',
          cikkszam: item.cikkszam || '',
          packaging_size: Number(item.packaging_size) || 1,
          line_total: Number(item.line_total) || 0,
        })),
      }
      await client.post('/api/invoices/approve', payload)
      setApproveStatus('success')
      const { data } = await client.get('/api/replenishment/suggestions')
      setReplenishment(data)
    } catch (e: any) {
      console.error(e)
      setApproveStatus('error')
    }
  }

  // ── PDF row click — find text + highlight ──────────────────────────────

  async function handleRowClick(item: any, rowIndex: number) {
    // Toggle off if same row clicked again
    if (highlightedRow === rowIndex) {
      setHighlightedRow(null)
      setPdfHighlight(null)
      return
    }
    setHighlightedRow(rowIndex)

    // For image invoices PDF.js has no document — just mark the row selected
    if (!pdfDocRef.current) return

    // ── Primary: use Claude's y_fraction to highlight directly ─────────────
    // Claude reported where on the page this row sits (0.0 = top, 1.0 = bottom)
    // while it was already looking at the image — no text layer needed.
    const targetPage: number = item.source_page ?? 1

    // Only use y_fraction when the API actually returned it (not the 0.5 default
    // for items processed before this field existed).
    if (item.y_fraction != null) {
      const yFraction = item.y_fraction as number
      const doc = pdfDocRef.current
      const page = await doc.getPage(targetPage)
      // At scale:1, viewport.height is the page height in PDF points (no viewBox needed)
      const baseVp = page.getViewport({ scale: 1 })
      const pageHeightPt = baseVp.height
      // PDF Y=0 is at the bottom; y_fraction 0=top → pdfY = pageHeightPt
      const rowHeightPt = Math.max(pageHeightPt * 0.03, 18)   // at least 18pt tall
      const pdfY = pageHeightPt * (1 - yFraction) - rowHeightPt / 2

      setPdfPage(targetPage)
      setPdfHighlight({ page: targetPage, y: pdfY, h: rowHeightPt * 2 })
      return
    }

    // ── Fallback: text-layer search (for re-processed PDFs without y_fraction) ──
    const cikkszam = (item.cikkszam || '').trim()
    const keywords = cikkszam
      ? []
      : (item.product_name || '')
          .split(/\s+/)
          .map((w: string) => w.toLowerCase().trim())
          .filter((w: string) => w.length > 3)

    const doc = pdfDocRef.current
    setPdfPage(targetPage)

    for (let pageNum = 1; pageNum <= doc.numPages; pageNum++) {
      const page = await doc.getPage(pageNum)
      const content = await page.getTextContent()
      const lines: { y: number; h: number; text: string; compact: string }[] = []
      for (const textItem of content.items as any[]) {
        if (!('str' in textItem) || !textItem.str.trim()) continue
        const y = textItem.transform[5] as number
        const h = (textItem.height as number) || Math.abs(textItem.transform[3] as number) || 10
        const str = textItem.str.toLowerCase()
        const existing = lines.find(l => Math.abs(l.y - y) < 8)
        if (existing) {
          existing.text += ' ' + str
          existing.compact += str.replace(/\s+/g, '')
          existing.h = Math.max(existing.h, h)
        } else {
          lines.push({ y, h, text: str, compact: str.replace(/\s+/g, '') })
        }
      }
      if (lines.length === 0) continue
      let bestLine: { y: number; h: number } | null = null
      if (cikkszam) {
        const needle = cikkszam.toLowerCase().replace(/\s+/g, '')
        bestLine = lines.find(l => l.compact.includes(needle) || l.text.includes(needle)) ?? null
      } else if (keywords.length > 0) {
        let bestScore = 0
        for (const line of lines) {
          const haystack = line.text + ' ' + line.compact
          const exact = keywords.filter((kw: string) => haystack.includes(kw)).length
          const partial = keywords.filter((kw: string) => kw.length >= 5 && haystack.includes(kw.slice(0, 5))).length
          const score = exact * 2 + partial
          if (score > 0 && score > bestScore) { bestScore = score; bestLine = line }
        }
      }
      if (bestLine) {
        setPdfPage(pageNum)
        setPdfHighlight({ page: pageNum, y: bestLine.y, h: Math.max(bestLine.h, 12) })
        return
      }
    }

    // Product not found in text — clear highlight but keep row selected
    setPdfHighlight(null)
  }

  // ── Replenishment actions ──────────────────────────────────────────────

  async function handleAccept(suggestion: Suggestion) {
    try {
      await client.post('/api/replenishment/accept', {
        orders: [{ product_id: suggestion.product_id, quantity: suggestion.suggested_order_quantity }],
        approved_by: uuidv4(),
      })
      setAcceptedRows(prev => new Set([...prev, suggestion.product_id]))
      setReplenishStatus(`✓ Purchase order accepted for ${suggestion.product_name}`)
    } catch {
      setReplenishStatus(`Failed to accept order for ${suggestion.product_name}`)
    }
  }

  function handleDismiss(suggestion: Suggestion) {
    setDismissedRows(prev => new Set([...prev, suggestion.product_id]))
    setReplenishStatus(`Dismissed suggestion for ${suggestion.product_name}`)
  }

  // ── Helpers ────────────────────────────────────────────────────────────

  function priorityColor(priority: string) {
    if (priority === 'critical') return 'bg-red-100 text-red-800'
    if (priority === 'low') return 'bg-yellow-100 text-yellow-800'
    return 'bg-green-100 text-green-800'
  }

  const visibleSuggestions = replenishment?.suggestions.filter(
    s => !dismissedRows.has(s.product_id)
  ) ?? []

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="bg-gray-50">
      <div className="p-8 max-w-7xl mx-auto">
        <h2 className="text-2xl font-bold mb-6">Management Dashboard</h2>

        {/* ── KPI Cards ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Today's Revenue</p>
            <p className="text-2xl font-bold text-green-600 mt-1">
              ${loading ? '—' : (kpis?.today_revenue ?? 0).toFixed(2)}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Today's Sales</p>
            <p className="text-2xl font-bold text-blue-600 mt-1">
              {loading ? '—' : kpis?.today_transactions ?? 0}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Today's Voids</p>
            <p className="text-2xl font-bold text-red-500 mt-1">
              {loading ? '—' : kpis?.today_void_count ?? 0}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">All-Time Revenue</p>
            <p className="text-2xl font-bold text-gray-700 mt-1">
              ${loading ? '—' : (kpis?.total_revenue ?? 0).toFixed(2)}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide">Reorder Budget Left</p>
            <p className="text-2xl font-bold text-purple-600 mt-1">
              ${replenishment ? Number(replenishment.budget_remaining).toFixed(2) : '—'}
            </p>
          </div>
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
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── AI Invoice Processing ───────────────────────────────────── */}
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
              accept=".pdf,.png,.jpg,.jpeg"
              className="hidden"
              onChange={handleInvoiceUpload}
            />
          </div>

          {invoiceError && (
            <p className="px-6 py-4 text-red-500 text-sm">{invoiceError}</p>
          )}

          {/* Loading state — full-height panel matching the invoice viewer */}
          {invoiceLoading && (
            <div className="flex items-center justify-center bg-gray-900" style={{ height: '75vh' }}>
              <div className="flex flex-col items-center gap-6 text-center px-8">
                {/* Spinner */}
                <svg
                  className="animate-spin text-blue-400"
                  style={{ width: 56, height: 56 }}
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                  <path className="opacity-75" fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {/* Current phrase */}
                <p className="text-white text-lg font-medium tracking-wide">
                  {_LOADING_PHRASES[loadingPhrase]}
                </p>
                {/* Progress dots */}
                <div className="flex gap-2">
                  {_LOADING_PHRASES.map((_, idx) => (
                    <span
                      key={idx}
                      className={`w-2 h-2 rounded-full transition-colors duration-500 ${
                        idx <= loadingPhrase ? 'bg-blue-400' : 'bg-gray-600'
                      }`}
                    />
                  ))}
                </div>
                <p className="text-gray-500 text-sm">
                  Claude Vision is reading the invoice image — this takes 10–30 seconds
                </p>
              </div>
            </div>
          )}

          {!invoiceResult && !invoiceError && !invoiceLoading && (
            <p className="px-6 py-4 text-gray-400 text-sm">
              Upload a supplier invoice PDF or image to extract line items automatically.
            </p>
          )}

          {invoiceResult && (
            <div>
              {/* ── Summary bar — editable header fields ── */}
              <div className="px-4 py-3 border-b bg-gray-50 flex flex-wrap gap-4 items-center text-sm">
                <label className="flex items-center gap-1">
                  <span className="font-semibold text-gray-600 whitespace-nowrap">Supplier:</span>
                  <input
                    type="text"
                    defaultValue={invoiceResult.header.supplier_name || ''}
                    onChange={e => { invoiceResult.header.supplier_name = e.target.value }}
                    placeholder="—"
                    className="border border-gray-300 rounded px-2 py-0.5 text-xs w-36 focus:border-blue-400 focus:outline-none"
                  />
                </label>
                <label className="flex items-center gap-1">
                  <span className="font-semibold text-gray-600 whitespace-nowrap">Ref:</span>
                  <input
                    type="text"
                    defaultValue={invoiceResult.header.invoice_ref || ''}
                    onChange={e => { invoiceResult.header.invoice_ref = e.target.value }}
                    placeholder="—"
                    className="border border-gray-300 rounded px-2 py-0.5 text-xs w-32 focus:border-blue-400 focus:outline-none"
                  />
                </label>
                <label className="flex items-center gap-1">
                  <span className="font-semibold text-gray-600 whitespace-nowrap">Date:</span>
                  <input
                    type="text"
                    defaultValue={invoiceResult.header.invoice_date || ''}
                    onChange={e => { invoiceResult.header.invoice_date = e.target.value }}
                    placeholder="YYYY-MM-DD"
                    className="border border-gray-300 rounded px-2 py-0.5 text-xs w-28 focus:border-blue-400 focus:outline-none"
                  />
                </label>
                <span className="text-gray-500">
                  Confidence: <strong>{(invoiceResult.overall_confidence * 100).toFixed(0)}%</strong>
                </span>
                {invoiceResult.document_warning ? (
                  <span className="text-orange-600 font-medium">⚠ {invoiceResult.document_warning}</span>
                ) : (
                  <>
                    <span className={invoiceResult.requires_review ? 'text-yellow-600 font-medium' : 'text-green-600 font-medium'}>
                      {invoiceResult.requires_review
                        ? `⚠ ${invoiceResult.flagged_count} item(s) need review`
                        : '✓ All items auto-accepted'}
                    </span>
                    {invoiceResult.footer_discrepancy ? (
                      <span className="text-red-600 font-medium">⚠ Total mismatch: {invoiceResult.footer_discrepancy}</span>
                    ) : (
                      <span className="text-green-600">✓ Net total {Number(invoiceResult.computed_net_total).toLocaleString('hu-HU')} matches invoice</span>
                    )}
                  </>
                )}
                {highlightedRow !== null && (
                  <span className="text-blue-600 text-xs">
                    {pdfHighlight ? '📍 Row highlighted on PDF' : '📄 Navigated to page'}
                    {' '}— click row again to deselect
                  </span>
                )}
              </div>

              {/* ── Split panel: PDF left, table right ── */}
              <div className="flex" style={{ height: '75vh' }}>

                {/* Left: PDF.js canvas viewer */}
                {invoiceFileUrl && (
                  <div className="w-5/12 flex-shrink-0 border-r flex flex-col bg-gray-800">
                    {/* Page navigation + zoom bar */}
                    <div className="px-3 py-2 bg-gray-700 flex items-center justify-between flex-shrink-0">
                      <span className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
                        Original Invoice
                      </span>
                      <div className="flex items-center gap-3">
                        {/* Zoom controls */}
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setViewZoom(z => Math.max(0.3, +(z - 0.25).toFixed(2)))}
                            title="Zoom out"
                            className="w-6 h-6 rounded bg-gray-600 hover:bg-gray-500 text-gray-200 text-sm flex items-center justify-center leading-none"
                          >
                            −
                          </button>
                          <button
                            onClick={() => { setViewZoom(1.0); setViewPan({ x: 0, y: 0 }) }}
                            title="Reset zoom and pan"
                            className="text-xs text-gray-300 hover:text-white w-10 text-center tabular-nums"
                          >
                            {Math.round(viewZoom * 100)}%
                          </button>
                          <button
                            onClick={() => setViewZoom(z => Math.min(6, +(z + 0.25).toFixed(2)))}
                            title="Zoom in"
                            className="w-6 h-6 rounded bg-gray-600 hover:bg-gray-500 text-gray-200 text-sm flex items-center justify-center leading-none"
                          >
                            +
                          </button>
                        </div>
                        {/* Page navigation — PDFs only */}
                        {!invoiceIsImage && pdfTotalPages > 1 && (
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => setPdfPage(p => Math.max(1, p - 1))}
                              disabled={pdfPage <= 1}
                              className="text-gray-300 hover:text-white disabled:opacity-30 text-lg leading-none px-1"
                            >
                              ‹
                            </button>
                            <span className="text-xs text-gray-300">
                              {pdfPage} / {pdfTotalPages}
                            </span>
                            <button
                              onClick={() => setPdfPage(p => Math.min(pdfTotalPages, p + 1))}
                              disabled={pdfPage >= pdfTotalPages}
                              className="text-gray-300 hover:text-white disabled:opacity-30 text-lg leading-none px-1"
                            >
                              ›
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Canvas / image area — scroll to zoom, drag to pan */}
                    <div
                      ref={pdfContainerRef}
                      className="flex-1 overflow-hidden relative select-none"
                      style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
                      onMouseDown={e => {
                        setIsDragging(true)
                        dragStartRef.current = {
                          mouseX: e.clientX,
                          mouseY: e.clientY,
                          panX: viewPan.x,
                          panY: viewPan.y,
                        }
                        e.preventDefault()
                      }}
                      onMouseMove={e => {
                        if (!isDragging) return
                        setViewPan({
                          x: dragStartRef.current.panX + (e.clientX - dragStartRef.current.mouseX),
                          y: dragStartRef.current.panY + (e.clientY - dragStartRef.current.mouseY),
                        })
                      }}
                      onMouseUp={() => setIsDragging(false)}
                      onMouseLeave={() => setIsDragging(false)}
                    >
                      {/* CSS transform wrapper — zoom + pan */}
                      <div
                        style={{
                          transform: `translate(${viewPan.x}px, ${viewPan.y}px) scale(${viewZoom})`,
                          transformOrigin: '0 0',
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          padding: '8px',
                        }}
                      >
                        {invoiceIsImage ? (
                          /* Direct image render for JPEG / PNG uploads */
                          <img
                            src={invoiceFileUrl!}
                            alt="Invoice"
                            className="block shadow-lg max-w-none"
                            style={{ width: '100%' }}
                            draggable={false}
                          />
                        ) : (
                          /* PDF.js canvas render for PDF uploads */
                          <div className="relative inline-block">
                            <canvas ref={canvasRef} className="block shadow-lg" />
                            <canvas
                              ref={overlayRef}
                              className="absolute inset-0 pointer-events-none"
                              style={{ mixBlendMode: 'multiply' }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Right: editable extracted table */}
                <div className={`flex flex-col overflow-hidden ${invoiceFileUrl ? 'w-7/12' : 'w-full'}`}>
                  <div className="px-3 py-2 bg-gray-100 border-b text-xs font-semibold text-gray-500 uppercase tracking-wide flex justify-between items-center">
                    <span>Extracted Data — Megnevezés → Db/Csom → Menny → Egységár → Nettó ár → ÁFA% → Bruttó</span>
                    <span className="text-blue-600 font-bold normal-case">Blue = goes into inventory</span>
                  </div>

                  <div className="overflow-auto flex-1">
                    <table className="text-sm w-full">
                      <thead className="bg-gray-50 text-gray-600 sticky top-0 z-10 border-b">
                        <tr>
                          <th className="text-left px-3 py-2 min-w-[160px]">
                            <div>Megnevezés</div>
                            <div className="text-xs text-gray-400 font-normal">Product name</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Csom.Egys</div>
                            <div className="text-xs text-gray-400 font-normal">Unit type</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Db/Csom</div>
                            <div className="text-xs text-gray-400 font-normal">Pack size</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Menny</div>
                            <div className="text-xs text-gray-400 font-normal">Qty (packs)</div>
                          </th>
                          <th className="text-left px-3 py-2 text-blue-700">
                            <div className="font-bold">→ Inventory</div>
                            <div className="text-xs text-blue-500 font-normal">Menny × Db/Csom</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Egységár</div>
                            <div className="text-xs text-gray-400 font-normal">Unit price</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Nettó ár</div>
                            <div className="text-xs text-gray-400 font-normal">Net total</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>ÁFA%</div>
                            <div className="text-xs text-gray-400 font-normal">VAT rate</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Bruttó</div>
                            <div className="text-xs text-gray-400 font-normal">Gross total</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Conf.</div>
                            <div className="text-xs text-gray-400 font-normal">AI score</div>
                          </th>
                          <th className="text-left px-3 py-2">
                            <div>Flags</div>
                          </th>
                          <th className="text-left px-3 py-2 min-w-[120px]">
                            <div>Notes</div>
                            <div className="text-xs text-gray-400 font-normal">Manager correction</div>
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {invoiceResult.line_items.map((item: any, i: number) => {
                          const totalUnits = (item.quantity || 0) * (item.packaging_size || 1)
                          const hasPackagingFlag = item.flags.some((f: string) =>
                            f.includes('pack') || f.includes('unit') || f.includes('quantity')
                          )
                          const confPct = Math.round((item.confidence ?? 0) * 100)
                          const confColor =
                            confPct >= 90 ? 'text-green-600' :
                            confPct >= 70 ? 'text-yellow-600' : 'text-red-500'
                          const FLAG_LABELS: Record<string, string> = {
                            line_total_mismatch: '⚠ Nettó ár mismatch',
                            low_confidence: '⚠ Low confidence',
                            packaging_ambiguous: '⚠ Db/Csom ambiguous',
                            unit_ambiguous: '⚠ Csom.Egys ambiguous',
                            quantity_ambiguous: '⚠ Menny ambiguous',
                            missing_product_match: '⚠ Product not matched',
                            invalid_quantity: '⚠ Invalid quantity',
                            invalid_unit_price: '⚠ Invalid price',
                          }

                          const isSelected = highlightedRow === i
                          const rowBg = isSelected
                            ? 'bg-blue-50 ring-2 ring-inset ring-blue-400 cursor-pointer'
                            : item.flags.length > 0
                              ? 'bg-yellow-50 hover:bg-yellow-100 cursor-pointer'
                              : 'hover:bg-gray-50 cursor-pointer'

                          return (
                            <tr
                              key={i}
                              className={`transition-colors ${rowBg}`}
                              onClick={() => handleRowClick(item, i)}
                              title="Click to highlight this row on the PDF"
                            >
                              {/* Megnevezés + cikkszám */}
                              <td className="px-3 py-1.5">
                                <input type="text" defaultValue={item.product_name}
                                  onChange={e => { item.product_name = e.target.value }}
                                  onClick={e => e.stopPropagation()}
                                  className="w-full border border-gray-200 rounded px-2 py-1 text-xs focus:border-blue-400 focus:outline-none" />
                                {item.cikkszam && (
                                  <div className="text-xs text-gray-400 font-mono mt-0.5 pl-1">
                                    #{item.cikkszam}
                                  </div>
                                )}
                              </td>
                              {/* Csom.Egys */}
                              <td className="px-3 py-1.5">
                                <input type="text" defaultValue={item.unit || ''}
                                  onChange={e => { item.unit = e.target.value }}
                                  onClick={e => e.stopPropagation()}
                                  placeholder="DB"
                                  className={`w-14 border rounded px-2 py-1 text-xs font-mono focus:outline-none uppercase ${
                                    hasPackagingFlag
                                      ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                      : 'border-gray-200 focus:border-blue-400'
                                  }`} />
                              </td>
                              {/* Db/Csom */}
                              <td className="px-3 py-1.5">
                                <input type="number" defaultValue={item.packaging_size || 1} min="1"
                                  onChange={e => { item.packaging_size = Number(e.target.value) }}
                                  onClick={e => e.stopPropagation()}
                                  className={`w-16 border rounded px-2 py-1 text-xs focus:outline-none ${
                                    hasPackagingFlag
                                      ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                      : 'border-gray-200 focus:border-blue-400'
                                  }`} />
                              </td>
                              {/* Menny */}
                              <td className="px-3 py-1.5">
                                <input type="number" defaultValue={item.quantity} min="1"
                                  onChange={e => { item.quantity = Number(e.target.value) }}
                                  onClick={e => e.stopPropagation()}
                                  className="w-14 border border-gray-200 rounded px-2 py-1 text-xs focus:border-blue-400 focus:outline-none" />
                              </td>
                              {/* → Inventory */}
                              <td className="px-3 py-1.5">
                                <span className="inline-block bg-blue-50 border border-blue-200 text-blue-800 font-bold rounded px-2 py-1 text-xs min-w-[2.5rem] text-center">
                                  {totalUnits}
                                </span>
                              </td>
                              {/* Egységár */}
                              <td className="px-3 py-1.5">
                                <input type="number" defaultValue={Number(item.unit_price).toFixed(2)} step="0.01"
                                  onChange={e => { item.unit_price = e.target.value }}
                                  onClick={e => e.stopPropagation()}
                                  className={`w-24 border rounded px-2 py-1 text-xs focus:outline-none ${
                                    item.flags.includes('line_total_mismatch')
                                      ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                      : 'border-gray-200 focus:border-blue-400'
                                  }`} />
                              </td>
                              {/* Nettó ár — editable */}
                              <td className="px-3 py-1.5">
                                <input
                                  type="number"
                                  defaultValue={Number(item.line_total).toFixed(2)}
                                  step="0.01"
                                  onChange={e => { item.line_total = e.target.value }}
                                  onClick={e => e.stopPropagation()}
                                  className={`w-24 border rounded px-2 py-1 text-xs focus:outline-none font-medium ${
                                    item.flags.includes('line_total_mismatch')
                                      ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                      : 'border-gray-200 focus:border-blue-400'
                                  }`}
                                />
                              </td>
                              {/* ÁFA% */}
                              <td className="px-3 py-1.5">
                                <span className="text-xs font-mono text-gray-600">
                                  {item.vat_rate ? `${item.vat_rate}%` : '—'}
                                </span>
                              </td>
                              {/* Bruttó */}
                              <td className="px-3 py-1.5">
                                <span className="text-xs font-mono font-medium text-gray-800">
                                  {item.brutto_line_total
                                    ? Number(item.brutto_line_total).toLocaleString('hu-HU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                                    : '—'}
                                </span>
                              </td>
                              {/* Confidence */}
                              <td className="px-3 py-1.5">
                                <span className={`font-bold text-xs ${confColor}`}>{confPct}%</span>
                              </td>
                              {/* Flags */}
                              <td className="px-3 py-1.5">
                                {item.flags.length === 0 ? (
                                  <span className="text-green-600 text-xs">✓</span>
                                ) : (
                                  <div className="flex flex-col gap-0.5">
                                    {item.flags.map((f: string, fi: number) => (
                                      <span key={fi} className="text-yellow-700 text-xs leading-tight whitespace-nowrap">
                                        {FLAG_LABELS[f] ?? `⚠ ${f.replace(/_/g, ' ')}`}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </td>
                              {/* Notes — free-text manager correction field */}
                              <td className="px-3 py-1.5">
                                <input
                                  type="text"
                                  defaultValue={item.notes || ''}
                                  onChange={e => { item.notes = e.target.value }}
                                  onClick={e => e.stopPropagation()}
                                  placeholder="Add note…"
                                  className="w-full border border-gray-200 rounded px-2 py-1 text-xs focus:border-blue-400 focus:outline-none text-gray-500 placeholder-gray-300"
                                />
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Footer bar */}
                  <div className="px-4 py-3 border-t bg-gray-50 flex justify-between items-center flex-shrink-0">
                    <span className="text-sm text-gray-500">
                      Computed net total:{' '}
                      <strong>{Number(invoiceResult.computed_net_total).toLocaleString('hu-HU')}</strong>
                    </span>
                    <div className="flex items-center gap-3">
                      {approveStatus === 'success' && (
                        <span className="text-green-600 text-sm font-medium">✓ Inventory updated</span>
                      )}
                      {approveStatus === 'error' && (
                        <span className="text-red-600 text-sm">Approval failed</span>
                      )}
                      {invoiceResult.document_warning ? (
                        <span className="text-orange-600 text-sm font-medium">
                          Delivery notes cannot be approved
                        </span>
                      ) : (
                        <button
                          onClick={handleApproveInvoice}
                          disabled={approveStatus === 'loading' || approveStatus === 'success'}
                          className="bg-green-600 text-white px-6 py-2 rounded font-medium hover:bg-green-700 disabled:opacity-50"
                        >
                          {approveStatus === 'loading' ? 'Approving...' : approveStatus === 'success' ? 'Approved ✓' : 'Approve Invoice'}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Replenishment Table ─────────────────────────────────────── */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-6 py-4 border-b flex justify-between items-center">
            <h3 className="font-bold text-lg">Replenishment Suggestions</h3>
            {replenishment && (
              <span className="text-sm text-gray-500">
                Solver: <span className="font-medium text-gray-700">{replenishment.solver_status}</span>
                {' · '}Est. cost:{' '}
                <span className="font-medium text-blue-600">
                  ${Number(replenishment.total_estimated_cost).toFixed(2)}
                </span>
              </span>
            )}
          </div>

          {replenishStatus && (
            <div className="px-6 py-2 bg-blue-50 text-blue-700 text-sm border-b">{replenishStatus}</div>
          )}

          {loading ? (
            <p className="p-6 text-gray-400">Loading...</p>
          ) : visibleSuggestions.length === 0 ? (
            <p className="p-6 text-gray-400">No replenishment needed.</p>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50 text-sm text-gray-500">
                <tr>
                  <th className="text-left px-6 py-3">Product</th>
                  <th className="text-left px-6 py-3">Stock</th>
                  <th className="text-left px-6 py-3">Daily demand</th>
                  <th className="text-left px-6 py-3">Days left</th>
                  <th className="text-left px-6 py-3">Order qty</th>
                  <th className="text-left px-6 py-3">Est. cost</th>
                  <th className="text-left px-6 py-3">Priority</th>
                  <th className="text-left px-6 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {visibleSuggestions.map(s => {
                  const accepted = acceptedRows.has(s.product_id)
                  return (
                    <tr key={s.product_id} className={accepted ? 'bg-green-50' : ''}>
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
                      <td className="px-6 py-4">
                        {accepted ? (
                          <span className="text-green-600 text-sm font-medium">✓ Order placed</span>
                        ) : (
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleAccept(s)}
                              className="text-xs bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700"
                            >
                              Accept
                            </button>
                            <button
                              onClick={() => handleDismiss(s)}
                              className="text-xs bg-gray-200 text-gray-700 px-3 py-1 rounded hover:bg-gray-300"
                            >
                              Dismiss
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
