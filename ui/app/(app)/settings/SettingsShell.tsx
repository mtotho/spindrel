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
      ? [{ to: "/settings/system", label: "System", icon: SettingsIcon }]
      : []),
  ];

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader
        variant="list"
        title="Settings"
        subtitle="Account preferences, personal catalogs, and admin system controls."
      />
      <div className="px-4 pt-2 flex flex-row gap-1 overflow-x-auto">
        {tabs.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end
            className={({ isActive }) =>
              cn(
                "flex min-h-[36px] shrink-0 flex-row items-center gap-1.5 rounded-md px-3 py-2 text-[13px] font-semibold transition-colors",
                "hover:bg-surface-overlay/40",
                isActive
                  ? "text-accent bg-accent/[0.08]"
                  : "text-text-muted",
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
