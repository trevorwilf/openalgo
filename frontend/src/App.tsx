import { lazy, type ReactNode, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Providers } from '@/app/providers'
import { AuthSync } from '@/components/auth/AuthSync'
import { IndiaOnlyFeature } from '@/components/IndiaOnlyFeature'
import { FullWidthLayout } from '@/components/layout/FullWidthLayout'
import { Layout } from '@/components/layout/Layout'
import { PageLoader } from '@/components/ui/page-loader'
import { usePageTitle } from '@/hooks/usePageTitle'
import { useBrokerStore } from '@/stores/brokerStore'

/** Wrap an India-only route element so non-India brokers see a
 * structured "feature unavailable" empty state instead of a page
 * that 404s its sub-routes. */
function IndiaOnly({
  feature,
  rationale,
  children,
}: {
  feature: string
  rationale?: string
  children: ReactNode
}) {
  return (
    <IndiaOnlyFeature featureName={feature} rationale={rationale}>
      {children}
    </IndiaOnlyFeature>
  )
}

// Lazy load all pages for code splitting
// Public pages
const Home = lazy(() => import('@/pages/Home'))
const Faq = lazy(() => import('@/india_legacy/pages/Faq'))
const Setup = lazy(() => import('@/pages/Setup'))
const Login = lazy(() => import('@/pages/Login'))
const ResetPassword = lazy(() => import('@/pages/ResetPassword'))
const Download = lazy(() => import('@/pages/Download'))
const ServerError = lazy(() => import('@/pages/ServerError'))
const RateLimited = lazy(() => import('@/pages/RateLimited'))
const NotFound = lazy(() => import('@/pages/NotFound'))

// Broker auth
const BrokerSelect = lazy(() => import('@/pages/BrokerSelect'))
const BrokerTOTP = lazy(() => import('@/pages/BrokerTOTP'))
const SamcoAuth = lazy(() => import('@/pages/SamcoAuth'))

// Main pages
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Positions = lazy(() => import('@/india_legacy/pages/Positions'))
const OrderBook = lazy(() => import('@/india_legacy/pages/OrderBook'))
const TradeBook = lazy(() => import('@/india_legacy/pages/TradeBook'))
const Holdings = lazy(() => import('@/pages/Holdings'))
const Token = lazy(() => import('@/india_legacy/pages/Token'))
const Search = lazy(() => import('@/pages/Search'))
const ApiKey = lazy(() => import('@/pages/ApiKey'))
const Profile = lazy(() => import('@/pages/Profile'))
const MasterContract = lazy(() => import('@/pages/MasterContract'))
const ActionCenter = lazy(() => import('@/india_legacy/pages/ActionCenter'))

// Platform pages
const Platforms = lazy(() => import('@/pages/Platforms'))
const TradingView = lazy(() => import('@/india_legacy/pages/TradingView'))
const GoCharting = lazy(() => import('@/india_legacy/pages/GoCharting'))
const PnLTracker = lazy(() => import('@/pages/PnLTracker'))

// Sandbox & Analyzer
const Sandbox = lazy(() => import('@/india_legacy/pages/Sandbox'))
const SandboxPnL = lazy(() => import('@/india_legacy/pages/SandboxPnL'))
const Analyzer = lazy(() => import('@/india_legacy/pages/Analyzer'))
const WebSocketTest = lazy(() => import('@/pages/WebSocketTest'))
const Playground = lazy(() => import('@/pages/Playground'))
const Historify = lazy(() => import('@/india_legacy/pages/Historify'))
const HistorifyCharts = lazy(() => import('@/india_legacy/pages/HistorifyCharts'))

