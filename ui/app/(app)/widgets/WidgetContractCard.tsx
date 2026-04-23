import type { WidgetContract } from "@/src/types/api";

interface ContractField {
  label: string;
  value: string;
}

function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function joinList(values: string[]): string {
  return values.length > 0 ? values.join(", ") : "None declared";
}

function summarizeActionIds(contract: WidgetContract | null | undefined): string {
  return joinList((contract?.actions ?? []).map((action) => action.id));
}

function toFields(contract: WidgetContract): ContractField[] {
  return [
    { label: "Definition", value: titleCase(contract.definition_kind) },
    { label: "Binding", value: titleCase(contract.binding_kind) },
    { label: "Instantiation", value: titleCase(contract.instantiation_kind) },
    { label: "Auth", value: titleCase(contract.auth_model) },
    { label: "State", value: titleCase(contract.state_model) },
    { label: "Refresh", value: titleCase(contract.refresh_model) },
    {
      label: "Theme",
      value: contract.theme_model ? titleCase(contract.theme_model) : "Not declared",
    },
    {
      label: "Supported scopes",
      value: contract.supported_scopes && contract.supported_scopes.length > 0
        ? contract.supported_scopes.map(titleCase).join(", ")
        : "No explicit scope restrictions declared",
    },
    { label: "Actions", value: summarizeActionIds(contract) },
  ];
}

export function WidgetContractCard({
  contract,
  title = "Contract",
}: {
  contract: WidgetContract | null | undefined;
  title?: string;
}) {
  if (!contract) return null;
  const fields = toFields(contract);
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
        {title}
      </div>
      <div className="mt-2 space-y-2">
        {fields.map((field) => (
          <div
            key={field.label}
            className="grid grid-cols-[92px_minmax(0,1fr)] items-start gap-2 text-[11px]"
          >
            <div className="font-semibold uppercase tracking-wide text-text-dim">
              {field.label}
            </div>
            <div className="leading-snug text-text-muted">
              {field.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
