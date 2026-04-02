/**
 * First-time setup guide shown when the dashboard has no data.
 * Walks users through connecting to the agent server and
 * setting up their first Mission Control channel.
 */

import { useState } from "react";

interface SetupGuideProps {
  hasServer: boolean;   // Agent server is reachable
  hasChannels: boolean; // At least one workspace-enabled channel exists
  hasBots: boolean;     // At least one bot exists
}

interface Step {
  number: number;
  title: string;
  description: string;
  detail: string;
  done: boolean;
}

export default function SetupGuide({ hasServer, hasChannels, hasBots }: SetupGuideProps) {
  const [expanded, setExpanded] = useState<number | null>(
    !hasServer ? 1 : !hasBots ? 2 : !hasChannels ? 3 : null,
  );

  const steps: Step[] = [
    {
      number: 1,
      title: "Connect to Agent Server",
      description: "The dashboard needs a running agent server to pull data from.",
      detail:
        "Set the AGENT_SERVER_URL environment variable to your agent server address " +
        "(default: http://host.docker.internal:8000). If authentication is enabled, " +
        "also set AGENT_SERVER_API_KEY — use the 'Mission Control Dashboard' preset " +
        "when creating an API key in the admin UI.",
      done: hasServer,
    },
    {
      number: 2,
      title: "Create a Bot",
      description: "You need at least one bot configured in the agent server.",
      detail:
        "Create a bot YAML file in bots/ or use the admin UI. To enable Mission Control " +
        "features, add the skill and tools to your bot config:\n\n" +
        "  skills: [mission_control]\n" +
        "  local_tools: [create_task_card, move_task_card]\n\n" +
        "The skill teaches the bot the structured file formats. The tools let it " +
        "programmatically manage kanban boards.",
      done: hasBots,
    },
    {
      number: 3,
      title: "Set Up a Channel",
      description: "Create a channel with workspace enabled and the Mission Control schema.",
      detail:
        "In the admin UI, create a new channel and:\n\n" +
        "1. Enable 'Channel Workspace'\n" +
        "2. Select the 'Mission Control' workspace schema\n" +
        "3. Assign your bot\n\n" +
        "The schema tells the bot to organize files as tasks.md (kanban board), " +
        "status.md (project health), decisions.md, notes.md, and references.md. " +
        "Send a message to the channel to get started — the bot will create the workspace files.",
      done: hasChannels,
    },
    {
      number: 4,
      title: "Start Working",
      description: "Your channels will appear here with kanban boards, file viewers, and activity logs.",
      detail:
        "Once a channel has workspace files, you'll see them in the dashboard. " +
        "The kanban board reads tasks.md — drag cards between columns to update status. " +
        "Changes write back to the workspace file so your bot sees them too.\n\n" +
        "You can create task cards directly from the kanban view, or let your bot " +
        "create them using the create_task_card tool.",
      done: hasChannels,
    },
  ];

  const allDone = steps.every((s) => s.done);
  if (allDone) return null;

  return (
    <div className="bg-surface-1 rounded-xl border border-surface-3 overflow-hidden">
      <div className="p-4 border-b border-surface-3">
        <h2 className="text-base font-semibold text-content">Getting Started</h2>
        <p className="text-xs text-content-dim mt-0.5">
          {steps.filter((s) => s.done).length} of {steps.length} steps complete
        </p>
      </div>
      <div className="divide-y divide-surface-3">
        {steps.map((step) => (
          <div key={step.number}>
            <button
              onClick={() => setExpanded(expanded === step.number ? null : step.number)}
              className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-surface-2 transition-colors"
            >
              <span
                className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                  step.done
                    ? "bg-status-green/20 text-status-green"
                    : "bg-surface-3 text-content-muted"
                }`}
              >
                {step.done ? "✓" : step.number}
              </span>
              <div className="min-w-0">
                <p className={`text-sm font-medium ${step.done ? "text-content-dim" : "text-content"}`}>
                  {step.title}
                </p>
                <p className="text-xs text-content-dim truncate">{step.description}</p>
              </div>
              <span className="flex-shrink-0 text-content-dim text-xs ml-auto">
                {expanded === step.number ? "▾" : "▸"}
              </span>
            </button>
            {expanded === step.number && (
              <div className="px-4 pb-3 ml-9">
                <pre className="text-xs text-content-muted whitespace-pre-wrap font-sans leading-relaxed">
                  {step.detail}
                </pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
