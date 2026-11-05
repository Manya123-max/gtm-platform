import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import Layout from './components/layout/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import ProtectedRoute from './components/ProtectedRoute'
import { SessionProvider } from './context/SessionContext'
import { AuthProvider } from './context/AuthContext'

// Lazy-loaded route components for optimal bundle splitting
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Contacts = lazy(() => import('./pages/Contacts'))
const ContactDetail = lazy(() => import('./pages/ContactDetail'))
const Deals = lazy(() => import('./pages/Deals'))
const Outreach = lazy(() => import('./pages/Outreach'))
const Content = lazy(() => import('./pages/Content'))
const Revenue = lazy(() => import('./pages/Revenue'))
const Agents = lazy(() => import('./pages/Agents'))
const InputForm = lazy(() => import('./components/InputForm'))
const History = lazy(() => import('./pages/History'))
const Settings = lazy(() => import('./pages/Settings'))
const Notifications = lazy(() => import('./pages/Notifications'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const ResetPassword = lazy(() => import('./pages/ResetPassword'))

function PageFallback() {
  return (
    <div className="flex min-h-[40vh] w-full items-center justify-center">
      <div className="h-7 w-7 animate-spin rounded-full border-2 border-[#BFCFEA] border-t-[#0A67FF]" />
    </div>
  )
}

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
          <Suspense fallback={<PageFallback />}>
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
          </Suspense>
        </BrowserRouter>
        </SessionProvider>
      </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
)
