/**
 * TaskCreateModal — re-exports TaskCreateWizard with the original interface.
 *
 * This preserves backward compatibility so admin/tasks/index.tsx doesn't need changes.
 */
export { TaskCreateWizard as TaskCreateModal } from "./task/TaskCreateWizard";
export type { TaskCreateWizardProps as TaskCreateModalProps } from "./task/TaskCreateWizard";
export { ChipPicker } from "./task/ChipPicker";
