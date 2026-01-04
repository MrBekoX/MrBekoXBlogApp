'use client';

import { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

/**
 * Error Boundary component to catch and handle React rendering errors.
 * Prevents the entire app from crashing when a component throws an error.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Log error for debugging and monitoring
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  handleReload = () => {
    // Reset state and reload the page
    this.setState({ hasError: false, error: undefined });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback or default error UI
      return this.props.fallback ?? (
        <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-background">
          <div className="max-w-md text-center">
            <div className="mb-6">
              <svg
                className="w-16 h-16 mx-auto text-destructive"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
            </div>
            <h1 className="text-2xl font-bold mb-4 text-foreground">
              Bir hata oluştu
            </h1>
            <p className="text-muted-foreground mb-6">
              Sayfa yüklenirken beklenmeyen bir sorun oluştu. 
              Lütfen sayfayı yenileyin veya daha sonra tekrar deneyin.
            </p>
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <details className="mb-6 text-left p-4 bg-muted rounded-lg">
                <summary className="cursor-pointer text-sm font-medium">
                  Hata Detayları (Geliştirici)
                </summary>
                <pre className="mt-2 text-xs overflow-auto text-destructive">
                  {this.state.error.message}
                  {'\n'}
                  {this.state.error.stack}
                </pre>
              </details>
            )}
            <button
              onClick={this.handleReload}
              className="px-6 py-3 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors font-medium"
            >
              Sayfayı Yenile
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
