import { DocsMarkdownModal } from "@/src/components/shared/DocsMarkdownModal";

interface Props {
  onClose: () => void;
}

export function WidgetTemplatesDocsModal({ onClose }: Props) {
  return (
    <DocsMarkdownModal
      path="widget-templates"
      title="Widget Authoring"
      errorMessage="Failed to load widget authoring documentation."
      onClose={onClose}
    />
  );
}
