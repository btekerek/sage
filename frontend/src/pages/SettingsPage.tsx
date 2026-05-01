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
  replenishment_target_days: number
  replenishment_lead_time_days: number
  replenishment_weekly_budget: number
  costing_strategy: string
  ai_confidence_threshold: number
  margin_target: number
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

  const [targetDays, setTargetDays] = useState('')
  const [leadTimeDays, setLeadTimeDays] = useState('')
  const [weeklyBudget, setWeeklyBudget] = useState('')
  const [costingStrategy, setCostingStrategy] = useState('FIFO')
  const [confidenceThreshold, setConfidenceThreshold] = useState('')
  const [marginTarget, setMarginTarget] = useState('')

  const [applyingMargin, setApplyingMargin] = useState(false)
  const [applyMarginResult, setApplyMarginResult] = useState<{
    updated: number; skipped: number; margin_target: number
  } | null>(null)
  const [applyMarginError, setApplyMarginError] = useState<string | null>(null)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const r = await client.get('/api/config')
      const cfg: Config = r.data
      setConfig(cfg)
      setTargetDays(String(cfg.replenishment_target_days))
      setLeadTimeDays(String(cfg.replenishment_lead_time_days))
      setWeeklyBudget(String(cfg.replenishment_weekly_budget))
      setCostingStrategy(cfg.costing_strategy)
      setConfidenceThreshold(String(cfg.ai_confidence_threshold))
      setMarginTarget(String(cfg.margin_target))
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
        replenishment_target_days: parseInt(targetDays, 10),
        replenishment_lead_time_days: parseInt(leadTimeDays, 10),
        replenishment_weekly_budget: parseInt(weeklyBudget, 10),
        costing_strategy: costingStrategy,
        ai_confidence_threshold: parseFloat(confidenceThreshold),
        margin_target: parseFloat(marginTarget),
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

  async function handleApplyMargin() {
    setApplyingMargin(true)
    setApplyMarginResult(null)
    setApplyMarginError(null)
    try {
      const r = await client.post('/api/config/apply-margin', {
        applied_by: user?.email ?? 'manager',
        margin_override: parseFloat(marginTarget),
      })
      setApplyMarginResult(r.data)
    } catch (e: any) {
      setApplyMarginError(e?.response?.data?.detail ?? e?.message ?? 'Failed to apply margin')
    } finally {
      setApplyingMargin(false)
    }
  }

  if (loading) return (
    <div className="flex-1 flex items-center justify-center text-gray-400">Loading...</div>
  )

  const isOverride = (key: string) => key in (config?.overrides ?? {})
  const marginPct = parseFloat(marginTarget) || 0

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">System Settings</h1>
        <p className="text-sm text-gray-500 mt-1">
          Runtime configuration — changes take effect immediately and are recorded
          in the event log for full audit traceability.
        </p>
      </div>

      {error && (
        <div className="mb-6 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded">
          {error}
        </div>
      )}

      {/* Pricing & Margins */}
      <section className="bg-white rounded-lg border border-gray-200 mb-6 overflow-hidden">
        <div className="px-5 py-3 bg-gray-50 border-b">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
            Pricing &amp; Margins
          </h2>
        </div>
        <div className="px-5 py-5">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Margin target
            <Badge label="margin_target" isOverride={isOverride('margin_target')} />
          </label>
          <div className="flex items-center gap-4">
            <input
              type="range" min={0} max={0.99} step={0.01}
              value={marginTarget}
              onChange={e => setMarginTarget(e.target.value)}
              className="flex-1 accent-indigo-600"
            />
            <span className="w-14 text-center font-mono text-sm font-semibold text-gray-700">
              {(marginPct * 100).toFixed(0)}%
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Selling price is set automatically as{' '}
            <span className="font-mono">selling = cost / (1 - target)</span>.
            At {(marginPct * 100).toFixed(0)}% margin, a 100 Ft cost item will be priced at{' '}
            <span className="font-mono font-semibold">
              {marginPct < 1 ? (100 / (1 - marginPct)).toFixed(2) : 'infinity'} Ft
            </span>.
          </p>

          <div className="mt-4 pt-4 border-t border-gray-100">
            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={handleApplyMargin}
                disabled={applyingMargin}
                className="bg-amber-500 text-white px-4 py-2 rounded text-sm font-medium hover:bg-amber-600 disabled:opacity-50"
              >
                {applyingMargin ? 'Repricing...' : `Apply ${(marginPct * 100).toFixed(0)}% to all existing products`}
              </button>
              {applyMarginResult && (
                <span className="text-sm text-green-700 font-medium">
                  {applyMarginResult.updated} product{applyMarginResult.updated !== 1 ? 's' : ''} repriced
                  {applyMarginResult.skipped > 0 && `, ${applyMarginResult.skipped} skipped`}
                </span>
              )}
              {applyMarginError && (
                <span className="text-sm text-red-600">{applyMarginError}</span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              Recalculates selling price for every product using weighted-average purchase cost
              from intake events, or the original creation price as fallback.
            </p>
          </div>
        </div>
      </section>

      {/* Replenishment Engine */}
      <section className="bg-white rounded-lg border border-gray-200 mb-6 overflow-hidden">
        <div className="px-5 py-3 bg-gray-50 border-b">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
            Replenishment Engine
          </h2>
        </div>
        <div className="px-5 py-5 space-y-5">

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Target stock days
              <Badge label="target_days" isOverride={isOverride('replenishment_target_days')} />
            </label>
            <input
              type="number" min={1} max={365}
              value={targetDays}
              onChange={e => setTargetDays(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <p className="text-xs text-gray-400 mt-1">
              How many days of demand the solver should cover when recommending orders.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Supplier lead time (days)
              <Badge label="lead_time" isOverride={isOverride('replenishment_lead_time_days')} />
            </label>
            <input
              type="number" min={1} max={90}
              value={leadTimeDays}
              onChange={e => setLeadTimeDays(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <p className="text-xs text-gray-400 mt-1">
              Expected days between placing an order and receiving stock.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Weekly purchasing budget (Ft)
              <Badge label="weekly_budget" isOverride={isOverride('replenishment_weekly_budget')} />
            </label>
            <input
              type="number" min={1000} step={1000}
              value={weeklyBudget}
              onChange={e => setWeeklyBudget(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <p className="text-xs text-gray-400 mt-1">
              Maximum total spend per MILP run. When binding, the solver prioritises
              near-stockout products by urgency weight — a bounded integer knapsack optimisation.
            </p>
          </div>

        </div>
      </section>

      {/* Inventory Costing */}
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
                  type="radio" name="costing" value={opt}
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

      {/* AI Invoice Pipeline */}
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
              type="range" min={0} max={1} step={0.05}
              value={confidenceThreshold}
              onChange={e => setConfidenceThreshold(e.target.value)}
              className="flex-1 accent-indigo-600"
            />
            <span className="w-12 text-center font-mono text-sm font-semibold text-gray-700">
              {(parseFloat(confidenceThreshold) * 100).toFixed(0)}%
            </span>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Line items with confidence below this value are flagged for manager review.
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
          {saving ? 'Saving...' : 'Save settings'}
        </button>
        {saved && (
          <span className="text-green-600 text-sm font-medium">
            Settings saved
          </span>
        )}
      </div>

      {/* Current effective values */}
      {config && (
        <div className="mt-8 bg-gray-50 border rounded-lg px-5 py-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Current effective values
          </h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt className="text-gray-500">Margin target</dt>
            <dd className="font-mono font-medium text-gray-900">
              {(config.margin_target * 100).toFixed(0)}%
            </dd>
            <dt className="text-gray-500">Target stock days</dt>
            <dd className="font-mono font-medium text-gray-900">{config.replenishment_target_days} days</dd>
            <dt className="text-gray-500">Supplier lead time</dt>
            <dd className="font-mono font-medium text-gray-900">{config.replenishment_lead_time_days} days</dd>
            <dt className="text-gray-500">Weekly budget</dt>
            <dd className="font-mono font-medium text-gray-900">
              {config.replenishment_weekly_budget.toLocaleString('hu-HU')} Ft
            </dd>
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
