/**
 * Simple markdown renderer for workspace files.
 * Renders raw markdown with basic formatting — not a full parser,
 * just enough to make workspace files readable.
 */

interface MarkdownViewerProps {
  content: string;
  className?: string;
}

export default function MarkdownViewer({ content, className = "" }: MarkdownViewerProps) {
  const lines = content.split("\n");
  const elements: JSX.Element[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("# ")) {
      elements.push(
        <h1 key={i} className="text-xl font-bold text-content mt-4 mb-2 first:mt-0">
          {line.slice(2)}
        </h1>,
      );
    } else if (line.startsWith("## ")) {
      elements.push(
        <h2 key={i} className="text-lg font-semibold text-content mt-3 mb-1.5">
          {line.slice(3)}
        </h2>,
      );
    } else if (line.startsWith("### ")) {
      elements.push(
        <h3 key={i} className="text-base font-medium text-content mt-2 mb-1">
          {line.slice(4)}
        </h3>,
      );
    } else if (line.startsWith("- ")) {
      elements.push(
        <li key={i} className="text-sm text-content-muted ml-4 list-disc">
          <InlineMarkdown text={line.slice(2)} />
        </li>,
      );
    } else if (line.startsWith("```")) {
      // Code block
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      elements.push(
        <pre
          key={`code-${i}`}
          className="bg-surface-0 rounded-lg p-3 my-2 text-xs text-content-muted overflow-x-auto border border-surface-3"
        >
          {codeLines.join("\n")}
        </pre>,
      );
    } else if (line.trim() === "") {
      elements.push(<div key={i} className="h-2" />);
    } else {
      elements.push(
        <p key={i} className="text-sm text-content-muted leading-relaxed">
          <InlineMarkdown text={line} />
        </p>,
      );
    }
    i++;
  }

  return <div className={`space-y-0.5 ${className}`}>{elements}</div>;
}

/** Render inline markdown (bold, italic, code). */
function InlineMarkdown({ text }: { text: string }) {
  // Replace **bold**, *italic*, `code`
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, idx) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={idx} className="font-semibold text-content">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if (part.startsWith("*") && part.endsWith("*")) {
          return <em key={idx}>{part.slice(1, -1)}</em>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code
              key={idx}
              className="bg-surface-3 px-1.5 py-0.5 rounded text-xs text-accent-hover"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={idx}>{part}</span>;
      })}
    </>
  );
}
