import { SelectInput } from "./FormControls";
import { useAdminUsers } from "../../api/hooks/useAdminUsers";

interface Props {
  value: string | null | undefined;
  onChange: (v: string | null) => void;
  /** Label for the null/none option. Defaults to "None". */
  noneLabel?: string;
  /** Omit the none option entirely (forces a user). */
  required?: boolean;
}

export function UserSelect({ value, onChange, noneLabel = "None", required }: Props) {
  const { data: users } = useAdminUsers();
  const options = [
    ...(required ? [] : [{ label: noneLabel, value: "" }]),
    ...(users?.map((u) => ({
      label: `${u.display_name} (${u.email})`,
      value: u.id,
    })) ?? []),
  ];
  return (
    <SelectInput
      value={value ?? ""}
      onChange={(v) => onChange(v || null)}
      options={options}
    />
  );
}
