
import { Spinner } from "@/src/components/shared/Spinner";
import { useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useWorkspaces } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";

/**
 * Single workspace mode: redirect to the default workspace's detail page.
 */
export default function WorkspacesScreen() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: workspaces, isLoading } = useWorkspaces();

  useEffect(() => {
    if (!isLoading && workspaces?.[0]) {
      navigate(`/admin/workspaces/${workspaces[0].id}`, { replace: true });
    }
  }, [isLoading, workspaces, navigate]);

  return (
    <div className="flex-1 bg-surface items-center justify-center">
      <Spinner />
    </div>
  );
}
