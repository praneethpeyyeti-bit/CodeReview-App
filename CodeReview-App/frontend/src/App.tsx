import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ReviewProvider } from './context/ReviewContext';
import HomePage from './pages/HomePage';
import ResultsPage from './pages/ResultsPage';

function App() {
  return (
    <BrowserRouter>
      <ReviewProvider>
        <div className="min-h-screen bg-mesh-bg bg-ui-g50 flex flex-col">
          {/* Header */}
          <header className="bg-hero-gradient text-white shadow-elevated sticky top-0 z-40">
            <div className="max-w-[1400px] mx-auto px-6 py-0 flex items-center justify-between h-16">
              <div className="flex items-center gap-4">
                <img src="/uipath-logo.png" alt="UiPath" className="h-7 invert brightness-0 invert" />
                <div className="h-8 w-px bg-white/20" />
                <div>
                  <h1 className="text-base font-bold tracking-tight leading-tight">Code Review</h1>
                  <p className="text-[10px] text-gray-400 font-medium tracking-wide uppercase">AI-Powered XAML Analysis</p>
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
                <span>UiPath AI Trust Layer</span>
              </div>
            </div>
          </header>

          {/* Main content */}
          <main className="max-w-[1400px] mx-auto px-6 py-8 flex-1 w-full">
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/results" element={<ResultsPage />} />
            </Routes>
          </main>

          {/* Footer */}
          <footer className="border-t border-ui-g200 bg-white/80 backdrop-blur-sm mt-auto">
            <div className="max-w-[1400px] mx-auto px-6 py-4 flex items-center justify-between">
              <p className="text-xs text-ui-g400">Powered by UiPath AI Trust Layer</p>
              <p className="text-xs text-ui-g400">47 Workflow Analyzer Rules</p>
            </div>
          </footer>
        </div>
      </ReviewProvider>
    </BrowserRouter>
  );
}

export default App;
