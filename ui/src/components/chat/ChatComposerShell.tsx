import type { ReactNode } from "react";

export function ChatComposerShell({
  children,
  chatMode = "default",
}: {
  children: ReactNode;
  chatMode?: "default" | "terminal";
}) {
  if (chatMode === "terminal") {
    return <>{children}</>;
  }

  return <div className="w-full mx-auto max-w-[820px] px-4">{children}</div>;
}
