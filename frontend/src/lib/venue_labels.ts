/**
 * Venue display labels — map ISO 10383 MIC codes to the names a
 * trader actually recognizes. Used by exchange dropdowns and
 * symbol-row renderers so the UI shows "NASDAQ" instead of "XNAS",
 * "NYSE" instead of "XNYS", etc.
 *
 * Indian codes (NSE/BSE/NFO/...) are passthrough — already friendly.
 * Returns the input if no mapping is defined so unknown venues still
 * render something useful.
 */

/** Friendly display names for ISO 10383 Market Identifier Codes. */
const VENUE_LABELS: Record<string, string> = {
  // US equities
  XNAS: 'NASDAQ',
  XNYS: 'NYSE',
  ARCX: 'NYSE Arca',
  BATS: 'Cboe BZX',
  IEXG: 'IEX',
  XCIS: 'NSX',
  XPHL: 'NYSE Philadelphia',
  XBOS: 'NASDAQ BX',
  XCHI: 'NYSE Chicago',
  // EU venues (kept for parity when EU brokers come online)
  XLON: 'LSE',
  XPAR: 'Euronext Paris',
  XAMS: 'Euronext Amsterdam',
  XETR: 'Xetra',
  XFRA: 'Frankfurt',
  XSWX: 'SIX Swiss',
  XMIL: 'Borsa Italiana',
  // Asia
  XTKS: 'Tokyo SE',
  XHKG: 'Hong Kong SE',
  XSHG: 'Shanghai SE',
  XSHE: 'Shenzhen SE',
  XSES: 'Singapore SX',
  // Crypto / synthetic
  ALPACA_CRYPTO: 'Alpaca Crypto',
  CRYPTO: 'Crypto',
}

/**
 * Return the friendly label for ``venueCode``. If the code is unknown
 * the original code is returned so unmapped venues still render.
 */
export function venueLabel(venueCode: string | null | undefined): string {
  if (!venueCode) return ''
  const upper = String(venueCode).trim().toUpperCase()
  return VENUE_LABELS[upper] ?? upper
}

/**
 * Return ``"<friendly> (<code>)"`` when a friendly label exists, else
 * just the code. Useful in dropdowns where the operator may want to
 * confirm the underlying MIC code at a glance.
 */
export function venueLabelWithCode(venueCode: string | null | undefined): string {
  if (!venueCode) return ''
  const upper = String(venueCode).trim().toUpperCase()
  const friendly = VENUE_LABELS[upper]
  if (!friendly || friendly === upper) return upper
  return `${friendly} (${upper})`
}
