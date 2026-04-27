import { Component, ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 p-8">
          <div className="bg-white rounded-lg shadow-md p-8 max-w-lg w-full">
            <h1 className="text-lg font-bold text-red-600 mb-2">Something went wrong</h1>
            <p className="text-sm text-gray-600 mb-4">
              The page crashed with the following error:
            </p>
            <pre className="text-xs bg-gray-100 rounded p-3 overflow-x-auto text-red-700 whitespace-pre-wrap">
              {this.state.error.message}
            </pre>
            <button
              onClick={() => window.location.reload()}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
            >
              Reload page
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
