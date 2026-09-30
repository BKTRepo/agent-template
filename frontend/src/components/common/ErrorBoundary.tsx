import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { Button } from '@heroui/react'

interface Props {
  children: ReactNode
}
interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen items-center justify-center">
          <div className="text-center p-8 max-w-md">
            <h2 className="text-lg font-semibold text-danger mb-2">出错了</h2>
            <p className="text-sm text-muted mb-4">
              {this.state.error?.message || '未知错误'}
            </p>
            <Button
              variant="outline"
              size="sm"
              onPress={() => {
                this.setState({ hasError: false, error: null })
                window.location.hash = '#/'
                window.location.reload()
              }}
            >
              刷新页面
            </Button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
