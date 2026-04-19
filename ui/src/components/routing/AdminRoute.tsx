import { Outlet } from "react-router-dom";
import { useIsAdmin } from "../../hooks/useScope";
import { UnauthorizedCard } from "../shared/UnauthorizedCard";

interface Props {
  children?: React.ReactNode;
}

/**
 * Route guard: renders children (or `<Outlet/>`) only for admin users.
 * Non-admins see the UnauthorizedCard instead. Backend still enforces
 * scope via `require_scopes` — this only hides chrome.
 */
export function AdminRoute({ children }: Props) {
  const isAdmin = useIsAdmin();
  if (!isAdmin) return <UnauthorizedCard />;
  return <>{children ?? <Outlet />}</>;
}
