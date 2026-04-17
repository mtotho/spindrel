import { useNavigate } from "react-router-dom";
import { ArrowLeft, Menu, ChevronRight } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { cn } from "../../lib/cn";

export interface PageHeaderProps {
  variant: "list" | "detail";
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  parentLabel?: string;
  backTo?: string;
  onBack?: () => void;
  hideNav?: boolean;
  hideTitle?: boolean;
  inline?: boolean;
}

export function PageHeader({
  variant,
  title,
  subtitle,
  right,
  parentLabel,
  backTo,
  onBack,
  hideNav,
  hideTitle,
  inline,
}: PageHeaderProps) {
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const openPalette = useUIStore((s) => s.openPalette);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const navigate = useNavigate();

  const sidebarHidden = isMobile || sidebarCollapsed;

  const handleBack = backTo ? () => navigate(backTo) : onBack;

  // Detail pages with a back target show back arrow everywhere (mobile + desktop).
  // List pages show hamburger on mobile or when sidebar is collapsed on desktop.
  const useBackArrow = variant === "detail" && !!handleBack;
  const useHamburger = !useBackArrow && (isMobile || (variant === "list" && sidebarHidden));

  const showNav = !hideNav && (useHamburger || useBackArrow);

  const navButton = showNav && (
    <button
      onClick={useHamburger
        ? (isMobile ? openPalette : toggleSidebar)
        : handleBack}
      aria-label={useHamburger ? "Open menu" : "Go back"}
      className="w-10 h-10 rounded-md flex flex-row items-center justify-center hover:bg-surface-overlay/60 transition-colors cursor-pointer bg-transparent border-none p-0"
    >
      {useHamburger
        ? <Menu size={20} className="text-text-muted" />
        : <ArrowLeft size={20} className="text-text-muted" />}
    </button>
  );

  return (
    <div className={cn(
      "flex flex-row items-center shrink-0",
      !inline && "min-h-[52px] bg-surface border-b border-surface-border",
      isMobile ? "px-3 gap-2" : "px-4 gap-3",
    )}>
      {navButton}

      {variant === "detail" && !isMobile && parentLabel && (
        <>
          <span className="text-[13px] text-text-muted font-medium whitespace-nowrap">
            {parentLabel}
          </span>
          <ChevronRight size={14} className="text-text-dim shrink-0" />
        </>
      )}

      {!hideTitle && (
        <div className="flex-1 min-w-0 py-2">
          <span className="text-base font-bold text-text truncate block">{title}</span>
          {subtitle && (
            <span className="text-xs text-text-muted truncate mt-0.5 block">{subtitle}</span>
          )}
        </div>
      )}

      {right && (
        <div className={cn("flex flex-row items-center gap-2", hideTitle ? "flex-1" : "shrink-0")}>
          {right}
        </div>
      )}
    </div>
  );
}
