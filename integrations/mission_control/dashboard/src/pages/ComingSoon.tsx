import { useLocation } from "react-router-dom";
import EmptyState from "../components/EmptyState";

export default function ComingSoon() {
  const location = useLocation();
  const pageName = location.pathname
    .split("/")
    .filter(Boolean)
    .pop()
    ?.replace(/-/g, " ")
    ?.replace(/\b\w/g, (c) => c.toUpperCase()) || "Page";

  return (
    <div className="flex items-center justify-center h-full p-8">
      <EmptyState
        icon="◇"
        title={`${pageName}`}
        description="This page is coming soon. Check back after the next update."
      />
    </div>
  );
}
