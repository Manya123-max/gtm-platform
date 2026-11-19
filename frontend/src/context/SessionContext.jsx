import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import api from '../api'
import { useAuth } from './AuthContext'

const SessionContext = createContext({
  activeSessionId: null,
  setActiveSessionId: () => {},
  setActiveSession: () => {},
  activeSessionData: null,
  setActiveSessionData: () => {},
  ourCompanyName: '',
  isLoading: true,
})

export function SessionProvider({ children }) {
  const { user } = useAuth()
  const [activeSessionId, setActiveSessionIdState] = useState(null)
  const [activeSessionData, setActiveSessionData] = useState(null)
  const [ourCompanyName, setOurCompanyName] = useState('')
  const [isLoading, setIsLoading] = useState(true)

  // Re-fetch active session whenever the authenticated user changes
  useEffect(() => {
    if (!user) {
      setActiveSessionIdState(null)
      setActiveSessionData(null)
      setOurCompanyName('')
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    api.get('/active-session')
      .then(res => {
        setActiveSessionIdState(res.data.user_input_id ?? null)
      })
      .catch(() => {
        setActiveSessionIdState(null)
        setActiveSessionData(null)
      })
      .finally(() => setIsLoading(false))
  }, [user])

  // Fetch session details whenever the active session ID changes
  useEffect(() => {
    if (activeSessionId) {
      api.get(`/sessions/${activeSessionId}`)
        .then(res => {
          setActiveSessionData(res.data || null)
          setOurCompanyName(res.data?.our_company_name || '')
        })
        .catch(() => {
          setActiveSessionData(null)
          setOurCompanyName('')
        })
    } else {
      setActiveSessionData(null)
      setOurCompanyName('')
    }
  }, [activeSessionId])

  const setActiveSessionId = useCallback((id) => {
    setActiveSessionIdState(id)
  }, [])

  const setActiveSession = useCallback((sessionOrId) => {
    if (typeof sessionOrId === 'object' && sessionOrId !== null) {
      setActiveSessionIdState(sessionOrId.id)
      setActiveSessionData(sessionOrId)
      setOurCompanyName(sessionOrId.our_company_name || '')
    } else {
      setActiveSessionIdState(sessionOrId)
    }
  }, [])

  return (
    <SessionContext.Provider value={{
      activeSessionId,
      setActiveSessionId,
      setActiveSession,
      activeSessionData,
      setActiveSessionData,
      ourCompanyName,
      isLoading,
    }}>
      {children}
    </SessionContext.Provider>
  )
}

export function useSession() {
  return useContext(SessionContext)
}
