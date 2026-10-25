import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { API_BASE_URL } from '../api'

const API_BASE = API_BASE_URL

// Raw axios (no interceptors) so auth calls never trigger the 401 logout loop
const http = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
  timeout: 30000,
})

export const TOKEN_KEY = 'gtm_access_token'
export const REFRESH_KEY = 'gtm_refresh_token'

function storeTokens({ access_token, refresh_token }) {
  localStorage.setItem(TOKEN_KEY, access_token)
  localStorage.setItem(REFRESH_KEY, refresh_token)
}

function clearTokens() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

function authError(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(i => i?.msg || String(i)).join(', ')
  return 'Something went wrong. Please try again.'
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [initializing, setInitializing] = useState(true)
  const queryClient = useQueryClient()

  // Restore session from a persisted token on first load
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) {
      setInitializing(false)
      return
    }
    http.get('/auth/me', { headers: { Authorization: `Bearer ${token}` } })
      .then(res => {
        if (res.data?.authenticated && res.data?.user) setUser(res.data.user)
        else clearTokens()
      })
      .catch(() => clearTokens())
      .finally(() => setInitializing(false))
  }, [])

  // Any 401 from the API instance means the session expired — log out locally
  useEffect(() => {
    const onUnauthorized = () => {
      clearTokens()
      setUser(null)
      queryClient.clear()
    }
    window.addEventListener('auth:unauthorized', onUnauthorized)
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized)
  }, [queryClient])

  const login = useCallback(async (email, password) => {
    queryClient.clear()
    const res = await http.post('/auth/login', { email, password })
    storeTokens(res.data)
    setUser(res.data.user)
    return res.data.user
  }, [queryClient])

  const register = useCallback(async (name, email, password, confirmPassword) => {
    queryClient.clear()
    const res = await http.post('/auth/register', {
      name,
      email,
      password,
      confirm_password: confirmPassword,
    })
    storeTokens(res.data)
    setUser(res.data.user)
    return res.data.user
  }, [queryClient])

  const logout = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_KEY)
    clearTokens()
    setUser(null)
    queryClient.clear()
    if (token) {
      try {
        await http.post('/auth/logout', {}, { headers: { Authorization: `Bearer ${token}` } })
      } catch {
        /* token already invalid — nothing else to do */
      }
    }
  }, [queryClient])

  return (
    <AuthContext.Provider value={{ user, initializing, login, register, logout, authError }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
