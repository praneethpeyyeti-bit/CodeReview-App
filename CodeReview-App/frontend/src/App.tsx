import ReviewPage from './pages/ReviewPage';

function App() {
  return (
    <div className="min-h-screen bg-ui-g50">
      {/* Header */}
      <header className="bg-ui-navy text-white px-6 py-4 shadow-lg">
        <div className="max-w-7xl mx-auto flex items-center gap-4">
          {/* UiPath Logo */}
          <div className="flex items-center gap-3">
            <img src="/uipath-logo.png" alt="UiPath" className="h-8 invert brightness-0 invert" />
            <div className="border-l border-white/30 pl-3">
              <h1 className="text-lg font-semibold tracking-tight">
                Code Review
              </h1>
              <p className="text-xs text-gray-400">
                AI-powered XAML workflow analysis
              </p>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        <ReviewPage />
      </main>

      {/* Footer */}
      <footer className="border-t border-ui-g200 bg-white mt-8">
        <div className="max-w-7xl mx-auto px-6 py-3 text-xs text-ui-g400">
          Powered by UiPath AI Trust Layer
        </div>
      </footer>
    </div>
  );
}

export default App;
