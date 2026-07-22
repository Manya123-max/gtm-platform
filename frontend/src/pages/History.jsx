import { useQuery } from '@tanstack/react-query'
import { History as HistoryIcon, Building2, MapPin, Briefcase, Tag, ChevronRight } from 'lucide-react'
import { fetchInputHistory } from '../api'
import { useSession } from '../context/SessionContext'

function FieldChip({ icon: Icon, label, value }) {
  if (!value) return null
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', marginBottom: '4px' }}>
      <Icon size={12} style={{ color: 'var(--c-text3)', marginTop: '2px', flexShrink: 0 }} />
      <div style={{ minWidth: 0 }}>
        <span style={{ fontSize: '10px', color: 'var(--c-text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: '4px' }}>
          {label}:
        </span>
        <span style={{ fontSize: '12px', color: 'var(--c-text2)' }}>{value}</span>
      </div>
    </div>
  )
}

export default function History() {
  const { activeSessionId, setActiveSessionId } = useSession()
  const { data: history = [], isLoading, isError } = useQuery({
    queryKey: ['input-history'],
    queryFn: fetchInputHistory,
    refetchInterval: 10_000,
  })

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
          <div
            style={{
              width: '36px', height: '36px', borderRadius: '10px',
              background: 'linear-gradient(135deg, #0A67FF22, #00C8FF22)',
              border: '1px solid rgba(10,103,255,0.25)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <HistoryIcon size={18} color="#5DA8FF" />
          </div>
          <div>
            <h1 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--c-text)', lineHeight: 1.2 }}>
              Search History
            </h1>
            <p style={{ fontSize: '12px', color: 'var(--c-text3)', marginTop: '2px' }}>
              All past GTM pipeline searches · newest first
            </p>
          </div>
        </div>
      </div>

      {/* States */}
      {isLoading && (
        <div style={{ textAlign: 'center', padding: '60px', color: 'var(--c-text3)' }}>
          Loading history…
        </div>
      )}

      {isError && (
        <div style={{
          padding: '16px', borderRadius: '10px', background: 'rgba(239,68,68,0.1)',
          border: '1px solid rgba(239,68,68,0.2)', color: '#F87171', fontSize: '13px'
        }}>
          Failed to load history. Please try refreshing.
        </div>
      )}

      {!isLoading && !isError && history.length === 0 && (
        <div style={{
          padding: '60px', textAlign: 'center', borderRadius: '12px',
          background: 'var(--c-surface)', border: '1px solid var(--c-border)',
        }}>
          <HistoryIcon size={32} style={{ color: 'var(--c-text3)', margin: '0 auto 12px' }} />
          <div style={{ fontSize: '15px', color: 'var(--c-text2)', marginBottom: '6px' }}>No searches yet</div>
          <div style={{ fontSize: '13px', color: 'var(--c-text3)' }}>
            Submit the Input form to start a GTM pipeline run. It will appear here.
          </div>
        </div>
      )}

      {/* History list */}
      {!isLoading && !isError && history.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {history.map((item, idx) => (
            <div
              key={item.id}
              style={{
                background: 'var(--c-surface)',
                border: '1px solid var(--c-border)',
                borderRadius: '12px',
                padding: '16px 18px',
                transition: 'border-color 0.2s, box-shadow 0.2s',
                cursor: 'default',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = 'rgba(10,103,255,0.35)'
                e.currentTarget.style.boxShadow = '0 0 0 1px rgba(10,103,255,0.12)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = 'var(--c-border)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              {/* Top row: company + index badge */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{
                    width: '28px', height: '28px', borderRadius: '8px',
                    background: 'linear-gradient(135deg, #0A67FF, #00C8FF)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    <Building2 size={14} color="white" />
                  </div>
                  <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--c-text)' }}>
                    {item.company_name}
                  </span>
                  {item.company_size && (
                    <span style={{
                      fontSize: '10px', color: 'var(--c-text3)', background: 'var(--c-surface2)',
                      border: '1px solid var(--c-border)', borderRadius: '6px',
                      padding: '1px 6px',
                    }}>
                      {item.company_size} employees
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {item.id === activeSessionId ? (
                    <span style={{
                      fontSize: '10px', color: 'var(--c-green)', fontWeight: 600,
                      background: 'rgba(5,150,105,0.1)', border: '1px solid rgba(5,150,105,0.25)',
                      borderRadius: '6px', padding: '2px 8px', display: 'inline-flex', alignItems: 'center', gap: '4px'
                    }}>
                      ● Active
                    </span>
                  ) : (
                    <button
                      onClick={() => setActiveSessionId(item.id)}
                      style={{
                        fontSize: '10px', color: 'var(--c-blue)', fontWeight: 600,
                        background: 'rgba(10,103,255,0.08)', border: '1px solid rgba(10,103,255,0.22)',
                        borderRadius: '6px', padding: '2px 10px', cursor: 'pointer',
                        transition: 'background 0.2s', outline: 'none',
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(10,103,255,0.16)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'rgba(10,103,255,0.08)'}
                    >
                      View Search
                    </button>
                  )}
                  <span style={{
                    fontSize: '10px', color: 'var(--c-text3)',
                    background: 'var(--c-surface2)', border: '1px solid var(--c-border)',
                    borderRadius: '6px', padding: '2px 8px',
                  }}>
                    #{history.length - idx}
                  </span>
                </div>
              </div>

              {/* Fields */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 24px' }}>
                <FieldChip icon={MapPin}    label="Location"  value={item.location}   />
                <FieldChip icon={Briefcase} label="Roles"     value={item.job_title}  />
                <FieldChip icon={ChevronRight} label="Services" value={item.services} />
                <FieldChip icon={Tag}       label="Keywords"  value={item.keywords}   />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
