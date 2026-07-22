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

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={qc}>
        <BrowserRouter>
          <Routes>
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
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
)