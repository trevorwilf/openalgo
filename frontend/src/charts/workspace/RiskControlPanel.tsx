// Phase 6 — Risk Controls panel.
//
// Surfaces:
//   * Kill switch toggle (ON/OFF). When ON, the HUD blocks intent
//     submission client-side; the backend pre-trade validator denies
//     server-side (defense in depth).
//   * Live-mode toggle behind a 3-step "I understand the risks" gate.
//     Per HANDOFF Phase 6 §13: 3 distinct checkboxes —
//       "I understand orders are real money"
//       "I understand the kill-switch protection"
//       "I understand audit logs are permanent"
//     Toggling kill-switch ON resets `live_mode_enabled` to false.
//   * Drag-to-modify confirmation toggle (default OFF per P-10).

import { useCallback, useState } from 'react'
import { Button } from '@/components/ui/button'

export interface RiskControlState {
  killSwitch: boolean
  liveModeEnabled: boolean
  modifyConfirmEnabled: boolean
  maxOrderSize: number
  maxNotional: string | null
  currency: string
}

export interface RiskControlPanelProps {
  state: RiskControlState
  onChange(next: RiskControlState): void
}

export function RiskControlPanel({ state, onChange }: RiskControlPanelProps) {
  const [showLiveGate, setShowLiveGate] = useState(false)
  const [ack1, setAck1] = useState(false)
  const [ack2, setAck2] = useState(false)
  const [ack3, setAck3] = useState(false)

  const toggleKill = useCallback(() => {
    const next: RiskControlState = {
      ...state,
      killSwitch: !state.killSwitch,
      // Killing kill-switch ON resets live-mode (HANDOFF Phase 6 §13).
      liveModeEnabled: !state.killSwitch ? false : state.liveModeEnabled,
    }
    onChange(next)
  }, [state, onChange])

  const enableLive = useCallback(() => {
    if (!ack1 || !ack2 || !ack3) return
    onChange({ ...state, liveModeEnabled: true })
    setShowLiveGate(false)
    setAck1(false)
    setAck2(false)
    setAck3(false)
  }, [ack1, ack2, ack3, state, onChange])

  const disableLive = useCallback(() => {
    onChange({ ...state, liveModeEnabled: false })
  }, [state, onChange])

  const toggleModifyConfirm = useCallback(() => {
    onChange({ ...state, modifyConfirmEnabled: !state.modifyConfirmEnabled })
  }, [state, onChange])

  return (
    <section data-testid="risk-control-panel" className="rounded-md border bg-card p-3 text-xs">
      <h3 className="mb-2 text-sm font-medium">Risk Controls</h3>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span>Kill switch</span>
          <Button
            type="button"
            variant={state.killSwitch ? 'destructive' : 'outline'}
            size="sm"
            onClick={toggleKill}
            data-testid="risk-kill-toggle"
            data-state={state.killSwitch ? 'on' : 'off'}
          >
            {state.killSwitch ? 'ON' : 'OFF'}
          </Button>
        </div>
        <div className="flex items-center justify-between">
          <span>Live trading</span>
          {state.liveModeEnabled ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={disableLive}
              data-testid="risk-live-disable"
            >
              Disable
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShowLiveGate(true)}
              data-testid="risk-live-open-gate"
            >
              Enable…
            </Button>
          )}
        </div>
        <div className="flex items-center justify-between">
          <span>Drag-to-modify confirmation</span>
          <Button
            type="button"
            variant={state.modifyConfirmEnabled ? 'default' : 'outline'}
            size="sm"
            onClick={toggleModifyConfirm}
            data-testid="risk-modify-confirm-toggle"
            data-state={state.modifyConfirmEnabled ? 'on' : 'off'}
          >
            {state.modifyConfirmEnabled ? 'ON' : 'OFF (default)'}
          </Button>
        </div>
        <hr className="my-2 border-muted" />
        <ul className="space-y-1 text-[10px] text-muted-foreground">
          <li>
            Max order size: <strong>{state.maxOrderSize}</strong>
          </li>
          <li>
            Max notional:{' '}
            <strong>
              {state.maxNotional ?? '—'} {state.currency}
            </strong>
          </li>
        </ul>
      </div>

      {showLiveGate && (
        <div
          data-testid="live-mode-gate"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-sm rounded-md border border-red-500/60 bg-background p-4 shadow-lg">
            <h2 className="mb-2 text-base font-medium text-red-200">Enable LIVE trading</h2>
            <p className="mb-3 text-xs text-muted-foreground">
              Live mode means chart-originated orders are real money. Confirm by ticking ALL three
              boxes.
            </p>
            <label className="mb-1 flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={ack1}
                onChange={(e) => setAck1(e.target.checked)}
                data-testid="live-ack-1"
              />
              <span>I understand orders are real money.</span>
            </label>
            <label className="mb-1 flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={ack2}
                onChange={(e) => setAck2(e.target.checked)}
                data-testid="live-ack-2"
              />
              <span>I understand the kill-switch protection.</span>
            </label>
            <label className="mb-3 flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={ack3}
                onChange={(e) => setAck3(e.target.checked)}
                data-testid="live-ack-3"
              />
              <span>I understand audit logs are permanent.</span>
            </label>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setShowLiveGate(false)}
                data-testid="live-gate-cancel"
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={enableLive}
                disabled={!ack1 || !ack2 || !ack3}
                data-testid="live-gate-confirm"
              >
                Enable LIVE
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
