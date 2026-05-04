import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, RefreshCw, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/src/api/client";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { SourceTextEditor } from "@/src/components/shared/SourceTextEditor";
import { Spinner } from "@/src/components/shared/Spinner";

interface KnowledgeDocumentSummary {
  slug: string;
  entry_id?: string | null;
  type: string;
  status: string;
  path: string;
  title: string;
  summary: string;
  excerpt: string;
  tags: string[];
  modified_at: string;
  frontmatter?: Record<string, unknown>;
}

interface KnowledgeDocumentDetail extends KnowledgeDocumentSummary {
  content: string;
  content_hash: string;
  workspace_path?: string;
  tool_path?: string;
  word_count?: number;
}

interface ReviewGroup {
  user_id: string;
  documents: KnowledgeDocumentSummary[];
}

interface ReviewResponse {
  workspace_id: string;
  groups: ReviewGroup[];
}

function useKnowledgeReview() {
  return useQuery({
    queryKey: ["admin-knowledge-review"],
    queryFn: () => apiFetch<ReviewResponse>("/api/v1/admin/knowledge/review"),
  });
}

function useReviewAction(action: "accept" | "reject") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, slug }: { userId: string; slug: string }) =>
      apiFetch(`/api/v1/admin/knowledge/review/${encodeURIComponent(userId)}/${encodeURIComponent(slug)}/${action}`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-knowledge-review"] });
    },
  });
}

function useReviewDocument(userId?: string, slug?: string) {
  return useQuery({
    queryKey: ["admin-knowledge-review-document", userId, slug],
    queryFn: () => apiFetch<KnowledgeDocumentDetail>(`/api/v1/admin/knowledge/review/${encodeURIComponent(userId!)}/${encodeURIComponent(slug!)}`),
    enabled: Boolean(userId && slug),
  });
}

function useWriteReviewDocument(userId?: string, slug?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ content, baseHash }: { content: string; baseHash?: string }) =>
      apiFetch<KnowledgeDocumentDetail>(`/api/v1/admin/knowledge/review/${encodeURIComponent(userId!)}/${encodeURIComponent(slug!)}`, {
        method: "PUT",
        body: JSON.stringify({ content, base_hash: baseHash }),
      }),
    onSuccess: (doc) => {
      queryClient.setQueryData(["admin-knowledge-review-document", userId, slug], doc);
      queryClient.invalidateQueries({ queryKey: ["admin-knowledge-review"] });
    },
  });
}

