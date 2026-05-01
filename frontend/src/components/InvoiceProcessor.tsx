/**
 * InvoiceProcessor — self-contained AI invoice upload + review + approve widget.
 *
 * Used on both the Management Dashboard and the Invoices page.
 * Props:
 *   onApproved?: () => void  — called after a successful approve so the parent
 *                              can refresh replenishment data or invoice history.
 */
import { useEffect, useRef, useState } from 'react'
import { v4 as uuidv4 } from 'uuid'
import client from '../api/client'

// ── Helpers ────────────────────────────────────────────────────────────────

function deriveVatRate(
  net: number | string | undefined,
  brutto: number | string | undefined,
): number | null {
  const n = parseFloat(String(net ?? ''))
  const b = parseFloat(String(brutto ?? ''))
  if (!isFinite(n) || !isFinite(b) || n <= 0 || b <= 0) return null
  const rawPct = ((b - n) / n) * 100
  if (rawPct < -0.5) return null
  return Math.round(rawPct)
}

const _LOADING_PHRASES = [
  'Rendering invoice pages…',
  'Extracting text and layout…',
  'Detecting table columns and rows…',
  'Sending to AI for verification…',
  'Reading product names…',
  'Extracting quantities and unit prices…',
  'Identifying VAT rates…',
  'Calculating gross totals…',
  'Validating line item math…',
  'Checking footer totals…',
  'Routing flagged items for review…',
  'Almost done…',
]

const FLAG_LABELS: Record<string, string> = {
  line_total_mismatch: '⚠ Line total mismatch',
  low_confidence: '⚠ Low confidence',
  packaging_ambiguous: '⚠ Pack size ambiguous',
  unit_ambiguous: '⚠ Unit size ambiguous',
  quantity_ambiguous: '⚠ Quantity ambiguous',
  missing_product_match: '⚠ Product not matched',
  invalid_quantity: '⚠ Invalid quantity',
  invalid_unit_price: '⚠ Invalid price',
}

// ── Component ──────────────────────────────────────────────────────────────

interface Props {
  onApproved?: () => void
}

