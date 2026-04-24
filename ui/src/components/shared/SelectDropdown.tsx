import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search, X } from "lucide-react";

export interface SelectDropdownOption {
  value: string;
  label: React.ReactNode;
  description?: React.ReactNode;
  meta?: React.ReactNode;
  icon?: React.ReactNode;
  group?: string;
  groupLabel?: string;
  searchText?: string;
  disabled?: boolean;
}

type PopoverWidth = "content" | "trigger" | "wide" | number;
type DropdownSize = "sm" | "md" | "compact";

interface SelectDropdownProps {
  value: string | null | undefined;
  options: SelectDropdownOption[];
  onChange: (value: string, option: SelectDropdownOption) => void;
  placeholder?: React.ReactNode;
  disabled?: boolean;
  allowClear?: boolean;
  clearLabel?: string;
  onClear?: () => void;
  searchable?: boolean;
  searchPlaceholder?: string;
  emptyLabel?: React.ReactNode;
  loading?: boolean;
  loadingLabel?: React.ReactNode;
  size?: DropdownSize;
  popoverWidth?: PopoverWidth;
  maxHeight?: number;
  zIndex?: number;
  leadingIcon?: React.ReactNode;
  renderValue?: (option: SelectDropdownOption) => React.ReactNode;
  renderOption?: (option: SelectDropdownOption, state: { selected: boolean; active: boolean }) => React.ReactNode;
  triggerClassName?: string;
  popoverClassName?: string;
}

function optionText(option: SelectDropdownOption): string {
  if (option.searchText) return option.searchText;
  const parts = [option.value];
  if (typeof option.label === "string") parts.push(option.label);
  if (typeof option.description === "string") parts.push(option.description);
  if (typeof option.meta === "string") parts.push(option.meta);
  if (option.groupLabel) parts.push(option.groupLabel);
  return parts.join(" ");
}

function popoverWidthFor(rect: DOMRect, mode: PopoverWidth): number {
  if (typeof mode === "number") return mode;
  if (mode === "trigger") return rect.width;
  if (mode === "wide") return Math.min(Math.max(rect.width, 420), 680);
  return Math.min(Math.max(rect.width, 300), 520);
}