// Tools & Option Chain
const Tools = lazy(() => import('@/india_legacy/pages/Tools'))
const OptionChain = lazy(() => import('@/pages/OptionChain'))
const IVChart = lazy(() => import('@/india_legacy/pages/IVChart'))
const OITracker = lazy(() => import('@/india_legacy/pages/OITracker'))
const MaxPain = lazy(() => import('@/pages/MaxPain'))
const StraddleChart = lazy(() => import('@/india_legacy/pages/StraddleChart'))
const CustomStraddle = lazy(() => import('@/india_legacy/pages/CustomStraddle'))
const VolSurface = lazy(() => import('@/pages/VolSurface'))
const GEXDashboard = lazy(() => import('@/india_legacy/pages/GEXDashboard'))
const IVSmile = lazy(() => import('@/india_legacy/pages/IVSmile'))
const OIProfile = lazy(() => import('@/india_legacy/pages/OIProfile'))
const StrategyBuilder = lazy(() => import('@/india_legacy/pages/StrategyBuilder'))
const StrategyPortfolio = lazy(() => import('@/india_legacy/pages/StrategyPortfolio'))

// Strategy pages
const StrategyIndex = lazy(() => import('@/pages/strategy/StrategyIndex'))
const NewStrategy = lazy(() => import('@/pages/strategy/NewStrategy'))
const ViewStrategy = lazy(() => import('@/pages/strategy/ViewStrategy'))
const ConfigureSymbols = lazy(() => import('@/india_legacy/pages/strategy/ConfigureSymbols'))

// Python Strategy pages
const PythonStrategyIndex = lazy(() => import('@/india_legacy/pages/python-strategy/PythonStrategyIndex'))
const NewPythonStrategy = lazy(() => import('@/india_legacy/pages/python-strategy/NewPythonStrategy'))
const EditPythonStrategy = lazy(() => import('@/india_legacy/pages/python-strategy/EditPythonStrategy'))
const PythonStrategyLogs = lazy(() => import('@/india_legacy/pages/python-strategy/PythonStrategyLogs'))
const SchedulePythonStrategy = lazy(() => import('@/india_legacy/pages/python-strategy/SchedulePythonStrategy'))
const PythonStrategyGuide = lazy(() => import('@/india_legacy/pages/python-strategy/PythonStrategyGuide'))

// Chartink pages
const ChartinkIndex = lazy(() => import('@/india_legacy/pages/chartink/ChartinkIndex'))
const NewChartinkStrategy = lazy(() => import('@/india_legacy/pages/chartink/NewChartinkStrategy'))
const ViewChartinkStrategy = lazy(() => import('@/india_legacy/pages/chartink/ViewChartinkStrategy'))
const ConfigureChartinkSymbols = lazy(() => import('@/india_legacy/pages/chartink/ConfigureChartinkSymbols'))

// Flow pages
const FlowIndex = lazy(() => import('@/pages/flow/FlowIndex'))
const FlowEditor = lazy(() => import('@/pages/flow/FlowEditor'))
const FlowKeyboardShortcuts = lazy(() => import('@/pages/flow/FlowKeyboardShortcuts'))

// Leverage page (crypto brokers only)
const Leverage = lazy(() => import('@/pages/Leverage'))

/** Route guard: only renders children if leverage_config is true, else redirects to dashboard */
function LeverageRoute() {
  const capabilities = useBrokerStore((s) => s.capabilities)
  if (!capabilities?.leverage_config) {
    return <Navigate to="/dashboard" replace />
  }
  return <Leverage />
}

/** Route guard: hide Holdings for crypto brokers (no equity holdings concept) */
function HoldingsRoute() {
  const capabilities = useBrokerStore((s) => s.capabilities)
  if (capabilities?.broker_type === 'crypto') {
    return <Navigate to="/dashboard" replace />
  }
  return <Holdings />
}

// Admin pages
const AdminIndex = lazy(() => import('@/india_legacy/pages/admin/AdminIndex'))
const FreezeQty = lazy(() => import('@/india_legacy/pages/admin/FreezeQty'))
const Holidays = lazy(() => import('@/pages/admin/Holidays'))
const MarketTimings = lazy(() => import('@/india_legacy/pages/admin/MarketTimings'))

