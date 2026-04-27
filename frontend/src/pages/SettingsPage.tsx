/**
 * SettingsPage — UC-12 System Configuration.
 *
 * Managers can adjust runtime parameters (budget, costing strategy, etc.)
 * without touching the .env file. Every change is written to the DB and
 * appended to the event store so it appears in the audit trail and replay.
 */

import { useEffect, useState } from 'react'
import client from '../api/client'
import { useAuthStore } from '../store/authStore'

interface Config {
  replenishment_budget: number
  replenishment_target_days: number
  costing_strategy: string
  ai_confidence_threshold: number
  overrides: Record<string, string>
}

function Badge({ label, isOverride }: { label: string; isOverride: boolean }) {
  return isOverride ? (
    <span className="ml-2 text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">
      overridden
    </span>
  ) : (
    <span className="ml-2 text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
      env default
    </span>
  )
}

export default function SettingsPage() {
  const { user } = useAuthStore()
  const [config, setConfig] = useState<Config | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Local editable copies
  const [budget, setBudget] = useState('')
  const [targetDays, setTargetDays] = useState('')
  const [costingStrategy, setCostingStrategy] = useState('FIFO')
  const [confidenceThreshold, setConfidenceThreshold] = useState('')

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    try {
      const r = await client.get('/api/config')
      const cfg: Config = r.data
      setConfig(cfg)
      setBudget(String(cfg.replenishment_budget))
      setTargetDays(String(cfg.replenishment_target_days))
      setCostingStrategy(cfg.costing_strategy)
      setConfidenceThreshold(String(cfg.ai_confidence_threshold))
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Failed to load config')
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const r = await client.patch('/api/config', {
        replenishment_budget: parseFloat(budget),
        replenishment_target_days: parseInt(targetDays, 10),
        costing_strategy: costingStrategy,
        ai_confidence_threshold: parseFloat(confidenceThreshold),
        updated_by: user?.email ?? 'manager',
      })
      setConfig(r.data)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return (
    <div className="flex-1 flex items-center justify-center text-gray-400">Loading…</div>
  )

  const isOverride = (key: string) => key in (config?.overrides ?? {})

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">System Settings</h1>
        <p className="text-sm text-gray-500 mt-1">
          Runtime configuration — changes take effect immediately and are recorded
          in the event log for full audit traceability.
        </p>
      </div>

      {error && (
        <div className="mb-6 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded">
          ⚠ {error}
        </div>
      )}

      {/* ── Replenishment ────────────────────────────────────────────────────── */}
      <section className="bg-white rounded-lg border border-gray-200 mb-6 overflow-hidden">
        <div className="px-5 py-3 bg-gray-50 border-b">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
            Replenishment Engine
          </h2>
        </div>
        <div className="px-5 py-5 space-y-5">

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Budget (Ft)
              <Badge label="budget" isOverride={isOverride('replenishment_budget')} />
            </label>
            <input
              type="number"
              min={1}
              step={500}
              value={budget}
              onChange={e => setBudget(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <p className="text-xs text-gray-400 mt-1">
              Maximum total spend the MILP solver may recommend per replenishment run.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Target stock days
              <Badge label="target_days" isOverride={isOverride('replenishment_target_days')} />
            </label>
            <input
              type="number"
              min={1}
              max={365}
              value={targetDays}
              onChange={e => setTargetDays(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <p className="text-xs text-gray-400 mt-1">
              How many days of demand the solver should cover when recommending orders.
            </p>
          </div>

        </div>
      </section>

      {/* ── Inventory costing ────────────────────────────────────────────────── */}
      <section className="bg-white rounded-lg border border-gray-200 mb-6 overflow-hidden">
        <div className="px-5 py-3 bg-gray-50 border-b">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
            Inventory Costing
          </h2>
        </div>
        <div className="px-5 py-5">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Costing strategy
            <Badge label="costing_strategy" isOverride={isOverride('costing_strategy')} />
          </label>
          <div className="flex gap-4">
            {(['FIFO', 'WAC'] as const).map(opt => (
              <label
                key={opt}
                className={`flex-1 border rounded-lg px-4 py-3 cursor-pointer transition-colors ${
                  costingStrategy === opt
                    ? 'border-indigo-500 bg-indigo-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <input
                  type="radio"
                  name="costing"
                  value={opt}
                  checked={costingStrategy === opt}
                  onChange={() => setCostingStrategy(opt)}
                  className="sr-only"
                />
                <div className="font-semibold text-sm text-gray-900">{opt}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {opt === 'FIFO'
                    ? 'First In, First Out — oldest cost layers consumed first'
                    : 'Weighted Average Cost — rolling average across all layers'}
                </div>
              </label>
            ))}
          </div>
        </div>
      </section>

      {/* ── AI invoice pipeline ──────────────────────────────────────────────── */}
      <section className="bg-white rounded-lg border border-gray-200 mb-8 overflow-hidden">
        <div className="px-5 py-3 bg-gray-50 border-b">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
            AI Invoice Pipeline
          </h2>
        </div>
        <div className="px-5 py-5">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Confidence threshold
            <Badge label="confidence" isOverride={isOverride('ai_confidence_threshold')} />
          </label>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={confidenceThreshold}
              onChange={e => setConfidenceThreshold(e.target.value)}
              className="flex-1 accent-indigo-600"
            />
            <span className="w-12 text-center font-mono text-sm font-semibold text-gray-700">
              {(parseFloat(confidenceThreshold) * 100).toFixed(0)}%
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Extracted line items with confidence below this value are flagged for manager review.
            Lower = fewer flags but more errors pass through. Higher = more flags, safer.
          </p>
        </div>
      </section>

      {/* Save button */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-indigo-600 text-white px-6 py-2 rounded font-medium text-sm hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        {saved && (
          <span className="text-green-600 text-sm font-medium">
            ✓ Settings saved — changes take effect immediately
          </span>
        )}
      </div>

      {/* Current effective values (read-only summary) */}
      {config && (
        <div className="mt-8 bg-gray-50 border rounded-lg px-5 py-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Current effective values
          </h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt className="text-gray-500">Replenishment budget</dt>
            <dd className="font-mono font-medium text-gray-900">
              {config.replenishment_budget.toLocaleString('hu-HU')} Ft
            </dd>
            <dt className="text-gray-500">Target stock days</dt>
            <dd className="font-mono font-medium text-gray-900">{config.replenishment_target_days} days</dd>
            <dt className="text-gray-500">Costing strategy</dt>
            <dd className="font-mono font-medium text-gray-900">{config.costing_strategy}</dd>
            <dt className="text-gray-500">Confidence threshold</dt>
            <dd className="font-mono font-medium text-gray-900">
              {(config.ai_confidence_threshold * 100).toFixed(0)}%
            </dd>
          </dl>
        </div>
      )}
    </div>
  )
}
