/**
 * tasks.md parser — mirrors the Python parser in tools/mission_control.py
 */

import type { KanbanColumn, TaskCard } from "./types";

/** Parse a single card block (text after ### header). */
function parseCard(raw: string): TaskCard {
  const lines = raw.trim().split("\n");
  if (lines.length === 0) return { title: "", meta: {}, description: "" };

  const title = lines[0].trim();
  const meta: Record<string, string> = {};
  const descLines: string[] = [];
  let inDesc = false;

  for (const line of lines.slice(1)) {
    const m = line.match(/^- \*\*(\w+)\*\*:\s*(.*)$/);
    if (m && !inDesc) {
      meta[m[1]] = m[2].trim();
    } else {
      inDesc = true;
      descLines.push(line);
    }
  }

  return { title, meta, description: descLines.join("\n").trim() };
}

/** Serialize a card back to markdown. */
export function serializeCard(card: TaskCard): string {
  const lines = [`### ${card.title}`];
  for (const [key, value] of Object.entries(card.meta)) {
    lines.push(`- **${key}**: ${value}`);
  }
  if (card.description) {
    lines.push("");
    lines.push(card.description);
  }
  return lines.join("\n");
}

/** Parse tasks.md content into columns. */
export function parseTasksMd(content: string): KanbanColumn[] {
  const columns: KanbanColumn[] = [];
  const parts = content.split(/(?:^|\n)## /);

  for (const part of parts.slice(1)) {
    const [firstLine, ...rest] = part.split("\n");
    const colName = firstLine.trim();
    const colBody = rest.join("\n");
    const cards: TaskCard[] = [];
    const cardParts = colBody.split(/\n### /);

    for (const cardRaw of cardParts.slice(1)) {
      const card = parseCard(cardRaw);
      if (card.title) cards.push(card);
    }

    columns.push({ name: colName, cards });
  }

  return columns;
}

/** Generate a short card ID like mc-a1b2c3. */
export function generateCardId(): string {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(3)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `mc-${hex}`;
}

/** Serialize columns back to tasks.md format. */
export function serializeTasksMd(columns: KanbanColumn[]): string {
  const lines = ["# Tasks", ""];

  for (const col of columns) {
    lines.push(`## ${col.name}`);
    lines.push("");
    for (const card of col.cards) {
      lines.push(serializeCard(card));
      lines.push("");
    }
  }

  return lines.join("\n").trimEnd() + "\n";
}
