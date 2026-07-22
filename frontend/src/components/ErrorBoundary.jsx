import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('UI render failed', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="min-h-screen bg-[#0B0F1A] text-gray-100 p-6">
        <div className="max-w-3xl mx-auto border border-red-900/50 bg-red-950/20 rounded-lg p-5">
          <h1 className="text-lg font-semibold text-red-300">UI render failed</h1>
          <p className="text-sm text-red-100/80 mt-2">
            The app caught a frontend runtime error instead of showing a blank page.
          </p>
          <pre className="mt-4 overflow-auto rounded bg-black/40 p-3 text-xs text-red-100 whitespace-pre-wrap">
            {this.state.error?.stack || this.state.error?.message || String(this.state.error)}
          </pre>
        </div>
      </div>
    )
  }
}