export default function AdminKnowledgeReviewPage() {
  const { data, isLoading, refetch, isFetching } = useKnowledgeReview();
  const accept = useReviewAction("accept");
  const reject = useReviewAction("reject");
  const groups = data?.groups ?? [];
  const total = groups.reduce((sum, group) => sum + group.documents.length, 0);
  const [selected, setSelected] = useState<{ userId: string; slug: string } | null>(null);
  const selectedDocQuery = useReviewDocument(selected?.userId, selected?.slug);
  const writeDoc = useWriteReviewDocument(selected?.userId, selected?.slug);
  const [draftContent, setDraftContent] = useState("");
  const selectedDoc = selectedDocQuery.data;

  useEffect(() => {
    setDraftContent(selectedDoc?.content ?? "");
  }, [selectedDoc?.content, selectedDoc?.content_hash]);

  const selectedBusy = accept.isPending || reject.isPending || writeDoc.isPending;
  const draftDirty = useMemo(() => Boolean(selectedDoc && draftContent !== selectedDoc.content), [draftContent, selectedDoc]);

  return (
    <div className="flex min-h-full flex-col bg-app text-text">
      <PageHeader
        variant="list"
        title="Knowledge Review"
        subtitle={total ? `${total} pending entr${total === 1 ? "y" : "ies"}` : "No pending entries"}
        right={
          <button
            type="button"
            onClick={() => refetch()}
            className="inline-flex items-center gap-2 rounded border border-surface-border bg-surface px-3 py-2 text-sm text-text hover:bg-surface-hover"
          >
            <RefreshCw size={15} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />

      <main className="grid min-h-0 flex-1 gap-5 overflow-auto px-6 py-5 xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.8fr)]">
        {isLoading ? (
          <div className="flex h-48 items-center justify-center xl:col-span-2">
            <Spinner />
          </div>
        ) : groups.length === 0 ? (
          <div className="rounded border border-surface-border bg-surface p-6 text-sm text-text-dim xl:col-span-2">
            No pending knowledge entries.
          </div>
        ) : (
          <div className="flex min-w-0 flex-col gap-5">
            {groups.map((group) => (
              <section key={group.user_id} className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-text">User {group.user_id}</h2>
                  <span className="text-xs text-text-dim">{group.documents.length} pending</span>
                </div>
                <div className="grid gap-3">
                  {group.documents.map((doc) => {
                    const sourceMessageId = String(doc.frontmatter?.source_message_id ?? "");
                    const busy = accept.isPending || reject.isPending;
                    return (
                      <article key={`${group.user_id}:${doc.slug}`} className={`rounded border bg-surface p-4 ${selected?.userId === group.user_id && selected?.slug === doc.slug ? "border-accent" : "border-surface-border"}`}>
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="truncate text-base font-semibold text-text">{doc.title}</h3>
                              <span className="rounded bg-surface-hover px-2 py-1 text-xs text-text-dim">{doc.type || "note"}</span>
                              <span className="rounded bg-warning/10 px-2 py-1 text-xs font-medium text-warning">{doc.status}</span>
                            </div>
                            {doc.excerpt ? <p className="mt-2 text-sm text-text-muted">{doc.excerpt}</p> : null}
                            <div className="mt-3 flex flex-wrap gap-3 text-xs text-text-dim">
                              <span>{doc.path}</span>
                              {sourceMessageId ? <span>Source {sourceMessageId}</span> : null}
                            </div>
                          </div>
                          <div className="flex shrink-0 gap-2">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => accept.mutate({ userId: group.user_id, slug: doc.slug })}
                              className="inline-flex items-center gap-2 rounded bg-success px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                            >
                              <Check size={15} />
                              Accept
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => reject.mutate({ userId: group.user_id, slug: doc.slug })}
                              className="inline-flex items-center gap-2 rounded border border-danger/40 px-3 py-2 text-sm font-medium text-danger disabled:opacity-50"
                            >
                              <X size={15} />
                              Reject
                            </button>
                            <button
                              type="button"
                              onClick={() => setSelected({ userId: group.user_id, slug: doc.slug })}
                              className="inline-flex items-center gap-2 rounded border border-surface-border px-3 py-2 text-sm text-text-muted hover:bg-surface-hover"
                              title="Open review editor"
                            >
                              <ExternalLink size={15} />
                            </button>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        )}
        {groups.length > 0 && (
          <aside className="min-w-0 rounded border border-surface-border bg-surface">
            {!selected ? (
              <div className="p-5 text-sm text-text-dim">Select an entry to review its full markdown before accepting or rejecting it.</div>
            ) : selectedDocQuery.isLoading ? (
              <div className="flex h-48 items-center justify-center"><Spinner /></div>
            ) : selectedDoc ? (
              <div className="flex min-h-[520px] flex-col">
                <div className="border-b border-surface-border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="truncate text-base font-semibold text-text">{selectedDoc.title}</h2>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-text-dim">
                        <span className="rounded bg-surface-hover px-2 py-1">{selectedDoc.type || "note"}</span>
                        <span className="rounded bg-warning/10 px-2 py-1 text-warning">{selectedDoc.status}</span>
                        <span>{selectedDoc.path}</span>
                      </div>
                    </div>
                    <button type="button" onClick={() => setSelected(null)} className="rounded border border-surface-border px-2 py-1 text-xs text-text-muted hover:bg-surface-hover">Close</button>
                  </div>
                </div>
                <div className="min-h-0 flex-1 p-4">
                  <SourceTextEditor value={draftContent} onChange={setDraftContent} language="markdown" minHeight={420} />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-border p-4">
                  <div className="text-xs text-text-dim">
                    {draftDirty ? "Unsaved edits" : writeDoc.isSuccess ? "Saved" : "Up to date"}
                    {writeDoc.isError ? <span className="ml-2 text-danger">Save failed</span> : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={!draftDirty || selectedBusy}
                      onClick={() => writeDoc.mutate({ content: draftContent, baseHash: selectedDoc.content_hash })}
                      className="inline-flex items-center gap-2 rounded border border-surface-border px-3 py-2 text-sm text-text-muted disabled:opacity-50"
                    >
                      <Save size={15} />
                      Save
                    </button>
                    <button
                      type="button"
                      disabled={selectedBusy}
                      onClick={() => accept.mutate({ userId: selected.userId, slug: selected.slug }, { onSuccess: () => setSelected(null) })}
                      className="inline-flex items-center gap-2 rounded bg-success px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                    >
                      <Check size={15} />
                      Accept
                    </button>
                    <button
                      type="button"
                      disabled={selectedBusy}
                      onClick={() => reject.mutate({ userId: selected.userId, slug: selected.slug }, { onSuccess: () => setSelected(null) })}
                      className="inline-flex items-center gap-2 rounded border border-danger/40 px-3 py-2 text-sm font-medium text-danger disabled:opacity-50"
                    >
                      <X size={15} />
                      Reject
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-5 text-sm text-danger">Could not load selected entry.</div>
            )}
          </aside>
        )}
      </main>
    </div>
  );
}
