/**
 * Centralized icon resolution and color utilities for all HUD components.
 * Add icons here as integrations declare them — one place to maintain.
 */
import {
  // Status / feedback
  CheckCircle, AlertTriangle, ShieldAlert, Info, AlertOctagon,
  // Content / feeds
  Rss, Mail, MessageSquare, FileText, Database,
  // Actions
  Activity, Zap, Play, RefreshCw, Send, Download, Upload,
  // Navigation
  ExternalLink, LayoutDashboard, Settings, Search,
  // Data
  BarChart2, TrendingUp, PieChart, Clock,
  // Communication
  MessageCircle, Pause,
  // Misc
  Circle, Plug, Bell, Eye, Loader2,
} from "lucide-react";
import type { ThemeTokens } from "@/src/theme/tokens";

type IconComponent = React.ComponentType<{ size: number; color: string }>;

const HUD_ICON_MAP: Record<string, IconComponent> = {
  // Status / feedback
  CheckCircle, AlertTriangle, ShieldAlert, Info, AlertOctagon,
  // Content / feeds
  Rss, Mail, MessageSquare, FileText, Database,
  // Actions
  Activity, Zap, Play, RefreshCw, Send, Download, Upload,
  // Navigation
  ExternalLink, LayoutDashboard, Settings, Search,
  // Data
  BarChart2, TrendingUp, PieChart, Clock,
  // Communication
  MessageCircle, Pause,
  // Misc
  Circle, Plug, Bell, Eye, Loader2,
};

/** Resolve a lucide icon name to a component. Falls back to Circle. */
export function resolveHudIcon(name: string | undefined): IconComponent {
  return (name && HUD_ICON_MAP[name]) || Circle;
}

export function variantColor(variant: string | undefined, t: ThemeTokens): string {
  switch (variant) {
    case "success": return t.success;
    case "warning": return t.warning;
    case "danger": return t.danger;
    case "accent": return t.accent;
    case "muted": return t.textDim;
    default: return t.textMuted;
  }
}

export function variantBg(variant: string | undefined, t: ThemeTokens): string {
  switch (variant) {
    case "success": return t.successSubtle;
    case "warning": return t.warningSubtle;
    case "danger": return t.dangerSubtle;
    case "accent": return t.accentSubtle;
    default: return t.surfaceOverlay;
  }
}
