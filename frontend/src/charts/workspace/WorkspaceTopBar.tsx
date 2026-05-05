// Phase 2 — Workspace Shell
// Tab/layout selector, broker context, paper/live banner, kill switch
// placeholder.
//
// Banner colors per HANDOFF Phase 2 §6: RED for live, BLUE for paper.
// Default is paper / live_mode_enabled=false (D-04). Phase 6 wires the
// per-account toggle + "I understand the risks" gate to the real
// `chart_safety_settings` table; Phase 2 reads default-OFF only.

import { Plus, Power, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useBrokerStore } from '@/stores/brokerStore'
import { makeTab, selectActiveTab, useWorkspaceStore } from '../state/workspaceStore'
import { EngineSelector } from './EngineSelector'

interface WorkspaceTopBarProps {
  /** Test override — when set, the top bar reports this paper/live
   *  state instead of asking the workspace store. Default: paper. */
  liveModeEnabled?: boolean
  /** Test override for kill-switch state. */
  killSwitchOn?: boolean
  /** Test override for the broker label. */
  brokerLabel?: string
}

export function WorkspaceTopBar({
  liveModeEnabled = false,
  killSwitchOn = false,
  brokerLabel,
}: WorkspaceTopBarProps = {}) {
  const tabs = useWorkspaceStore((s) => s.tabs)
  const activeTab = useWorkspaceStore(selectActiveTab)
  const setActiveTab = useWorkspaceStore((s) => s.setActiveTab)
  const addTab = useWorkspaceStore((s) => s.addTab)
  const removeTab = useWorkspaceStore((s) => s.removeTab)

  const capabilities = useBrokerStore((s) => s.capabilities)
  const broker = brokerLabel ?? capabilities?.broker_name ?? capabilities?.broker_code ?? null

  const banner = liveModeEnabled
    ? {
        label: 'LIVE',
        title:
          'LIVE trading: chart-originated orders are real money. Kill-switch active per safety policy.',
        // RED for live (P-10 / D-04).
        className: 'bg-red-600/90 text-red-50 border-red-700 shadow-sm shadow-red-700/40',
      }
    : {
        label: 'PAPER',
        title:
          'PAPER trading: simulated orders only. Toggle live mode in Settings → Risk Controls (Phase 6).',
        // BLUE for paper.
        className: 'bg-blue-600/90 text-blue-50 border-blue-700',
      }

  return (
    <header
      data-testid="workspace-topbar"
      className="flex h-12 w-full items-center gap-3 border-b bg-background/95 px-3"
    >
      <div className="flex items-center gap-1" data-testid="workspace-tabs">
        {tabs.map((t) => (
          <div
            key={t.id}
            className={cn(
              'group flex items-center gap-1 rounded-sm border px-2 py-1 text-xs',
              t.id === activeTab?.id
                ? 'border-primary bg-muted text-foreground'
                : 'border-transparent text-muted-foreground hover:bg-muted/40'
            )}
          >
            <button
              type="button"
              onClick={() => setActiveTab(t.id)}
              className="font-medium"
              data-testid={`tab-${t.id}`}
            >
              {t.name}
            </button>
            <button
              type="button"
              onClick={() => removeTab(t.id)}
              aria-label={`Close tab ${t.name}`}
              className="opacity-0 group-hover:opacity-100"
              data-testid={`tab-close-${t.id}`}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => addTab(makeTab(`Workspace ${tabs.length + 1}`, '1'))}
          aria-label="Add tab"
          data-testid="add-tab"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <EngineSelector className="rounded-sm border bg-background px-2 py-1 text-xs" />
        {broker && (
          <span
            data-testid="broker-label"
            className="rounded-sm border px-2 py-1 text-xs text-muted-foreground"
          >
            {broker}
          </span>
        )}
        <span
          data-testid="paper-live-banner"
          data-mode={liveModeEnabled ? 'live' : 'paper'}
          title={banner.title}
          className={cn(
            'inline-flex items-center rounded-sm border px-2 py-1 text-xs font-semibold tracking-wide',
            banner.className
          )}
        >
          {banner.label}
        </span>
        <Button
          variant={killSwitchOn ? 'destructive' : 'outline'}
          size="sm"
          data-testid="kill-switch"
          data-state={killSwitchOn ? 'on' : 'off'}
          // Phase 6 wires the actual toggle. Phase 2 placeholder is
          // intentionally a no-op so the UI surface exists today.
          onClick={() => undefined}
          aria-label={killSwitchOn ? 'Kill switch ON' : 'Kill switch OFF'}
        >
          <Power className="mr-1 h-3 w-3" />
          {killSwitchOn ? 'KILL' : 'Kill'}
        </Button>
      </div>
    </header>
  )
}
