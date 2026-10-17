import { ViewTransition } from "react";
import { WrenchIcon } from "lucide-react";

// Transition types set on <Link transitionTypes={[...]}>; CSS lives in globals.css.
export const NAV_FORWARD = ["nav-forward"]; // home → dashboard
export const NAV_BACK = ["nav-back"]; // dashboard → home
export const NAV_SWITCH = ["nav-switch"]; // between dashboard pages

/** Wraps a whole area (home or dashboard) so it slides in/out when moving between them. */
export function AreaTransition({ children }: { children: React.ReactNode }) {
  const map = { "nav-forward": "nav-forward", "nav-back": "nav-back", default: "none" };
  return (
    <ViewTransition enter={map} exit={map} default="none">
      {children}
    </ViewTransition>
  );
}

/** Wraps one dashboard page so switching pages crossfades while the sidebar stays still. */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const map = { "nav-switch": "nav-switch", default: "none" };
  return (
    <ViewTransition enter={map} exit={map} default="none">
      {children}
    </ViewTransition>
  );
}

/**
 * The logo tile. With `morph`, it shares a transition name so it glides between the home nav and the
 * sidebar. Only one mounted logo may carry the name, so the mobile nav renders it with morph={false}.
 */
export function BrandMark({ morph = true }: { morph?: boolean }) {
  const tile = (
    <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-foreground text-background">
      <WrenchIcon className="size-4" />
    </span>
  );
  if (!morph) return tile;
  return (
    <ViewTransition name="brand-mark" share="morph" default="none">
      {tile}
    </ViewTransition>
  );
}
