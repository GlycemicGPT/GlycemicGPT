/**
 * Custom Hooks
 *
 * Barrel export for custom React hooks.
 */

export {
  useGlucoseStream,
  mapBackendTrendToFrontend,
  type GlucoseData,
  type GlucoseStreamState,
  type ConnectionState,
  type BackendTrendDirection,
  type FrontendTrendDirection,
} from "./use-glucose-stream";

export { useCurrentUser } from "./use-current-user";

export {
  useGlucoseRange,
  type GlucoseThresholds,
} from "./use-glucose-range";

export { useReducedMotion } from "./use-reduced-motion";