// Telegram pages
const TelegramIndex = lazy(() => import('@/pages/telegram/TelegramIndex'))
const TelegramConfig = lazy(() => import('@/india_legacy/pages/telegram/TelegramConfig'))
const TelegramUsers = lazy(() => import('@/pages/telegram/TelegramUsers'))
const TelegramAnalytics = lazy(() => import('@/pages/telegram/TelegramAnalytics'))

// Logs & Monitoring pages
const LogsIndex = lazy(() => import('@/pages/LogsIndex'))
const LiveLogs = lazy(() => import('@/pages/Logs'))
const SecurityDashboard = lazy(() => import('@/pages/monitoring/SecurityDashboard'))
const TrafficDashboard = lazy(() => import('@/pages/monitoring/TrafficDashboard'))
const LatencyDashboard = lazy(() => import('@/pages/monitoring/LatencyDashboard'))
const HealthMonitor = lazy(() => import('@/pages/HealthMonitor'))

function PageTitleUpdater() {
  usePageTitle()
  return null
}

function App() {
  return (
    <Providers>
      <BrowserRouter>
        <PageTitleUpdater />
        <AuthSync>
          <Suspense fallback={<PageLoader />}>
            <Routes>
              {/* Public routes */}
              <Route path="/" element={<Home />} />
              <Route path="/faq" element={<Faq />} />
              <Route path="/setup" element={<Setup />} />
              <Route path="/login" element={<Login />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route path="/download" element={<Download />} />
              <Route path="/error" element={<ServerError />} />
              <Route path="/rate-limited" element={<RateLimited />} />

              {/* Broker auth routes */}
              <Route path="/broker" element={<BrokerSelect />} />
              <Route path="/broker/:broker/totp" element={<BrokerTOTP />} />
              <Route path="/broker/samco/auth" element={<SamcoAuth />} />
              {/* Dynamic broker TOTP routes for all supported brokers */}
              <Route path="/:broker/auth" element={<BrokerTOTP />} />

              {/* Protected routes - requires broker auth */}
              <Route element={<Layout />}>
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/positions" element={<Positions />} />
                <Route path="/orderbook" element={<OrderBook />} />
                <Route path="/tradebook" element={<TradeBook />} />
                <Route path="/holdings" element={<HoldingsRoute />} />
                {/* Search routes - match Flask /search/* routes */}
                <Route path="/search/token" element={<Token />} />
                <Route path="/search" element={<Search />} />
                {/* API Key management */}
                <Route path="/apikey" element={<ApiKey />} />
                {/* Phase 4: Charts & Webhook Configuration */}
                <Route path="/platforms" element={<Platforms />} />
                <Route path="/tradingview" element={<TradingView />} />
                <Route path="/gocharting" element={<GoCharting />} />
                <Route
                  path="/pnl-tracker"
                  element={
                    <IndiaOnly
                      feature="Intraday P&L Tracker"
                      rationale="The intraday P&L tracker pulls realised + unrealised values from the Indian-broker positionbook shape and renders an IST timeline. Equivalent functionality on US brokers comes from Alpaca's account snapshot widgets."
                    >
                      <PnLTracker />
                    </IndiaOnly>
                  }
                />
                {/* Phase 4: Sandbox & Analyzer */}
                <Route path="/sandbox" element={<Sandbox />} />
                <Route path="/sandbox/mypnl" element={<SandboxPnL />} />
                <Route path="/analyzer" element={<Analyzer />} />
                <Route path="/tools" element={<Tools />} />
                <Route
                  path="/optionchain"
                  element={
                    <IndiaOnly
                      feature="Option Chain"
                      rationale="The option-chain reader is keyed on Indian F&O expiry codes (NFO/BFO weekly/monthly series). US single-name and index options use a different chain structure that's not yet wired into this page."
                    >
                      <OptionChain />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/ivchart"
                  element={
                    <IndiaOnly
                      feature="Implied Volatility Chart"
                      rationale="IV charts source from the Indian options chain feed."
                    >
                      <IVChart />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/oitracker"
                  element={
                    <IndiaOnly
                      feature="Open Interest Tracker"
                      rationale="OI streams come from the NSE/BFO derivatives tape, which Indian brokers expose; US options OI plumbing isn't wired yet."
                    >
                      <OITracker />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/maxpain"
                  element={
                    <IndiaOnly
                      feature="Max Pain"
                      rationale="Max-pain calc consumes the Indian options-chain endpoint."
                    >
                      <MaxPain />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/straddle"
                  element={
                    <IndiaOnly
                      feature="Straddle Chart"
                      rationale="The straddle visualizer charts Indian F&O underlyings (NIFTY/BANKNIFTY/etc)."
                    >
                      <StraddleChart />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/straddlepnl"
                  element={
                    <IndiaOnly
                      feature="Custom Straddle"
                      rationale="The custom-straddle builder targets Indian F&O strike/expiry combinations."
                    >
                      <CustomStraddle />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/volsurface"
                  element={
                    <IndiaOnly
                      feature="Volatility Surface"
                      rationale="The vol-surface plot reads from the Indian options chain."
                    >
                      <VolSurface />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/gex"
                  element={
                    <IndiaOnly
                      feature="Gamma Exposure (GEX) Dashboard"
                      rationale="GEX aggregation runs over Indian-broker options-chain rows."
                    >
                      <GEXDashboard />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/ivsmile"
                  element={
                    <IndiaOnly
                      feature="IV Smile"
                      rationale="Plot reads the Indian options-chain feed."
                    >
                      <IVSmile />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/oiprofile"
                  element={
                    <IndiaOnly
                      feature="OI Profile"
                      rationale="OI-by-strike profile reads from the Indian options-chain endpoint."
                    >
                      <OIProfile />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/strategybuilder"
                  element={
                    <IndiaOnly
                      feature="Strategy Builder"
                      rationale="The visual strategy builder composes legs against Indian F&O underlyings + expiries; the calc model assumes NSE/BFO contract specs."
                    >
                      <StrategyBuilder />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/strategybuilder/portfolio"
                  element={
                    <IndiaOnly
                      feature="Strategy Portfolio"
                      rationale="Saved strategies reference Indian F&O instruments."
                    >
                      <StrategyPortfolio />
                    </IndiaOnly>
                  }
                />
                {/* Legacy /tools/strategy paths — redirect to the new route. */}
                <Route
                  path="/tools/strategy"
                  element={<Navigate to="/strategybuilder" replace />}
                />
                <Route
                  path="/tools/strategy/portfolio"
                  element={<Navigate to="/strategybuilder/portfolio" replace />}
                />
                <Route path="/websocket/test" element={<WebSocketTest />} />
                <Route path="/websocket/test/20" element={<WebSocketTest depthLevel={20} />} />
                <Route path="/websocket/test/30" element={<WebSocketTest depthLevel={30} />} />
                <Route path="/websocket/test/50" element={<WebSocketTest depthLevel={50} />} />
                {/* Phase 6: Webhook Strategies */}
                <Route path="/strategy" element={<StrategyIndex />} />
                <Route path="/strategy/new" element={<NewStrategy />} />
                <Route path="/strategy/:strategyId" element={<ViewStrategy />} />
                <Route path="/strategy/:strategyId/configure" element={<ConfigureSymbols />} />
                {/* Phase 6: Python Strategies */}
                <Route path="/python" element={<PythonStrategyIndex />} />
                <Route path="/python/new" element={<NewPythonStrategy />} />
                <Route path="/python/:strategyId/edit" element={<EditPythonStrategy />} />
                <Route path="/python/:strategyId/logs" element={<PythonStrategyLogs />} />
                <Route path="/python/:strategyId/schedule" element={<SchedulePythonStrategy />} />
                <Route path="/python/guide" element={<PythonStrategyGuide />} />
                {/* Phase 6: Chartink Strategies — India-only by definition
                    (Chartink is an Indian-equity scanner). */}
                <Route
                  path="/chartink"
                  element={
                    <IndiaOnly
                      feature="Chartink Strategies"
                      rationale="Chartink is an Indian-equity scanner; the integration consumes its Indian symbol vocabulary directly."
                    >
                      <ChartinkIndex />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/chartink/new"
                  element={
                    <IndiaOnly feature="Chartink Strategies">
                      <NewChartinkStrategy />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/chartink/:strategyId"
                  element={
                    <IndiaOnly feature="Chartink Strategies">
                      <ViewChartinkStrategy />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/chartink/:strategyId/configure"
                  element={
                    <IndiaOnly feature="Chartink Strategies">
                      <ConfigureChartinkSymbols />
                    </IndiaOnly>
                  }
                />
                {/* Flow Editor */}
                <Route path="/flow" element={<FlowIndex />} />
                <Route path="/flow/shortcuts" element={<FlowKeyboardShortcuts />} />
                {/* Leverage Configuration (crypto brokers only) */}
                <Route path="/leverage" element={<LeverageRoute />} />
                {/* Phase 7: Admin */}
                <Route path="/admin" element={<AdminIndex />} />
                <Route path="/admin/freeze" element={<FreezeQty />} />
                <Route path="/admin/holidays" element={<Holidays />} />
                <Route path="/admin/timings" element={<MarketTimings />} />
                {/* Phase 7: Telegram */}
                <Route path="/telegram" element={<TelegramIndex />} />
                <Route path="/telegram/config" element={<TelegramConfig />} />
                <Route path="/telegram/users" element={<TelegramUsers />} />
                <Route path="/telegram/analytics" element={<TelegramAnalytics />} />
                {/* Phase 7: Logs & Monitoring */}
                <Route path="/logs" element={<LogsIndex />} />
                <Route path="/logs/live" element={<LiveLogs />} />
                <Route path="/logs/sandbox" element={<Analyzer />} />
                <Route path="/logs/security" element={<SecurityDashboard />} />
                <Route path="/logs/traffic" element={<TrafficDashboard />} />
                <Route path="/logs/latency" element={<LatencyDashboard />} />
                <Route path="/health" element={<HealthMonitor />} />
                {/* Phase 7: Settings & Action Center */}
                <Route path="/profile" element={<Profile />} />
                <Route path="/master-contract" element={<MasterContract />} />
                <Route path="/action-center" element={<ActionCenter />} />
              </Route>

              {/* Full-width protected routes */}
              <Route element={<FullWidthLayout />}>
                <Route path="/playground" element={<Playground />} />
                <Route
                  path="/historify"
                  element={
                    <IndiaOnly
                      feature="Historify (Historical Data Manager)"
                      rationale="Historify's symbol picker and download scheduler are wired to the Indian-broker `BrokerData` interface (broker.<name>.api.data). For Alpaca + other promoted brokers, historical bars are available via `/api/v2/bars` directly."
                    >
                      <Historify />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/historify/charts"
                  element={
                    <IndiaOnly feature="Historify Charts">
                      <HistorifyCharts />
                    </IndiaOnly>
                  }
                />
                <Route
                  path="/historify/charts/:symbol"
                  element={
                    <IndiaOnly feature="Historify Charts">
                      <HistorifyCharts />
                    </IndiaOnly>
                  }
                />
                {/* Flow Editor (full-width for canvas) */}
                <Route path="/flow/editor/:id" element={<FlowEditor />} />
              </Route>

              {/* 404 Not Found */}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </AuthSync>
      </BrowserRouter>
    </Providers>
  )
}

export default App
