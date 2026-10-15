import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { History as HistoryIcon, Building2, MapPin, Briefcase, Tag, ChevronRight, Trash2, AlertTriangle, X } from 'lucide-react'
import { fetchInputHistory, deleteInputHistory, deleteAllInputHistory } from '../api'
import { useSession } from '../context/SessionContext'
import { useAuth } from '../context/AuthContext'

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
  const navigate = useNavigate()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { activeSessionId, setActiveSessionId } = useSession()

  const [deleteModal, setDeleteModal] = useState({ open: false, type: 'single', item: null })
  const [deleteError, setDeleteError] = useState(null)

  const { data: history = [], isLoading, isError } = useQuery({
    queryKey: ['input-history', user?.id],
    queryFn: fetchInputHistory,
    refetchInterval: 10_000,
  })

  // Single delete mutation
  const deleteSingleMut = useMutation({
    mutationFn: (id) => deleteInputHistory(id),
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['input-history'] })
      if (activeSessionId === variables) {
        setActiveSessionId(null)
      }
      setDeleteModal({ open: false, type: 'single', item: null })
      setDeleteError(null)
    },
    onError: (err) => {
      setDeleteError(err.response?.data?.detail || err.message || 'Failed to delete search history.')
    }
  })

  // Delete all mutation
  const deleteAllMut = useMutation({
    mutationFn: () => deleteAllInputHistory(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['input-history'] })
      setActiveSessionId(null)
      setDeleteModal({ open: false, type: 'all', item: null })
      setDeleteError(null)
    },
    onError: (err) => {
      setDeleteError(err.response?.data?.detail || err.message || 'Failed to delete all search history.')
    }
  })

  const confirmDelete = () => {
    setDeleteError(null)
    if (deleteModal.type === 'single' && deleteModal.item) {
      deleteSingleMut.mutate(deleteModal.item.id)
    } else if (deleteModal.type === 'all') {
      deleteAllMut.mutate()
    }
  }

  const isDeleting = deleteSingleMut.isPending || deleteAllMut.isPending

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
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
              All past GTM pipeline searches — newest first
            </p>
          </div>
        </div>

        {/* Delete All Action */}
        {!isLoading && !isError && history.length > 0 && (
          <button
            onClick={() => {
              setDeleteError(null)
              setDeleteModal({ open: true, type: 'all', item: null })
            }}
            style={{
              fontSize: '11px', color: '#EF4444', fontWeight: 600,
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.22)',
              borderRadius: '8px', padding: '6px 12px', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: '6px',
              transition: 'background 0.2s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.15)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.08)'}
          >
            <Trash2 size={13} />
            <span>Delete All History</span>
          </button>
        )}
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
              {/* Top row: company name + actions */}
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
                    {item.our_company_name}
                  </span>
                  {item.target_company_size && (
                    <span style={{
                      fontSize: '10px', color: 'var(--c-text3)', background: 'var(--c-surface2)',
                      border: '1px solid var(--c-border)', borderRadius: '6px',
                      padding: '1px 6px',
                    }}>
                      Size: {item.target_company_size}
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
                      onClick={() => {
                        setActiveSessionId(item.id)
                        navigate('/contacts')
                      }}
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

                  {/* Delete Button for Single Item */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setDeleteError(null)
                      setDeleteModal({ open: true, type: 'single', item })
                    }}
                    title="Delete this search history"
                    style={{
                      fontSize: '10px', color: 'var(--c-text3)',
                      background: 'var(--c-surface2)', border: '1px solid var(--c-border)',
                      borderRadius: '6px', padding: '3px 6px', cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      transition: 'all 0.2s', outline: 'none',
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.color = '#EF4444'
                      e.currentTarget.style.borderColor = 'rgba(239,68,68,0.35)'
                      e.currentTarget.style.background = 'rgba(239,68,68,0.1)'
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.color = 'var(--c-text3)'
                      e.currentTarget.style.borderColor = 'var(--c-border)'
                      e.currentTarget.style.background = 'var(--c-surface2)'
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>

              {/* Fields */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 24px' }}>
                <FieldChip icon={Briefcase} label="Services"   value={item.our_services}   />
                <FieldChip icon={MapPin}    label="Location"   value={item.target_location}   />
                <FieldChip icon={ChevronRight} label="Roles"    value={item.target_job_titles}  />
                <FieldChip icon={Building2} label="Industries" value={item.target_industries} />
                <FieldChip icon={Tag}       label="Keywords"   value={item.target_keywords}   />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Confirmation Dialog Modal */}
      {deleteModal.open && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0, 0, 0, 0.6)', backdropFilter: 'blur(3px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px'
        }}>
          <div style={{
            background: 'var(--c-surface)',
            border: '1px solid var(--c-border)',
            borderRadius: '14px', maxWidth: '440px', width: '100%',
            padding: '24px', boxShadow: '0 20px 40px rgba(0,0,0,0.4)',
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{
                  width: '36px', height: '36px', borderRadius: '10px',
                  background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#EF4444'
                }}>
                  <AlertTriangle size={18} />
                </div>
                <div>
                  <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--c-text)', margin: 0 }}>
                    {deleteModal.type === 'all' ? 'Delete All Search History?' : 'Delete this search history?'}
                  </h3>
                  <p style={{ fontSize: '11px', color: 'var(--c-text3)', margin: '2px 0 0' }}>
                    {deleteModal.type === 'all'
                      ? 'Permanently clear all search history runs'
                      : `Search #${deleteModal.item?.id}: ${deleteModal.item?.our_company_name}`}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setDeleteModal({ open: false, type: 'single', item: null })}
                style={{ background: 'none', border: 'none', color: 'var(--c-text3)', cursor: 'pointer', padding: '4px' }}
              >
                <X size={16} />
              </button>
            </div>

            <div style={{
              background: 'var(--c-surface2)', borderRadius: '10px', padding: '12px 14px',
              fontSize: '12px', color: 'var(--c-text2)', lineHeight: 1.5, marginBottom: '20px',
              border: '1px solid var(--c-border)'
            }}>
              {deleteModal.type === 'all' ? (
                <>
                  <p style={{ margin: '0 0 8px 0', fontWeight: 600, color: '#EF4444' }}>
                    Are you sure you want to delete all {history.length} search entries?
                  </p>
                  <p style={{ margin: 0, color: 'var(--c-text3)' }}>
                    This will remove all intake form history records for your account. 
                    <strong> Your contacts, pipeline deals, signals, and outreach drafts will be safely preserved.</strong>
                  </p>
                </>
              ) : (
                <>
                  <p style={{ margin: '0 0 6px 0' }}>
                    This will delete this search history record (<strong>{deleteModal.item?.our_company_name}</strong>).
                  </p>
                  <p style={{ margin: 0, color: 'var(--c-text3)' }}>
                    Associated search links will be cleaned up. <strong>Contacts, deals, and outreach history are safely preserved and will not be deleted.</strong>
                  </p>
                </>
              )}
            </div>

            {deleteError && (
              <div style={{
                background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)',
                color: '#EF4444', borderRadius: '8px', padding: '10px 12px', fontSize: '12px', marginBottom: '16px'
              }}>
                {deleteError}
              </div>
            )}

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                type="button"
                onClick={() => setDeleteModal({ open: false, type: 'single', item: null })}
                disabled={isDeleting}
                style={{
                  fontSize: '12px', fontWeight: 600, color: 'var(--c-text2)',
                  background: 'var(--c-surface2)', border: '1px solid var(--c-border)',
                  borderRadius: '8px', padding: '7px 14px', cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={isDeleting}
                style={{
                  fontSize: '12px', fontWeight: 600, color: '#fff',
                  background: '#EF4444', border: 'none',
                  borderRadius: '8px', padding: '7px 16px', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: '6px',
                  boxShadow: '0 2px 6px rgba(239,68,68,0.3)',
                  opacity: isDeleting ? 0.6 : 1,
                }}
              >
                <Trash2 size={13} />
                <span>{isDeleting ? 'Deleting…' : (deleteModal.type === 'all' ? 'Delete All' : 'Delete History')}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