export function SelectDropdown({
  value,
  options,
  onChange,
  placeholder = "Select...",
  disabled = false,
  allowClear = false,
  clearLabel = "Clear selection",
  onClear,
  searchable = false,
  searchPlaceholder = "Search...",
  emptyLabel = "No options found",
  loading = false,
  loadingLabel = "Loading...",
  size = "md",
  popoverWidth = "content",
  maxHeight = 360,
  zIndex = 50000,
  leadingIcon,
  renderValue,
  renderOption,
  triggerClassName = "",
  popoverClassName = "",
}: SelectDropdownProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 300, bottom: 0, anchor: "bottom" as "bottom" | "top" });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const selected = options.find((option) => option.value === value) ?? null;

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return options;
    return options.filter((option) => optionText(option).toLowerCase().includes(term));
  }, [options, search]);

  const enabledOptions = filtered.filter((option) => !option.disabled);

  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect || typeof window === "undefined") return;
    const width = Math.min(popoverWidthFor(rect, popoverWidth), window.innerWidth - 24);
    const left = Math.min(Math.max(12, rect.left), Math.max(12, window.innerWidth - width - 12));
    const spaceBelow = window.innerHeight - rect.bottom;
    const anchor = spaceBelow < Math.min(maxHeight, 320) && rect.top > spaceBelow ? "top" : "bottom";
    setPos({
      top: rect.bottom + 5,
      left,
      width,
      bottom: window.innerHeight - rect.top + 5,
      anchor,
    });
  }, [maxHeight, popoverWidth]);

  const openDropdown = useCallback(() => {
    if (disabled) return;
    updatePosition();
    setOpen(true);
  }, [disabled, updatePosition]);

  const closeDropdown = useCallback(() => {
    setOpen(false);
    setSearch("");
    setActiveIndex(0);
  }, []);

  useEffect(() => {
    if (!open) return;
    updatePosition();
    const onResize = () => updatePosition();
    const onScroll = () => updatePosition();
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open || !searchable) return;
    requestAnimationFrame(() => searchRef.current?.focus());
  }, [open, searchable]);

  useEffect(() => {
    if (!open) return;
    const firstSelected = filtered.findIndex((option) => !option.disabled && option.value === value);
    setActiveIndex(Math.max(0, firstSelected));
  }, [filtered, open, value]);

  const selectOption = useCallback((option: SelectDropdownOption) => {
    if (option.disabled) return;
    onChange(option.value, option);
    closeDropdown();
  }, [closeDropdown, onChange]);

  const moveActive = useCallback((delta: number) => {
    if (enabledOptions.length === 0) return;
    const activeValue = filtered[activeIndex]?.value;
    const enabledIndex = Math.max(0, enabledOptions.findIndex((option) => option.value === activeValue));
    const nextEnabled = enabledOptions[(enabledIndex + delta + enabledOptions.length) % enabledOptions.length];
    const nextIndex = filtered.findIndex((option) => option.value === nextEnabled.value);
    setActiveIndex(Math.max(0, nextIndex));
  }, [activeIndex, enabledOptions, filtered]);

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDropdown();
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeDropdown();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActive(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(-1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = filtered[activeIndex];
      if (option) selectOption(option);
    }
  };

  const triggerSize =
    size === "compact"
      ? "min-h-[28px] px-2 py-1 text-[11px]"
      : size === "sm"
        ? "min-h-[34px] px-2.5 py-1.5 text-[12px]"
        : "min-h-[40px] px-3 py-2 text-[13px]";

  return (
    <div className="relative w-full">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? closeDropdown() : openDropdown())}
        onKeyDown={handleKeyDown}
        className={
          `flex w-full items-center gap-2 rounded-md bg-input text-left text-text transition-colors ` +
          `focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 disabled:cursor-default disabled:opacity-50 ` +
          `border ${open ? "border-accent/45 bg-surface-raised/70" : "border-input-border hover:border-surface-border"} ` +
          `${triggerSize} ${triggerClassName}`
        }
      >
        {selected?.icon ?? leadingIcon}
        <span className={`min-w-0 flex-1 truncate ${selected ? "text-text" : "text-text-dim"}`}>
          {selected ? (renderValue ? renderValue(selected) : selected.label) : placeholder}
        </span>
        {allowClear && selected ? (
          <span
            role="button"
            aria-label={clearLabel}
            tabIndex={-1}
            onClick={(event) => {
              event.stopPropagation();
              onClear?.();
              closeDropdown();
            }}
            className="inline-flex shrink-0 items-center rounded p-0.5 text-text-dim transition-colors hover:text-text-muted"
          >
            <X size={13} />
          </span>
        ) : (
          <ChevronDown size={14} className="shrink-0 text-text-dim" />
        )}
      </button>

      {open && typeof document !== "undefined" && createPortal(
        <>
          <div
            aria-hidden
            className="fixed inset-0"
            style={{ zIndex }}
            onMouseDown={closeDropdown}
          />
          <div
            ref={popoverRef}
            className={
              `fixed flex flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised ` +
              `ring-1 ring-black/10 ${popoverClassName}`
            }
            style={{
              ...(pos.anchor === "top"
                ? { bottom: pos.bottom, left: pos.left, width: pos.width }
                : { top: pos.top, left: pos.left, width: pos.width }),
              maxWidth: "calc(100vw - 24px)",
              zIndex: zIndex + 1,
            }}
            onKeyDown={handleKeyDown}
          >
            {searchable && (
              <div className="shrink-0 p-2">
                <div className="flex min-h-[34px] items-center gap-1.5 rounded-md bg-input px-2.5 text-text-dim focus-within:ring-2 focus-within:ring-accent/25">
                  <Search size={13} className="shrink-0" />
                  <input
                    ref={searchRef}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={searchPlaceholder}
                    className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
                  />
                  {search && (
                    <button
                      type="button"
                      onClick={() => setSearch("")}
                      className="inline-flex items-center text-text-dim transition-colors hover:text-text"
                      aria-label="Clear search"
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>
              </div>
            )}
            <div role="listbox" className="min-h-0 overflow-y-auto py-1" style={{ maxHeight }}>
              {loading ? (
                <div className="px-3 py-4 text-center text-[12px] text-text-dim">{loadingLabel}</div>
              ) : filtered.length === 0 ? (
                <div className="px-3 py-4 text-center text-[12px] text-text-dim">{emptyLabel}</div>
              ) : (
                filtered.map((option, index) => {
                  const selectedOption = option.value === value;
                  const active = index === activeIndex;
                  const prev = filtered[index - 1];
                  const showGroup = option.group && option.group !== prev?.group;
                  return (
                    <div key={`${option.group ?? "default"}:${option.value}`}>
                      {showGroup && (
                        <div className="sticky top-0 z-10 bg-surface-raised px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
                          {option.groupLabel ?? option.group}
                        </div>
                      )}
                      <button
                        type="button"
                        role="option"
                        aria-selected={selectedOption}
                        disabled={option.disabled}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => selectOption(option)}
                        className={
                          `flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors disabled:cursor-default disabled:opacity-50 ` +
                          (selectedOption
                            ? "bg-accent/[0.07] text-accent"
                            : active
                              ? "bg-surface-overlay/50 text-text"
                              : "bg-transparent text-text hover:bg-surface-overlay/45")
                        }
                      >
                        {renderOption ? (
                          renderOption(option, { selected: selectedOption, active })
                        ) : (
                          <>
                            {option.icon && <span className="mt-0.5 shrink-0 text-text-dim">{option.icon}</span>}
                            <span className="min-w-0 flex-1">
                              <span className={`block truncate text-[13px] font-medium ${selectedOption ? "text-accent" : "text-text"}`}>
                                {option.label}
                              </span>
                              {option.description && (
                                <span className="mt-0.5 block truncate text-[11px] leading-snug text-text-dim">
                                  {option.description}
                                </span>
                              )}
                            </span>
                            {option.meta && (
                              <span className="mt-0.5 shrink-0 text-[10px] text-text-dim">{option.meta}</span>
                            )}
                            {selectedOption && <Check size={13} className="mt-0.5 shrink-0 text-accent" />}
                          </>
                        )}
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </>,
        document.body
      )}
    </div>
  );
}
