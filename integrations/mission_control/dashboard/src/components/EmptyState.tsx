interface EmptyStateProps {
  icon?: string;
  title: string;
  description: string;
  action?: {
    label: string;
    onClick?: () => void;
    href?: string;
  };
}

export default function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
      {icon && <span className="text-3xl mb-3 opacity-50">{icon}</span>}
      <h3 className="text-sm font-medium text-gray-300">{title}</h3>
      <p className="text-xs text-gray-500 mt-1 max-w-sm">{description}</p>
      {action && (
        action.href ? (
          <a
            href={action.href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 text-xs text-accent hover:text-accent-hover underline underline-offset-2"
          >
            {action.label}
          </a>
        ) : action.onClick ? (
          <button
            onClick={action.onClick}
            className="mt-3 text-xs bg-accent hover:bg-accent-hover text-white px-3 py-1.5 rounded-lg transition-colors"
          >
            {action.label}
          </button>
        ) : null
      )}
    </div>
  );
}