export default function InvoiceProcessor({ onApproved }: Props) {
  const [invoiceResult, setInvoiceResult] = useState<any>(null)
  const [invoiceFileUrl, setInvoiceFileUrl] = useState<string | null>(null)
  const [invoiceIsImage, setInvoiceIsImage] = useState(false)
  const [invoiceLoading, setInvoiceLoading] = useState(false)
  const [invoiceError, setInvoiceError] = useState('')
  const [approveStatus, setApproveStatus] = useState<
    'idle' | 'loading' | 'success' | 'error'
  >('idle')
  const [loadingPhrase, setLoadingPhrase] = useState(0)

  // PDF viewer
  const [pdfPage, setPdfPage] = useState(1)
  const [pdfTotalPages, setPdfTotalPages] = useState(0)
  const [pdfjsReady, setPdfjsReady] = useState(false)
  const [highlightedRow, setHighlightedRow] = useState<number | null>(null)
  const [pdfHighlight, setPdfHighlight] = useState<{
    page: number
    y: number
    h: number
  } | null>(null)
  const [pdfDocVersion, setPdfDocVersion] = useState(0)
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

  // ── PDF.js: load library once ────────────────────────────────────────────

  useEffect(() => {
    const win = window as any
    if (win.pdfjsLib) {
      setPdfjsReady(true)
      return
    }
    const script = document.createElement('script')
    script.src =
      'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'
    script.onload = () => {
      win.pdfjsLib.GlobalWorkerOptions.workerSrc =
        'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
      setPdfjsReady(true)
    }
    document.head.appendChild(script)
  }, [])

  // ── PDF.js: load document when URL changes ───────────────────────────────

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
      setPdfDocVersion(v => v + 1)
    })
  }, [pdfjsReady, invoiceFileUrl])

  // ── PDF.js: re-render when invoiceResult arrives ─────────────────────────

  useEffect(() => {
    if (invoiceResult && pdfDocRef.current) {
      setPdfDocVersion(v => v + 1)
    }
  }, [invoiceResult])

  // ── PDF.js: render current page + highlight overlay ──────────────────────

  useEffect(() => {
    async function renderPage() {
      if (!pdfDocRef.current || !canvasRef.current || !overlayRef.current) return
      if (renderTaskRef.current) {
        try {
          renderTaskRef.current.cancel()
        } catch { /* ignore */ }
        renderTaskRef.current = null
      }
      const page = await pdfDocRef.current.getPage(pdfPage)
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
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
        return
      }
      renderTaskRef.current = null
      const overlayCtx = overlay.getContext('2d')!
      overlayCtx.clearRect(0, 0, overlay.width, overlay.height)
      if (pdfHighlight && pdfHighlight.page === pdfPage) {
        const [, canvasYBottom] = viewport.convertToViewportPoint(
          0,
          pdfHighlight.y,
        )
        const [, canvasYTop] = viewport.convertToViewportPoint(
          0,
          pdfHighlight.y + pdfHighlight.h,
        )
        const rectY = Math.min(canvasYBottom, canvasYTop) - 4
        const rectH = Math.abs(canvasYBottom - canvasYTop) + 8
        const padX = 6
        overlayCtx.fillStyle = 'rgba(255, 215, 0, 0.45)'
        overlayCtx.fillRect(padX, rectY, overlay.width - padX * 2, rectH)
        overlayCtx.strokeStyle = 'rgba(200, 130, 0, 0.85)'
        overlayCtx.lineWidth = 1.5
        overlayCtx.strokeRect(padX, rectY, overlay.width - padX * 2, rectH)
      }
    }
    renderPage()
  }, [pdfPage, pdfHighlight, pdfDocVersion])

  // ── PDF viewer: scroll-to-zoom ────────────────────────────────────────────

  useEffect(() => {
    const handleWheel = (e: WheelEvent) => {
      const el = pdfContainerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const isOver =
        e.clientX >= rect.left &&
        e.clientX <= rect.right &&
        e.clientY >= rect.top &&
        e.clientY <= rect.bottom
      if (!isOver) return
      if (e.ctrlKey) return
      e.preventDefault()
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

  // ── Loading phrase ticker ─────────────────────────────────────────────────

  useEffect(() => {
    if (!invoiceLoading) return
    setLoadingPhrase(0)
    const id = setInterval(() => {
      setLoadingPhrase(p => Math.min(p + 1, _LOADING_PHRASES.length - 1))
    }, 2200)
    return () => clearInterval(id)
  }, [invoiceLoading])

  // ── Invoice pipeline ──────────────────────────────────────────────────────

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
      setInvoiceError(
        e.response?.data?.detail || 'Failed to process invoice',
      )
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
        supplier_ref:
          invoiceResult.header.supplier_name || 'UNKNOWN',
        invoice_ref:
          invoiceResult.header.invoice_ref || `INV-${Date.now()}`,
        invoice_date: invoiceResult.header.invoice_date || null,
        approved_by: uuidv4(),
        line_items: invoiceResult.line_items.map((item: any) => ({
          product_name: item.product_name,
          quantity: Number(item.quantity),
          unit_price: Number(item.unit_price),
          supplier_ref:
            invoiceResult.header.supplier_name || 'UNKNOWN',
          cikkszam: item.cikkszam || '',
          packaging_size: Number(item.packaging_size) || 1,
          line_total: Number(item.line_total) || 0,
        })),
      }
      await client.post('/api/invoices/approve', payload)
      setApproveStatus('success')
      onApproved?.()
    } catch (e: any) {
      console.error(e)
      setApproveStatus('error')
    }
  }

  // ── PDF row click — find text + highlight ─────────────────────────────────

  async function handleRowClick(item: any, rowIndex: number) {
    if (highlightedRow === rowIndex) {
      setHighlightedRow(null)
      setPdfHighlight(null)
      return
    }
    setHighlightedRow(rowIndex)
    if (!pdfDocRef.current) return

    const doc = pdfDocRef.current
    const targetPage: number = item.source_page ?? 1
    const cikkszam = (item.cikkszam || '').trim()
    const productKeywords = (item.product_name || '')
      .split(/\s+/)
      .map((w: string) => w.toLowerCase().trim())
      .filter((w: string) => w.length > 3)

    async function getPageLines(pageNum: number) {
      const page = await doc.getPage(pageNum)
      const content = await page.getTextContent()
      const hasText = (content.items as any[]).some(
        (it: any) => 'str' in it && it.str.trim().length > 0,
      )
      if (!hasText) return null
      const lines: {
        y: number
        h: number
        text: string
        compact: string
      }[] = []
      for (const textItem of content.items as any[]) {
        if (!('str' in textItem) || !textItem.str.trim()) continue
        const y = textItem.transform[5] as number
        const h =
          (textItem.height as number) ||
          Math.abs(textItem.transform[3] as number) ||
          10
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
      return lines.length > 0 ? lines : null
    }

    function keywordScore(line: { text: string; compact: string }) {
      const haystack = line.text + ' ' + line.compact
      const exact = productKeywords.filter((kw: string) =>
        haystack.includes(kw),
      ).length
      const partial = productKeywords.filter(
        (kw: string) => kw.length >= 5 && haystack.includes(kw.slice(0, 5)),
      ).length
      return exact * 2 + partial
    }

    if (cikkszam) {
      const lines = await getPageLines(targetPage)
      if (lines) {
        const needle = cikkszam.toLowerCase().replace(/\s+/g, '')
        const matches = lines.filter(
          l => l.compact.includes(needle) || l.text.includes(needle),
        )
        if (matches.length === 1) {
          setPdfPage(targetPage)
          setPdfHighlight({
            page: targetPage,
            y: matches[0].y,
            h: Math.max(matches[0].h, 18),
          })
          return
        }
        if (matches.length > 1) {
          let best = matches[0]
          let bestScore = keywordScore(matches[0])
          for (let mi = 1; mi < matches.length; mi++) {
            const s = keywordScore(matches[mi])
            if (s > bestScore) {
              bestScore = s
              best = matches[mi]
            }
          }
          setPdfPage(targetPage)
          setPdfHighlight({
            page: targetPage,
            y: best.y,
            h: Math.max(best.h, 18),
          })
          return
        }
      }
    }

    if (productKeywords.length > 0) {
      const searchPages = [
        targetPage,
        ...Array.from({ length: doc.numPages }, (_: unknown, i: number) => i + 1).filter(
          (p: number) => p !== targetPage,
        ),
      ]
      for (const pageNum of searchPages) {
        const lines = await getPageLines(pageNum)
        if (lines === null) break
        let bestScore = 0
        let bestLine: { y: number; h: number } | null = null
        for (const line of lines) {
          const score = keywordScore(line)
          if (score > 0 && score > bestScore) {
            bestScore = score
            bestLine = line
          }
        }
        if (bestLine) {
          setPdfPage(pageNum)
          setPdfHighlight({
            page: pageNum,
            y: bestLine.y,
            h: Math.max(bestLine.h, 18),
          })
          return
        }
      }
    }

    if (item.y_fraction != null) {
      const yFraction = item.y_fraction as number
      const page = await doc.getPage(targetPage)
      const baseVp = page.getViewport({ scale: 1 })
      const pageHeightPt = baseVp.height
      const rowHeightPt = Math.max(pageHeightPt * 0.03, 18)
      const fullH = rowHeightPt * 1.4
      const pdfY = pageHeightPt * (1 - yFraction) - fullH  // bottom edge anchor
      const h = fullH * 0.6                                 // trim 40% from top
      setPdfPage(targetPage)
      setPdfHighlight({
        page: targetPage,
        y: pdfY,
        h,
      })
      return
    }

    setPdfHighlight(null)
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="bg-white rounded-lg shadow mb-8">
      {/* Header */}
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

      {/* Loading panel */}
      {invoiceLoading && (
        <div
          className="flex items-center justify-center bg-gray-900"
          style={{ height: '75vh' }}
        >
          <div className="flex flex-col items-center gap-6 text-center px-8">
            <svg
              className="animate-spin text-blue-400"
              style={{ width: 56, height: 56 }}
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="3"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <p className="text-white text-lg font-medium tracking-wide">
              {_LOADING_PHRASES[loadingPhrase]}
            </p>
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
              Parsing layout, then verifying with AI — this takes 10–30 seconds
            </p>
          </div>
        </div>
      )}

      {!invoiceResult && !invoiceError && !invoiceLoading && (
        <p className="px-6 py-4 text-gray-400 text-sm">
          Upload a supplier invoice PDF or image to extract line items
          automatically.
        </p>
      )}

      {invoiceResult && (
        <div>
          {/* Summary bar */}
          <div className="px-4 py-3 border-b bg-gray-50 flex flex-wrap gap-4 items-center text-sm">
            <label className="flex items-center gap-1">
              <span className="font-semibold text-gray-600 whitespace-nowrap">
                Supplier:
              </span>
              <input
                type="text"
                defaultValue={invoiceResult.header.supplier_name || ''}
                onChange={e => {
                  invoiceResult.header.supplier_name = e.target.value
                }}
                placeholder="—"
                className="border border-gray-300 rounded px-2 py-0.5 text-xs w-36 focus:border-blue-400 focus:outline-none"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="font-semibold text-gray-600 whitespace-nowrap">
                Ref:
              </span>
              <input
                type="text"
                defaultValue={invoiceResult.header.invoice_ref || ''}
                onChange={e => {
                  invoiceResult.header.invoice_ref = e.target.value
                }}
                placeholder="—"
                className="border border-gray-300 rounded px-2 py-0.5 text-xs w-32 focus:border-blue-400 focus:outline-none"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="font-semibold text-gray-600 whitespace-nowrap">
                Date:
              </span>
              <input
                type="text"
                defaultValue={invoiceResult.header.invoice_date || ''}
                onChange={e => {
                  invoiceResult.header.invoice_date = e.target.value
                }}
                placeholder="YYYY-MM-DD"
                className="border border-gray-300 rounded px-2 py-0.5 text-xs w-28 focus:border-blue-400 focus:outline-none"
              />
            </label>
            <span className="text-gray-500">
              Confidence:{' '}
              <strong>
                {(invoiceResult.overall_confidence * 100).toFixed(0)}%
              </strong>
            </span>
            {invoiceResult.document_warning ? (
              <span className="text-orange-600 font-medium">
                ⚠ {invoiceResult.document_warning}
              </span>
            ) : (
              <>
                <span
                  className={
                    invoiceResult.requires_review
                      ? 'text-yellow-600 font-medium'
                      : 'text-green-600 font-medium'
                  }
                >
                  {invoiceResult.requires_review
                    ? `⚠ ${invoiceResult.flagged_count} item(s) need review`
                    : '✓ All items auto-accepted'}
                </span>
                {invoiceResult.footer_discrepancy ? (
                  <span className="text-red-600 font-medium">
                    ⚠ Total mismatch: {invoiceResult.footer_discrepancy}
                  </span>
                ) : (
                  <span className="text-green-600">
                    ✓ Net total{' '}
                    {Number(invoiceResult.computed_net_total).toLocaleString(
                      'hu-HU',
                    )}{' '}
                    matches invoice
                  </span>
                )}
              </>
            )}
            {highlightedRow !== null && (
              <span className="text-blue-600 text-xs">
                {pdfHighlight
                  ? '📍 Row highlighted on PDF'
                  : '📄 Navigated to page'}
                {' '}— click row again to deselect
              </span>
            )}
          </div>

          {/* Split panel: PDF left, table right */}
          <div className="flex" style={{ height: '75vh' }}>
            {/* Left: PDF viewer */}
            {invoiceFileUrl && (
              <div className="w-5/12 flex-shrink-0 border-r flex flex-col bg-gray-800">
                <div className="px-3 py-2 bg-gray-700 flex items-center justify-between flex-shrink-0">
                  <span className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
                    Original Invoice
                  </span>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() =>
                          setViewZoom(z => Math.max(0.3, +(z - 0.25).toFixed(2)))
                        }
                        title="Zoom out"
                        className="w-6 h-6 rounded bg-gray-600 hover:bg-gray-500 text-gray-200 text-sm flex items-center justify-center leading-none"
                      >
                        −
                      </button>
                      <button
                        onClick={() => {
                          setViewZoom(1.0)
                          setViewPan({ x: 0, y: 0 })
                        }}
                        title="Reset zoom and pan"
                        className="text-xs text-gray-300 hover:text-white w-10 text-center tabular-nums"
                      >
                        {Math.round(viewZoom * 100)}%
                      </button>
                      <button
                        onClick={() =>
                          setViewZoom(z => Math.min(6, +(z + 0.25).toFixed(2)))
                        }
                        title="Zoom in"
                        className="w-6 h-6 rounded bg-gray-600 hover:bg-gray-500 text-gray-200 text-sm flex items-center justify-center leading-none"
                      >
                        +
                      </button>
                    </div>
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
                          onClick={() =>
                            setPdfPage(p => Math.min(pdfTotalPages, p + 1))
                          }
                          disabled={pdfPage >= pdfTotalPages}
                          className="text-gray-300 hover:text-white disabled:opacity-30 text-lg leading-none px-1"
                        >
                          ›
                        </button>
                      </div>
                    )}
                  </div>
                </div>

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
                      x:
                        dragStartRef.current.panX +
                        (e.clientX - dragStartRef.current.mouseX),
                      y:
                        dragStartRef.current.panY +
                        (e.clientY - dragStartRef.current.mouseY),
                    })
                  }}
                  onMouseUp={() => setIsDragging(false)}
                  onMouseLeave={() => setIsDragging(false)}
                >
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
                      <img
                        src={invoiceFileUrl!}
                        alt="Invoice"
                        className="block shadow-lg max-w-none"
                        style={{ width: '100%' }}
                        draggable={false}
                      />
                    ) : (
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
            <div
              className={`flex flex-col overflow-hidden ${invoiceFileUrl ? 'w-7/12' : 'w-full'}`}
            >
              <div className="px-3 py-2 bg-gray-100 border-b text-xs font-semibold text-gray-500 uppercase tracking-wide">
                <span>Extracted Data</span>
              </div>

              <div className="overflow-auto flex-1">
                <table className="text-sm w-full">
                  <thead className="bg-gray-50 text-gray-600 sticky top-0 z-10 border-b">
                    <tr>
                      <th className="text-left px-3 py-2 min-w-[160px]">
                        <div>Product name</div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Unit type</div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Pack size</div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Qty (packs)</div>
                      </th>
                      <th className="text-left px-3 py-2 text-blue-700">
                        <div className="font-bold">→ Inventory</div>
                        <div className="text-xs text-blue-500 font-normal">
                          Qty × Pack size
                        </div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Unit price</div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Net total</div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>VAT %</div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Gross total</div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Conf.</div>
                        <div className="text-xs text-gray-400 font-normal">
                          AI score
                        </div>
                      </th>
                      <th className="text-left px-3 py-2">
                        <div>Flags</div>
                      </th>
                      <th className="text-left px-3 py-2 min-w-[120px]">
                        <div>Notes</div>
                        <div className="text-xs text-gray-400 font-normal">
                          Manager correction
                        </div>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {invoiceResult.line_items.map((item: any, i: number) => {
                      const totalUnits =
                        (item.quantity || 0) * (item.packaging_size || 1)
                      const hasPackagingFlag = item.flags.some((f: string) =>
                        f.includes('pack') ||
                        f.includes('unit') ||
                        f.includes('quantity'),
                      )
                      const confPct = Math.round((item.confidence ?? 0) * 100)
                      const confColor =
                        confPct >= 90
                          ? 'text-green-600'
                          : confPct >= 70
                          ? 'text-yellow-600'
                          : 'text-red-500'
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
                          <td className="px-3 py-1.5">
                            <input
                              type="text"
                              defaultValue={item.product_name}
                              onChange={e => {
                                item.product_name = e.target.value
                              }}
                              onClick={e => e.stopPropagation()}
                              className="w-full border border-gray-200 rounded px-2 py-1 text-xs focus:border-blue-400 focus:outline-none"
                            />
                            {item.cikkszam && (
                              <div className="text-xs text-gray-400 font-mono mt-0.5 pl-1">
                                #{item.cikkszam}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              type="text"
                              defaultValue={item.unit || ''}
                              onChange={e => {
                                item.unit = e.target.value
                              }}
                              onClick={e => e.stopPropagation()}
                              placeholder="DB"
                              className={`w-14 border rounded px-2 py-1 text-xs font-mono focus:outline-none uppercase ${
                                hasPackagingFlag
                                  ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                  : 'border-gray-200 focus:border-blue-400'
                              }`}
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              type="number"
                              defaultValue={item.packaging_size || 1}
                              min="1"
                              onChange={e => {
                                item.packaging_size = Number(e.target.value)
                              }}
                              onClick={e => e.stopPropagation()}
                              className={`w-16 border rounded px-2 py-1 text-xs focus:outline-none ${
                                hasPackagingFlag
                                  ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                  : 'border-gray-200 focus:border-blue-400'
                              }`}
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              type="number"
                              defaultValue={item.quantity}
                              min="1"
                              onChange={e => {
                                item.quantity = Number(e.target.value)
                              }}
                              onClick={e => e.stopPropagation()}
                              className="w-14 border border-gray-200 rounded px-2 py-1 text-xs focus:border-blue-400 focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <span className="inline-block bg-blue-50 border border-blue-200 text-blue-800 font-bold rounded px-2 py-1 text-xs min-w-[2.5rem] text-center">
                              {totalUnits}
                            </span>
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              type="number"
                              defaultValue={Number(item.unit_price).toFixed(2)}
                              step="0.01"
                              onChange={e => {
                                item.unit_price = e.target.value
                              }}
                              onClick={e => e.stopPropagation()}
                              className={`w-24 border rounded px-2 py-1 text-xs focus:outline-none ${
                                item.flags.includes('line_total_mismatch')
                                  ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                  : 'border-gray-200 focus:border-blue-400'
                              }`}
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              type="number"
                              defaultValue={Number(item.line_total).toFixed(2)}
                              step="0.01"
                              onChange={e => {
                                item.line_total = e.target.value
                              }}
                              onClick={e => e.stopPropagation()}
                              className={`w-24 border rounded px-2 py-1 text-xs focus:outline-none font-medium ${
                                item.flags.includes('line_total_mismatch')
                                  ? 'border-yellow-400 bg-yellow-50 focus:border-yellow-600'
                                  : 'border-gray-200 focus:border-blue-400'
                              }`}
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            {(() => {
                              const computed = deriveVatRate(
                                item.line_total,
                                item.brutto_line_total,
                              )
                              const extracted =
                                item.vat_rate != null && item.vat_rate !== ''
                                  ? Number(item.vat_rate)
                                  : null
                              const display = computed ?? extracted
                              const mismatch =
                                computed !== null &&
                                extracted !== null &&
                                Math.abs(computed - extracted) > 0.5
                              return (
                                <div>
                                  <span
                                    className={`text-xs font-mono font-medium ${mismatch ? 'text-amber-600' : 'text-gray-700'}`}
                                  >
                                    {display != null ? `${display}%` : '—'}
                                  </span>
                                  {mismatch && (
                                    <div
                                      className="text-xs text-gray-400 leading-tight"
                                      title="VAT rate extracted by AI — overridden by net/brut calculation"
                                    >
                                      AI: {extracted}%
                                    </div>
                                  )}
                                </div>
                              )
                            })()}
                          </td>
                          <td className="px-3 py-1.5">
                            <span className="text-xs font-mono font-medium text-gray-800">
                              {item.brutto_line_total
                                ? Number(
                                    item.brutto_line_total,
                                  ).toLocaleString('hu-HU', {
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                  })
                                : '—'}
                            </span>
                          </td>
                          <td className="px-3 py-1.5">
                            <span
                              className={`font-bold text-xs ${confColor}`}
                            >
                              {confPct}%
                            </span>
                          </td>
                          <td className="px-3 py-1.5">
                            {item.flags.length === 0 ? (
                              <span className="text-green-600 text-xs">✓</span>
                            ) : (
                              <div className="flex flex-col gap-0.5">
                                {item.flags.map((f: string, fi: number) => (
                                  <span
                                    key={fi}
                                    className="text-yellow-700 text-xs leading-tight whitespace-nowrap"
                                  >
                                    {FLAG_LABELS[f] ??
                                      `⚠ ${f.replace(/_/g, ' ')}`}
                                  </span>
                                ))}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              type="text"
                              defaultValue={item.notes || ''}
                              onChange={e => {
                                item.notes = e.target.value
                              }}
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
                  <strong>
                    {Number(invoiceResult.computed_net_total).toLocaleString(
                      'hu-HU',
                    )}
                  </strong>
                </span>
                <div className="flex items-center gap-3">
                  {approveStatus === 'success' && (
                    <span className="text-green-600 text-sm font-medium">
                      ✓ Inventory updated
                    </span>
                  )}
                  {approveStatus === 'error' && (
                    <span className="text-red-600 text-sm">
                      Approval failed
                    </span>
                  )}
                  {invoiceResult.document_warning ? (
                    <span className="text-orange-600 text-sm font-medium">
                      Delivery notes cannot be approved
                    </span>
                  ) : (
                    <button
                      onClick={handleApproveInvoice}
                      disabled={
                        approveStatus === 'loading' ||
                        approveStatus === 'success'
                      }
                      className="bg-green-600 text-white px-6 py-2 rounded font-medium hover:bg-green-700 disabled:opacity-50"
                    >
                      {approveStatus === 'loading'
                        ? 'Approving...'
                        : approveStatus === 'success'
                        ? 'Approved ✓'
                        : 'Approve Invoice'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
