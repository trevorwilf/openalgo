/**
 * Wrapper that renders India-only features (F&O option chains,
 * Indian-style PnL, NFO straddles, etc.) only when the active broker
 * serves the Indian exchanges. Other regions (US, EU, UK) see a
 * clear empty state explaining why the page is unavailable for
 * their broker — no decorative-but-broken charts that 404 their
 * sub-routes.
 *
 * Architecturally cleaner than hiding routes from the navigation:
 * lets bookmarked / direct-linked URLs survive a broker switch
 * without 404'ing the SPA, and the empty state self-documents the
 * region constraint to operators evaluating which features apply.
 */

import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useBrokerRegion } from '@/hooks/useBrokerRegion'
import { useBrokerStore } from '@/stores/brokerStore'

interface IndiaOnlyFeatureProps {
  /** Friendly name of the feature this page provides. Shown in the
   * unavailable-state heading. */
  featureName: string
  /** One-sentence explanation of why the feature is India-only —
   * usually a reference to Indian-exchange mechanics or the
   * Indian-options ecosystem. */
  rationale?: string
  children: ReactNode
}

export function IndiaOnlyFeature({
  featureName,
  rationale,
  children,
}: IndiaOnlyFeatureProps) {
  const region = useBrokerRegion()
  const capabilities = useBrokerStore((s) => s.capabilities)
  const isLoaded = useBrokerStore((s) => s.isLoaded)
  const isError = useBrokerStore((s) => s.isError)

  // Capabilities still loading — render a transient placeholder
  // instead of guessing.
  if (!isLoaded && !isError) {
    return (
      <div
        className="container mx-auto p-6 text-sm text-muted-foreground"
        data-testid="india-only-feature-loading"
      >
        Loading broker capabilities…
      </div>
    )
  }

  if (region === 'india') {
    return <>{children}</>
  }

  const brokerName = capabilities?.broker_name || capabilities?.broker_code || 'this broker'

  return (
    <div
      className="container mx-auto p-6"
      data-testid="india-only-feature-blocked"
    >
      <Card>
        <CardContent className="p-8 space-y-4">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold">{featureName}</h1>
            <p className="text-sm text-muted-foreground">
              This feature targets Indian exchanges and isn't available for{' '}
              <span className="font-medium text-foreground">{brokerName}</span>
              {region !== 'unknown' && (
                <> ({region.toUpperCase()} region)</>
              )}
              .
            </p>
          </div>

          {rationale && (
            <div className="rounded-md border bg-muted/30 p-3 text-sm">
              {rationale}
            </div>
          )}

          <div className="text-sm text-muted-foreground">
            What you can do instead:
            <ul className="list-disc pl-5 mt-2 space-y-1">
              <li>
                <Link to="/dashboard" className="text-primary hover:underline">
                  Dashboard
                </Link>{' '}
                — account balance and live positions
              </li>
              <li>
                <Link to="/search" className="text-primary hover:underline">
                  Search
                </Link>{' '}
                — find a symbol and place an order via the Trade button
              </li>
              <li>
                <Link to="/orderbook" className="text-primary hover:underline">
                  Order Book
                </Link>{' '}
                — manage existing orders
              </li>
              <li>
                <Link to="/positions" className="text-primary hover:underline">
                  Positions
                </Link>{' '}
                — open positions snapshot
              </li>
            </ul>
          </div>

          <div className="pt-2">
            <Link to="/dashboard">
              <Button variant="outline">Back to Dashboard</Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default IndiaOnlyFeature
