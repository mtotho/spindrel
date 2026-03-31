export default function LoadingSpinner({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center justify-center p-8 ${className}`}>
      <div className="w-6 h-6 border-2 border-surface-4 border-t-accent rounded-full animate-spin" />
    </div>
  );
}
