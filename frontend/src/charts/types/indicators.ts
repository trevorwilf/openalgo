// Phase 5 — TS mirror of services/charts/indicator_catalog.py.
// Keep in sync with the Python catalog by hand; the
// `tests/charts/test_indicator_catalog.py` test asserts the keys match.

export type IndicatorParamType = 'int' | 'float' | 'bool' | 'string' | 'select'

export interface IndicatorParam {
  name: string
  type: IndicatorParamType
  default: number | string | boolean
  min_value?: number
  max_value?: number
  step?: number
  options?: readonly string[]
}

export interface IndicatorDef {
  key: string
  label: string
  pane: 'price' | 'oscillator'
  output_keys: readonly string[]
  compute_path: 'talib' | 'pandas_ta' | 'talipp_only'
  params: readonly IndicatorParam[]
}

export const INDICATOR_CATALOG: readonly IndicatorDef[] = [
  {
    key: 'SMA',
    label: 'Simple Moving Average',
    pane: 'price',
    output_keys: ['sma'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 1, max_value: 500, step: 1 }],
  },
  {
    key: 'EMA',
    label: 'Exponential Moving Average',
    pane: 'price',
    output_keys: ['ema'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 1, max_value: 500, step: 1 }],
  },
  {
    key: 'WMA',
    label: 'Weighted Moving Average',
    pane: 'price',
    output_keys: ['wma'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 1, max_value: 500, step: 1 }],
  },
  {
    key: 'VWAP',
    label: 'Volume-Weighted Average Price',
    pane: 'price',
    output_keys: ['vwap'],
    compute_path: 'pandas_ta',
    params: [],
  },
  {
    key: 'RSI',
    label: 'Relative Strength Index',
    pane: 'oscillator',
    output_keys: ['rsi'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 2, max_value: 100, step: 1 }],
  },
  {
    key: 'MACD',
    label: 'MACD',
    pane: 'oscillator',
    output_keys: ['macd', 'signal', 'histogram'],
    compute_path: 'talib',
    params: [
      { name: 'fast_period', type: 'int', default: 12, min_value: 1, max_value: 200, step: 1 },
      { name: 'slow_period', type: 'int', default: 26, min_value: 1, max_value: 400, step: 1 },
      { name: 'signal_period', type: 'int', default: 9, min_value: 1, max_value: 100, step: 1 },
    ],
  },
  {
    key: 'BB',
    label: 'Bollinger Bands',
    pane: 'price',
    output_keys: ['upper', 'middle', 'lower'],
    compute_path: 'talib',
    params: [
      { name: 'period', type: 'int', default: 20, min_value: 2, max_value: 200, step: 1 },
      { name: 'std', type: 'float', default: 2.0, min_value: 0.5, max_value: 5.0, step: 0.5 },
    ],
  },
  {
    key: 'STOCH',
    label: 'Stochastic',
    pane: 'oscillator',
    output_keys: ['k', 'd'],
    compute_path: 'talib',
    params: [
      { name: 'k_period', type: 'int', default: 14, min_value: 1, max_value: 100, step: 1 },
      { name: 'd_period', type: 'int', default: 3, min_value: 1, max_value: 50, step: 1 },
      { name: 'smooth_k', type: 'int', default: 3, min_value: 1, max_value: 50, step: 1 },
    ],
  },
  {
    key: 'ATR',
    label: 'Average True Range',
    pane: 'oscillator',
    output_keys: ['atr'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 1, max_value: 100, step: 1 }],
  },
  {
    key: 'ADX',
    label: 'Average Directional Index',
    pane: 'oscillator',
    output_keys: ['adx', '+di', '-di'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 1, max_value: 100, step: 1 }],
  },
  {
    key: 'OBV',
    label: 'On-Balance Volume',
    pane: 'oscillator',
    output_keys: ['obv'],
    compute_path: 'talib',
    params: [],
  },
  {
    key: 'CCI',
    label: 'Commodity Channel Index',
    pane: 'oscillator',
    output_keys: ['cci'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 20, min_value: 1, max_value: 100, step: 1 }],
  },
  {
    key: 'WILLIAMS_R',
    label: 'Williams %R',
    pane: 'oscillator',
    output_keys: ['willr'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 1, max_value: 100, step: 1 }],
  },
  {
    key: 'ICHIMOKU',
    label: 'Ichimoku Cloud',
    pane: 'price',
    output_keys: ['tenkan', 'kijun', 'senkou_a', 'senkou_b', 'chikou'],
    compute_path: 'pandas_ta',
    params: [
      { name: 'tenkan', type: 'int', default: 9, min_value: 1, max_value: 200, step: 1 },
      { name: 'kijun', type: 'int', default: 26, min_value: 1, max_value: 200, step: 1 },
      { name: 'senkou', type: 'int', default: 52, min_value: 1, max_value: 400, step: 1 },
    ],
  },
  {
    key: 'PSAR',
    label: 'Parabolic SAR',
    pane: 'price',
    output_keys: ['psar'],
    compute_path: 'talib',
    params: [
      {
        name: 'acceleration',
        type: 'float',
        default: 0.02,
        min_value: 0.001,
        max_value: 1.0,
        step: 0.001,
      },
      { name: 'maximum', type: 'float', default: 0.2, min_value: 0.05, max_value: 1.0, step: 0.05 },
    ],
  },
  {
    key: 'DONCHIAN',
    label: 'Donchian Channel',
    pane: 'price',
    output_keys: ['upper', 'middle', 'lower'],
    compute_path: 'pandas_ta',
    params: [{ name: 'period', type: 'int', default: 20, min_value: 1, max_value: 200, step: 1 }],
  },
  {
    key: 'KELTNER',
    label: 'Keltner Channel',
    pane: 'price',
    output_keys: ['upper', 'middle', 'lower'],
    compute_path: 'pandas_ta',
    params: [
      { name: 'period', type: 'int', default: 20, min_value: 1, max_value: 200, step: 1 },
      {
        name: 'multiplier',
        type: 'float',
        default: 2.0,
        min_value: 0.5,
        max_value: 5.0,
        step: 0.5,
      },
    ],
  },
  {
    key: 'MFI',
    label: 'Money Flow Index',
    pane: 'oscillator',
    output_keys: ['mfi'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 14, min_value: 1, max_value: 100, step: 1 }],
  },
  {
    key: 'ROC',
    label: 'Rate of Change',
    pane: 'oscillator',
    output_keys: ['roc'],
    compute_path: 'talib',
    params: [{ name: 'period', type: 'int', default: 10, min_value: 1, max_value: 100, step: 1 }],
  },
  {
    key: 'STOCH_RSI',
    label: 'Stochastic RSI',
    pane: 'oscillator',
    output_keys: ['k', 'd'],
    compute_path: 'talib',
    params: [
      { name: 'rsi_period', type: 'int', default: 14, min_value: 1, max_value: 100, step: 1 },
      { name: 'stoch_period', type: 'int', default: 14, min_value: 1, max_value: 100, step: 1 },
      { name: 'k_period', type: 'int', default: 3, min_value: 1, max_value: 50, step: 1 },
      { name: 'd_period', type: 'int', default: 3, min_value: 1, max_value: 50, step: 1 },
    ],
  },
  {
    key: 'SUPERTREND',
    label: 'SuperTrend',
    pane: 'price',
    output_keys: ['supertrend', 'direction'],
    compute_path: 'pandas_ta',
    params: [
      { name: 'period', type: 'int', default: 7, min_value: 1, max_value: 100, step: 1 },
      {
        name: 'multiplier',
        type: 'float',
        default: 3.0,
        min_value: 0.5,
        max_value: 10.0,
        step: 0.5,
      },
    ],
  },
  {
    key: 'HEIKIN_ASHI',
    label: 'Heikin-Ashi',
    pane: 'price',
    output_keys: ['ha_o', 'ha_h', 'ha_l', 'ha_c'],
    compute_path: 'pandas_ta',
    params: [],
  },
] as const

export const INDICATOR_BY_KEY: Record<string, IndicatorDef> = Object.fromEntries(
  INDICATOR_CATALOG.map((d) => [d.key, d])
)

export function getIndicator(key: string): IndicatorDef | null {
  return INDICATOR_BY_KEY[key.toUpperCase()] ?? null
}
