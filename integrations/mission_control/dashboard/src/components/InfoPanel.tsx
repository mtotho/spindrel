import { useState, useEffect } from "react";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

interface InfoPanelProps {
  id: string;
  description: string;
  tips?: string[];
  links?: Array<{ label: string; to: string; external?: boolean }>;
}

export default function InfoPanel({ id, description, tips, links }: InfoPanelProps) {
  const storageKey = `mc-info-${id}`;
  const [expanded, setExpanded] = useState(() => {
    const stored = localStorage.getItem(storageKey);
    return stored === null ? true : stored === "1";
  });

  useEffect(() => {
    localStorage.setItem(storageKey, expanded ? "1" : "0");
  }, [expanded, storageKey]);

  const hasTips = tips && tips.length > 0;
  const hasLinks = links && links.length > 0;
  const hasExtra = hasTips || hasLinks;

  return (
    <div className="bg-accent/5 border border-accent/10 rounded-lg px-4 py-2.5 mb-5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-content-muted">{description}</p>
        {hasExtra && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-content-dim hover:text-content-muted transition-colors flex-shrink-0"
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        )}
      </div>
      {expanded && hasExtra && (
        <div className="mt-2 pt-2 border-t border-accent/10">
          {hasTips && (
            <ul className="space-y-1">
              {tips.map((tip, i) => (
                <li key={i} className="text-[11px] text-content-dim flex items-start gap-1.5">
                  <span className="mt-0.5 flex-shrink-0">&#8226;</span>
                  <span>{tip}</span>
                </li>
              ))}
            </ul>
          )}
          {hasLinks && (
            <div className="flex flex-wrap gap-3 mt-2">
              {links.map((link) =>
                link.external ? (
                  <a
                    key={link.to}
                    href={link.to}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover transition-colors"
                  >
                    {link.label} <ExternalLink size={10} />
                  </a>
                ) : (
                  <Link
                    key={link.to}
                    to={link.to}
                    className="text-[11px] text-accent hover:text-accent-hover transition-colors"
                  >
                    {link.label}
                  </Link>
                ),
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
