import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { apiFetch } from "../../../src/api/client";

/** Lands on `/widgets` and redirects to `/widgets/<slug>` where `<slug>` is
 *  the user's most recently viewed dashboard, falling back to `default`. */
export default function WidgetsRedirect() {
  const [slug, setSlug] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch<{ slug: string }>(
          "/api/v1/widgets/dashboards/redirect-target",
        );
        if (!cancelled) setSlug(resp.slug || "default");
      } catch {
        if (!cancelled) setSlug("default");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!slug) return null;
  return <Navigate to={`/widgets/${slug}`} replace />;
}
