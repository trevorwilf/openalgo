// v6 Phase 1 — venue/region timezone hook (capability-driven).
//
// The v6 prompt asks for `useVenueTimezone` at this exact path. The
// underlying logic already lives in `@/lib/format/timezone.ts` as
// `useActiveTimezone` and `useActiveTimezoneLabel`; this module
// re-exports them under the v6-named identifier so component code can
// import a stable name from a hooks-folder home.
//
// Behavior is unchanged from v5 Phase 2 (capability-driven; null when
// the active broker has no resolved timezone — caller renders an
// explicit unknown state).

export {
  useActiveTimezone as useVenueTimezone,
  useActiveTimezoneLabel as useVenueTimezoneLabel,
  timezoneShortLabel as venueTimezoneShortLabel,
} from '@/lib/format/timezone'
