import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'                                  // ← THIS WAS MISSING
import Layout from './components/layout/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import Dashboard from './pages/Dashboard'
import Contacts from './pages/Contacts'
import ContactDetail from './pages/ContactDetail'
import { Deals, Outreach, Content, Revenue, Agents } from './pages/index'
import InputForm from './components/InputForm'
import History from './pages/History'
import Settings from './pages/Settings'
import Notifications from './pages/Notifications'
import Login from './pages/Login'
import Register from './pages/Register'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import ProtectedRoute from './components/ProtectedRoute'
import { SessionProvider } from './context/SessionContext'
import { AuthProvider } from './context/AuthContext'

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={qc}>
      <AuthProvider>
        <SessionProvider>
        <BrowserRouter>
          <Routes>
            {/* Public auth routes */}
            <Route path="/login"           element={<Login initialMode="login" />} />
            <Route path="/register"        element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password"  element={<ResetPassword />} />

            {/* Protected application routes */}
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<Layout />}>
                <Route index element={<Navigate to="/agents" replace />} />
                <Route path="agents"       element={<Agents />} />
                <Route path="dashboard"    element={<Dashboard />} />
                <Route path="contacts"     element={<Contacts />} />
                <Route path="contacts/:id" element={<ContactDetail />} />
                <Route path="deals"        element={<Deals />} />
                <Route path="outreach"     element={<Outreach />} />
                <Route path="content"      element={<Content />} />
                <Route path="revenue"      element={<Revenue />} />
                <Route path="input"        element={<InputForm />} />
                <Route path="history"      element={<History />} />
                <Route path="settings"     element={<Settings />} />
                <Route path="profile"      element={<Settings />} />
                <Route path="notifications" element={<Notifications />} />
              </Route>
            </Route>

            {/* Unknown routes → protected root (which lands on login if unauthenticated) */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
        </SessionProvider>
      </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
)