// ── Deals Page ────────────────────────────────────────────────────────────
export { default as Deals } from './Deals'

// ── Revenue Page ──────────────────────────────────────────────────────────
export function Revenue() {
  const { activeSessionId, ourCompanyName } = useSession()
  const { data: forecast } = useQuery({ queryKey: ['forecast'], queryFn: fetchForecast })
  const { data: deals = [] } = useQuery({
    queryKey: ['deals', activeSessionId],
    queryFn: () => fetchDeals(activeSessionId != null ? { user_input_id: activeSessionId } : {}),
  })
  const { data: metrics = {} } = useQuery({
    queryKey: ['funnel-metrics', 30],
    queryFn: () => fetchFunnelMetrics(30),
  })

  const funnelData = Object.entries(metrics).map(([k, v]) => ({
    name: k.replace(/_/g, ' '),
    count: v,
  })).sort((a, b) => b.count - a.count).slice(0, 8)

  const stages = forecast?.stage_conversion_rates
    ? Object.entries(forecast.stage_conversion_rates).map(([k, v]) => ({
      stage: k.replace(/_to_.*/, '').replace(/_/g, ' '),
      rate: Math.round(v * 100),
    }))
    : []

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6 flex justify-between items-center">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">
            Revenue Intelligence {ourCompanyName ? `for ${ourCompanyName}` : ''}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">A7 forecast model — Multi-factor deal-level pipeline intelligence</p>
        </div>
        {forecast?.current_pipeline_value != null && (
          <div className="text-right">
            <div className="text-xs text-gray-400">Total Active Pipeline</div>
            <div className="text-lg font-bold text-gray-100">${Math.round(forecast.current_pipeline_value).toLocaleString()}</div>
          </div>
        )}
      </div>

      {/* Forecast cards */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {[
          { label: '30-Day Forecast', val: forecast?.forecast_30d, note: 'Near-term closing expected value' },
          { label: '60-Day Forecast', val: forecast?.forecast_60d, note: 'Mid-term velocity-weighted forecast' },
          { label: '90-Day Forecast', val: forecast?.forecast_90d, note: 'Full quarterly pipeline conversion' },
        ].map(f => (
          <div key={f.label} className="stat-card">
            <div className="stat-label">{f.label}</div>
            <div className="stat-value text-blue-400 font-bold">
              {f.val != null ? `$${Math.round(f.val).toLocaleString()}` : '—'}
            </div>
            <div className="text-[11px] text-gray-500 mt-1">{f.note}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        {/* Constraint / Pipeline Health */}
        {forecast?.bottleneck_stage ? (
          <div className="card border-amber-800/40 bg-amber-900/10">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle size={14} className="text-amber-400" />
              <span className="text-sm font-medium text-amber-300">Pipeline Constraint Identified</span>
            </div>
            <div className="text-sm text-amber-400 font-medium capitalize mb-1">{forecast.bottleneck_stage} Stage Bottleneck</div>
            <div className="text-xs text-gray-400 mb-3">{forecast.bottleneck_description}</div>
            <div className="text-xs text-blue-400 font-medium bg-blue-950/40 p-2.5 rounded border border-blue-900/30">
              <strong className="text-blue-300">Recommended Growth Lever:</strong> {forecast.recommended_lever}
            </div>
          </div>
        ) : (
          <div className="card border-slate-800/60 bg-slate-900/20">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium text-slate-300">Pipeline Health & Levers</span>
            </div>
            <div className="text-sm text-slate-200 font-medium mb-1">
              {forecast?.bottleneck_description || "No active bottleneck detected"}
            </div>
            <div className="text-xs text-gray-400 mb-3">
              {forecast?.recommended_lever || "Pipeline converting healthily across stages."}
            </div>
          </div>
        )}

        {/* Stage conversion rates */}
        <div className="card">
          <div className="section-title">Stage Conversion Rates & Velocity</div>
          <div className="section-sub">Current transition probabilities (A7 calibrated model)</div>
          <div className="space-y-2 mt-2">
            {stages.map(s => (
              <div key={s.stage}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-400 capitalize">{s.stage} Transition</span>
                  <span className="text-gray-200 font-medium">{s.rate}%</span>
                </div>
                <div className="score-bar">
                  <div className="score-fill bg-blue-500" style={{ width: `${s.rate}%` }} />
                </div>
              </div>
            ))}
            {stages.length === 0 && (
              <div className="text-sm text-gray-600 text-center py-4">Run A7 to see conversion rates</div>
            )}
          </div>
        </div>
      </div>

      {/* Deal-Level Revenue Predictions */}
      <div className="card mb-6">
        <div className="flex justify-between items-center mb-2">
          <div>
            <div className="section-title">Deal-Level Revenue Predictions</div>
            <div className="section-sub">Individual deal expected values based on BANT qualification, health score & time-in-stage decay</div>
          </div>
          <span className="text-xs text-gray-400 bg-gray-800 px-2.5 py-1 rounded border border-gray-700">
            {deals.length} Active Deals
          </span>
        </div>

        {deals.length === 0 ? (
          <div className="text-sm text-gray-500 text-center py-6">No active deals recorded. Run A5 Deal Intelligence to sync pipeline.</div>
        ) : (
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-gray-800 text-gray-400 font-medium">
                  <th className="py-2.5 px-3">Deal / Company</th>
                  <th className="py-2.5 px-3">Stage</th>
                  <th className="py-2.5 px-3 text-right">Deal Value</th>
                  <th className="py-2.5 px-3 text-center">Win Probability</th>
                  <th className="py-2.5 px-3 text-right">Expected Revenue</th>
                  <th className="py-2.5 px-3">Next Best Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {deals.map(deal => {
                  const amt = deal.amount
                  const prob = deal.win_probability != null ? deal.win_probability : 35
                  const ev = amt != null ? (amt * prob) / 100 : null
                  return (
                    <tr key={deal.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="py-2.5 px-3">
                        <div className="font-medium text-gray-200">{deal.name}</div>
                        <div className="text-[11px] text-gray-500">{deal.contact?.company || 'Enterprise Account'}</div>
                      </td>
                      <td className="py-2.5 px-3">
                        <span className="inline-block px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide bg-blue-900/30 text-blue-300 border border-blue-800/40">
                          {deal.stage}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right font-medium text-gray-200">
                        {amt != null ? `$${Math.round(amt).toLocaleString()}` : <span className="text-gray-500 italic text-[11px]">Not available</span>}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <span className={`inline-block px-2 py-0.5 rounded font-bold text-xs ${prob >= 50 ? 'bg-emerald-900/30 text-emerald-400 border border-emerald-800/40' :
                            prob >= 30 ? 'bg-amber-900/30 text-amber-400 border border-amber-800/40' :
                              'bg-gray-800 text-gray-400 border border-gray-700'
                          }`}>
                          {Math.round(prob)}%
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right font-bold text-blue-400">
                        {ev != null ? `$${Math.round(ev).toLocaleString()}` : <span className="text-gray-500 italic text-[11px]">--</span>}
                      </td>
                      <td className="py-2.5 px-3 text-gray-400 max-w-xs truncate" title={deal.next_best_action || 'Review stage progression'}>
                        {deal.next_best_action || 'Schedule follow-up and review BANT criteria'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Activity breakdown */}
      {funnelData.length > 0 && (
        <div className="card">
          <div className="section-title">Activity Log (30 days)</div>
          <div className="section-sub">Events recorded in the Prospect Intelligence Graph</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={funnelData} layout="vertical" barSize={14}>
              <XAxis type="number" hide />
              <YAxis dataKey="name" type="category" tick={{ fill: '#6B7280', fontSize: 11 }} axisLine={false} tickLine={false} width={140} />
              <Tooltip contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="count" fill="#3B82F6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
export { default as Revenue } from './Revenue'

// ── Agents Control Page ───────────────────────────────────────────────────
export { default as Agents } from './Agents'

// ── Outreach Page ─────────────────────────────────────────────────────────
export { default as Outreach } from './Outreach'

// ── Content Page ──────────────────────────────────────────────────────────
export { default as Content } from './Content'
