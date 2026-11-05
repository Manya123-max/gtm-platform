import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import api from '../api'
import { useAuth } from './AuthContext'

const SessionContext = createContext({
  activeSessionId: null,
  setActiveSessionId: () => {},
  isLoading: true,
})

export function SessionProvider({ children }) {
  const { user } = useAuth()
  const [activeSessionId, setActiveSessionIdState] = useState(null)
  const [ourCompanyName, setOurCompanyName] = useState('')
  const [isLoading, setIsLoading] = useState(true)

  // Re-fetch active session whenever the authenticated user changes
  useEffect(() => {
    if (!user) {
      setActiveSessionIdState(null)
      setOurCompanyName('')
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    api.get('/active-session')
      .then(res => {
        setActiveSessionIdState(res.data.user_input_id ?? null)
      })
      .catch(() => setActiveSessionIdState(null))
      .finally(() => setIsLoading(false))
  }, [user])

  // Fetch session details whenever the active session ID changes
  useEffect(() => {
    if (activeSessionId) {
      api.get(`/sessions/${activeSessionId}`)
        .then(res => {
          setOurCompanyName(res.data.our_company_name || '')
        })
        .catch(() => setOurCompanyName(''))
    } else {
      setOurCompanyName('')
    }
  }, [activeSessionId])

  const setActiveSessionId = useCallback((id) => {
    setActiveSessionIdState(id)
  }, [])

  return (
    <SessionContext.Provider value={{ activeSessionId, setActiveSessionId, ourCompanyName, isLoading }}>
      {children}
    </SessionContext.Provider>
  )
}

export function useSession() {
  return useContext(SessionContext)
}
