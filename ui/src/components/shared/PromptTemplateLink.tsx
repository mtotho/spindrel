import { useState, useRef } from "react";
import { Link2, Unlink, FileText, Pencil, FolderOpen } from "lucide-react";
import { usePromptTemplates, useCreatePromptTemplate } from "../../api/hooks/usePromptTemplates";
import type { PromptTemplate } from "../../types/api";
import { WorkspaceFilePicker } from "./WorkspaceFilePicker";

interface Props {
  templateId: string | null | undefined;
  onLink: (id: string) => void;
  onUnlink: () => void;
  workspaceId?: string;
}

export function PromptTemplateLink({ templateId, onLink, onUnlink, workspaceId }: Props) {
  const [open, setOpen] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [browseFile, setBrowseFile] = useState("");
  const [search, setSearch] = useState("");
  const btnRef = useRef<HTMLButtonElement>(null);
  const browseRef = useRef<HTMLButtonElement>(null);
  const { data: templates } = usePromptTemplates(workspaceId);
  const createMut = useCreatePromptTemplate();

  const linked = templates?.find((t) => t.id === templateId);

  const q = search.toLowerCase();
  const filtered = templates
    ? q
      ? templates.filter(
          (t) =>
            t.name.toLowerCase().includes(q) ||
            (t.category || "").toLowerCase().includes(q) ||
            (t.description || "").toLowerCase().includes(q)
        )
      : templates
    : [];

  // Group by source type
  const wsFiles = filtered.filter((t) => t.source_type === "workspace_file");
  const manual = filtered.filter((t) => t.source_type !== "workspace_file");

  const handleBrowseLink = async () => {
    if (!browseFile || !workspaceId) return;
    // Derive a name from the file path
    const fileName = browseFile.split("/").pop() || browseFile;
    const name = fileName.replace(/\.[^.]+$/, "").replace(/[-_]/g, " ");
    const result = await createMut.mutateAsync({
      name,
      source_type: "workspace_file",
      workspace_id: workspaceId,
      source_path: browseFile,
    });
    onLink(result.id);
    setBrowsing(false);
    setBrowseFile("");
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
      {linked ? (
        <>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              padding: "3px 8px",
              fontSize: 11,
              fontWeight: 600,
              borderRadius: 4,
              background: "rgba(59,130,246,0.1)",
              border: "1px solid rgba(59,130,246,0.25)",
              color: "#93c5fd",
            }}
          >
            {linked.source_type === "workspace_file" ? (
              <FileText size={11} />
            ) : (
              <Pencil size={11} />
            )}
            {linked.name}
          </div>
          <button
            onClick={onUnlink}
            title="Unlink template"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              padding: "3px 6px",
              fontSize: 10,
              border: "1px solid #333",
              borderRadius: 4,
              background: "transparent",
              color: "#888",
              cursor: "pointer",
            }}
          >
            <Unlink size={10} />
            Unlink
          </button>
        </>
      ) : (
        <>
          <div style={{ position: "relative", display: "inline-block" }}>
            <button
              ref={btnRef}
              onClick={() => { setOpen(!open); setBrowsing(false); }}
              title="Link a prompt template"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "3px 8px",
                fontSize: 11,
                fontWeight: 600,
                border: "1px solid #333",
                borderRadius: 4,
                background: open ? "#1a1a1a" : "transparent",
                color: "#888",
                cursor: "pointer",
              }}
            >
              <Link2 size={11} />
              Link Template
            </button>

            {open &&
              typeof document !== "undefined" &&
              (() => {
                const ReactDOM = require("react-dom");
                return ReactDOM.createPortal(
                  <>
                    <div
                      onClick={() => {
                        setOpen(false);
                        setSearch("");
                      }}
                      style={{ position: "fixed", inset: 0, zIndex: 10010 }}
                    />
                    <div
                      style={{
                        position: "fixed",
                        top: (btnRef.current?.getBoundingClientRect().bottom ?? 0) + 4,
                        left: btnRef.current?.getBoundingClientRect().left ?? 0,
                        width: 340,
                        maxHeight: 380,
                        zIndex: 10011,
                        background: "#1a1a1a",
                        border: "1px solid #333",
                        borderRadius: 8,
                        boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                        display: "flex",
                        flexDirection: "column",
                      }}
                    >
                      <div style={{ padding: "8px 10px", borderBottom: "1px solid #2a2a2a" }}>
                        <input
                          type="text"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                          placeholder="Search templates..."
                          autoFocus
                          style={{
                            width: "100%",
                            background: "#111",
                            border: "1px solid #333",
                            borderRadius: 4,
                            padding: "5px 8px",
                            fontSize: 12,
                            color: "#e5e5e5",
                            outline: "none",
                          }}
                        />
                      </div>
                      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
                        {filtered.length === 0 && (
                          <div
                            style={{
                              padding: "16px 12px",
                              textAlign: "center",
                              color: "#555",
                              fontSize: 12,
                            }}
                          >
                            No templates found
                          </div>
                        )}
                        {wsFiles.length > 0 && (
                          <TemplateGroup
                            label="Workspace Files"
                            items={wsFiles}
                            onSelect={(t) => {
                              onLink(t.id);
                              setOpen(false);
                              setSearch("");
                            }}
                          />
                        )}
                        {manual.length > 0 && (
                          <TemplateGroup
                            label="Manual"
                            items={manual}
                            onSelect={(t) => {
                              onLink(t.id);
                              setOpen(false);
                              setSearch("");
                            }}
                          />
                        )}
                      </div>
                    </div>
                  </>,
                  document.body
                );
              })()}
          </div>

          {workspaceId && (
            <div style={{ position: "relative", display: "inline-block" }}>
              <button
                ref={browseRef}
                onClick={() => { setBrowsing(!browsing); setOpen(false); setBrowseFile(""); }}
                title="Browse workspace files"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "3px 8px",
                  fontSize: 11,
                  fontWeight: 600,
                  border: "1px solid #333",
                  borderRadius: 4,
                  background: browsing ? "#1a1a1a" : "transparent",
                  color: "#888",
                  cursor: "pointer",
                }}
              >
                <FolderOpen size={11} />
                Browse Workspace
              </button>

              {browsing &&
                typeof document !== "undefined" &&
                (() => {
                  const ReactDOM = require("react-dom");
                  return ReactDOM.createPortal(
                    <>
                      <div
                        onClick={() => { setBrowsing(false); setBrowseFile(""); }}
                        style={{ position: "fixed", inset: 0, zIndex: 10010 }}
                      />
                      <div
                        style={{
                          position: "fixed",
                          top: (browseRef.current?.getBoundingClientRect().bottom ?? 0) + 4,
                          left: browseRef.current?.getBoundingClientRect().left ?? 0,
                          width: 380,
                          zIndex: 10011,
                          background: "#1a1a1a",
                          border: "1px solid #333",
                          borderRadius: 8,
                          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                          display: "flex",
                          flexDirection: "column",
                          padding: 12,
                          gap: 10,
                        }}
                      >
                        <div style={{ fontSize: 11, fontWeight: 600, color: "#999", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                          Select workspace file
                        </div>
                        <WorkspaceFilePicker
                          workspaceId={workspaceId}
                          value={browseFile}
                          onChange={setBrowseFile}
                          fileFilter=".md"
                        />
                        <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                          <button
                            onClick={() => { setBrowsing(false); setBrowseFile(""); }}
                            style={{
                              padding: "4px 12px", fontSize: 11,
                              background: "transparent", border: "1px solid #333",
                              borderRadius: 4, color: "#888", cursor: "pointer",
                            }}
                          >
                            Cancel
                          </button>
                          <button
                            onClick={handleBrowseLink}
                            disabled={!browseFile || createMut.isPending}
                            style={{
                              padding: "4px 12px", fontSize: 11, fontWeight: 600,
                              background: browseFile ? "#3b82f6" : "#333",
                              color: browseFile ? "#fff" : "#666",
                              border: "none", borderRadius: 4,
                              cursor: browseFile ? "pointer" : "not-allowed",
                            }}
                          >
                            {createMut.isPending ? "Creating..." : "Link"}
                          </button>
                        </div>
                      </div>
                    </>,
                    document.body
                  );
                })()}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TemplateGroup({
  label,
  items,
  onSelect,
}: {
  label: string;
  items: PromptTemplate[];
  onSelect: (t: PromptTemplate) => void;
}) {
  return (
    <div>
      <div
        style={{
          padding: "6px 12px 2px",
          fontSize: 9,
          fontWeight: 700,
          color: "#555",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </div>
      {items.map((t) => (
        <button
          key={t.id}
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(t);
          }}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
            width: "100%",
            padding: "6px 12px",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            textAlign: "left",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "#2a2a2a")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {t.source_type === "workspace_file" ? (
              <FileText size={11} color="#86efac" />
            ) : (
              <Pencil size={11} color="#93c5fd" />
            )}
            <span style={{ fontSize: 12, fontWeight: 600, color: "#e5e5e5" }}>
              {t.name}
            </span>
          </div>
          {t.description && (
            <span
              style={{
                fontSize: 11,
                color: "#666",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                paddingLeft: 17,
              }}
            >
              {t.description}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
