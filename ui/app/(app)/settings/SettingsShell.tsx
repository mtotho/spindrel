import { NavLink, Outlet } from "react-router-dom";
import { User as UserIcon, Hash, Bot, Settings as SettingsIcon } from "lucide-react";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useIsAdmin } from "@/src/hooks/useScope";
import { cn } from "@/src/lib/cn";

interface TabDef {
  to: string;
  label: string;
  icon: React.ComponentType<{ size: number; className?: string }>;
}

const USER_TABS: TabDef[] = [
  { to: "/settings/account", label: "Account", icon: UserIcon },
  { to: "/settings/channels", label: "Channels", icon: Hash },
  { to: "/settings/bots", label: "Bots", icon: Bot },
];

export function SettingsShell() {
  const isAdmin = useIsAdmin();
  const tabs: TabDef[] = [
    ...USER_TABS,
    ...(isAdmin
      ? [{ to: "/settings", label: "System", icon: SettingsIcon }]
      : []),
  ];

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Settings" />
      <div className="px-4 pt-2 flex flex-row gap-1 overflow-x-auto border-b border-surface-border/40">
        {tabs.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/settings"}
            className={({ isActive }) =>
              cn(
                "flex flex-row items-center gap-1.5 px-3 py-2 text-[13px] rounded-t-md transition-colors",
                "hover:bg-surface-overlay/40",
                isActive
                  ? "text-text bg-surface-overlay/60 border-b-2 border-accent -mb-[1px]"
                  : "text-text-muted border-b-2 border-transparent -mb-[1px]",
              )
            }
          >
            <Icon size={14} className="text-text-dim" />
            <span>{label}</span>
          </NavLink>
        ))}
      </div>
      <div className="flex-1 overflow-auto">
        <Outlet />
      </div>
    </div>
  );
}
