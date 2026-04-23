import { DocsMarkdownModal } from "@/src/components/shared/DocsMarkdownModal";

interface Props {
  onClose: () => void;
}

export function IntegrationGuideModal({ onClose }: Props) {
  return (
    <DocsMarkdownModal
      path="integrations/index"
      title="Integration Guide"
      errorMessage="Failed to load integration documentation."
      width={680}
      onClose={onClose}
    />
  );
}
