/**
 * PlaceOrderEntry — dispatches to the legacy PlaceOrderDialog when
 * the active broker is Indian-legacy, and to PlaceOrderDialogV2 for
 * every other region.
 *
 * The decision is driven by `capabilities.supported_regions`. If
 * "india" is in the list, the broker is on the legacy lane; otherwise
 * the capability-native V2 ticket renders.
 */

import type { BrokerCapabilities } from '@/types/capabilities'
import type { BrokerOrderRule } from '@/types/broker-rules'
import { PlaceOrderDialogV2, type Instrument } from './PlaceOrderDialogV2'

interface PlaceOrderEntryProps {
  apikey: string
  capabilities: BrokerCapabilities | null
  rules: BrokerOrderRule[]
  instrument: Instrument | null
  // Pass-through render hook for the legacy ticket. Kept as a prop so
  // this wrapper does not force import of the legacy component on
  // every bundle (a cycle-avoidance concern in this codebase).
  LegacyDialog?: React.ComponentType<{ apikey: string }>
  onSubmit?: (payload: unknown, response: unknown) => void
  onError?: (error: unknown) => void
}

export function PlaceOrderEntry({
  apikey,
  capabilities,
  rules,
  instrument,
  LegacyDialog,
  onSubmit,
  onError,
}: PlaceOrderEntryProps) {
  if (!capabilities) {
    return (
      <div data-testid="v2-entry-loading">Loading broker capabilities…</div>
    )
  }
  if (!instrument) {
    return <div data-testid="v2-entry-no-instrument">Pick an instrument.</div>
  }

  const isLegacyIndianBroker = capabilities.supported_regions.includes('india')
  if (isLegacyIndianBroker) {
    if (LegacyDialog) {
      return <LegacyDialog apikey={apikey} />
    }
    return (
      <div data-testid="v2-entry-legacy-placeholder">
        legacy ticket required for india
      </div>
    )
  }

  return (
    <PlaceOrderDialogV2
      apikey={apikey}
      capabilities={capabilities}
      rules={rules}
      instrument={instrument}
      onSubmit={onSubmit}
      onError={onError}
    />
  )
}

export default PlaceOrderEntry
