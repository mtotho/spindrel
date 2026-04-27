import { Link } from "react-router-dom";
import { Pin } from "lucide-react";

import { useSpatialNodes } from "../../../api/hooks/useWorkspaceSpatial";
import { widgetPinHref } from "../../../lib/hubRoutes";
import { contextualNavigationState } from "../../../lib/contextualNavigation";
import { SectionHeading } from "./SectionHeading";

const MAX_PINS = 8;
const HUB_BACK_STATE = contextualNavigationState("/", "Home");

/**
 * Quick-access chips for canvas widget pins. Each pin opens the dedicated
 * full-widget route so mobile users get a focused interaction surface.
 */
export function PinnedWidgetsSection() {
  const { data: nodes } = useSpatialNodes();
  const pins = (nodes ?? []).filter(
    (n) => n.widget_pin_id != null && n.pin != null,
  );
  if (pins.length === 0) return null;

  const visible = pins.slice(0, MAX_PINS);

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading icon={<Pin size={14} />} label="Pinned widgets" count={pins.length} />
      <div className="flex flex-wrap gap-1.5">
        {visible.map((node) => {
          const pin = node.pin!;
          const label = pin.display_label || pin.panel_title || pin.tool_name;
          const href = widgetPinHref(pin.id);
          return (
            <Link
              key={node.id}
              to={href}
              state={HUB_BACK_STATE}
              className="inline-flex max-w-full items-center gap-1.5 rounded-md bg-surface-raised/40 px-3 py-2 text-xs text-text-muted transition-colors hover:bg-surface-overlay/45 hover:text-text"
              title={label}
            >
              <Pin size={11} className="shrink-0 text-text-dim" />
              <span className="truncate">{label}</span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
