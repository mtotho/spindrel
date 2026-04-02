/**
 * Inline form for creating a new kanban card.
 * Shows at the bottom of a column when the user clicks "+ Add card".
 */

import { useState } from "react";

interface NewCardFormProps {
  columnName: string;
  onSubmit: (data: { title: string; priority: string; description: string }) => void;
  onCancel: () => void;
}

export default function NewCardForm({ columnName, onSubmit, onCancel }: NewCardFormProps) {
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("medium");
  const [description, setDescription] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    onSubmit({ title: title.trim(), priority, description: description.trim() });
    setTitle("");
    setDescription("");
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-surface-2 rounded-lg border border-accent/30 p-3 space-y-2"
    >
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Task title..."
        autoFocus
        className="w-full bg-surface-0 border border-surface-4 rounded px-2.5 py-1.5 text-sm text-content placeholder-gray-600 focus:outline-none focus:border-accent/50"
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)"
        rows={2}
        className="w-full bg-surface-0 border border-surface-4 rounded px-2.5 py-1.5 text-xs text-content-muted placeholder-gray-600 focus:outline-none focus:border-accent/50 resize-none"
      />
      <div className="flex items-center gap-2">
        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          className="bg-surface-0 border border-surface-4 rounded px-2 py-1 text-xs text-content-muted focus:outline-none"
        >
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-content-dim hover:text-content-muted px-2 py-1"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={!title.trim()}
          className="text-xs bg-accent hover:bg-accent-hover disabled:opacity-40 text-white px-3 py-1 rounded transition-colors"
        >
          Add to {columnName}
        </button>
      </div>
    </form>
  );
}
