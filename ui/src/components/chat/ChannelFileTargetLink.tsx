import type { CSSProperties, MouseEvent, ReactNode } from "react";
import {
  buildChannelFileHref,
  CHANNEL_FILE_LINK_OPEN_EVENT,
  directoryForWorkspaceFile,
  resolveToolTargetFilePath,
  type ChannelFileLinkOpenDetail,
} from "../../lib/channelFileNavigation";

function shouldLetBrowserOpen(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey;
}

export function resolveToolTargetHref({
  channelId,
  sessionId,
  target,
}: {
  channelId?: string | null;
  sessionId?: string | null;
  target?: string | null;
}): { filePath: string; href: string } | null {
  if (!channelId) return null;
  const filePath = resolveToolTargetFilePath(target);
  if (!filePath) return null;
  return {
    filePath,
    href: buildChannelFileHref({
      channelId,
      sessionId,
      directoryPath: directoryForWorkspaceFile(filePath),
      openFile: filePath,
    }),
  };
}

export function ChannelFileTargetLink({
  channelId,
  sessionId,
  target,
  children,
  className,
  style,
  testId,
}: {
  channelId?: string | null;
  sessionId?: string | null;
  target: string;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  testId?: string;
}) {
  const link = resolveToolTargetHref({ channelId, sessionId, target });
  if (!link) {
    return (
      <span data-testid={testId} className={className} style={style}>
        {children}
      </span>
    );
  }

  return (
    <a
      data-testid={testId}
      href={link.href}
      className={className}
      style={style}
      title="Open file. Alt-click to open split. Ctrl/Cmd-click to open in a new tab."
      onClick={(event) => {
        event.stopPropagation();
        if (shouldLetBrowserOpen(event)) return;
        const openEvent = new CustomEvent<ChannelFileLinkOpenDetail>(
          CHANNEL_FILE_LINK_OPEN_EVENT,
          {
            cancelable: true,
            detail: { channelId: channelId!, path: link.filePath, split: event.altKey },
          },
        );
        if (!window.dispatchEvent(openEvent)) {
          event.preventDefault();
        }
      }}
    >
      {children}
    </a>
  );
}
