import { useMemo, useState } from "react";
import {
  Activity,
  AlarmClock,
  Anchor,
  Archive,
  AtSign,
  Award,
  BarChart,
  BarChart3,
  Battery,
  Bell,
  Bike,
  Book,
  BookMarked,
  BookOpen,
  Bookmark,
  Box,
  Briefcase,
  Bug,
  Building,
  Calendar,
  Camera,
  Car,
  ChefHat,
  Cloud,
  CloudRain,
  Code,
  Coffee,
  Compass,
  Cpu,
  CreditCard,
  Database,
  Disc,
  DollarSign,
  Download,
  Dumbbell,
  Feather,
  Film,
  Flag,
  Flame,
  Flower,
  Folder,
  Gamepad2,
  Gauge,
  Gem,
  Gift,
  Globe,
  GraduationCap,
  Hammer,
  Hash,
  Headphones,
  Heart,
  Home,
  Image,
  Inbox,
  Key,
  Lamp,
  LayoutDashboard,
  Leaf,
  Lightbulb,
  Link,
  List,
  Lock,
  Mail,
  Map,
  MapPin,
  Megaphone,
  Mic,
  Moon,
  Mountain,
  Music,
  Newspaper,
  Package,
  Palette,
  PawPrint,
  Phone,
  PieChart,
  Pin,
  Pizza,
  Plane,
  Plug,
  Puzzle,
  Radio,
  Rocket,
  Ruler,
  Save,
  Scissors,
  Server,
  Settings,
  Shield,
  ShoppingBag,
  ShoppingCart,
  Smartphone,
  Smile,
  Speaker,
  Star,
  Sun,
  Tag,
  Target,
  Terminal,
  Thermometer,
  Timer,
  PenTool,
  Train,
  Trash,
  Trees,
  TrendingUp,
  Trophy,
  Truck,
  Tv,
  Umbrella,
  User,
  Users,
  Utensils,
  Video,
  Wallet,
  Watch,
  Wifi,
  Wrench,
  Zap,
} from "lucide-react";
import { cn } from "../lib/cn";

interface Props {
  value: string | null;
  onChange: (iconName: string | null) => void;
  /** Optional label displayed above the grid. */
  label?: string;
}

/** Curated rail-friendly icon set. Keys are the stored string names; values
 *  are the component references. This is the single source of truth for
 *  both the picker UI and the dynamic render path. */
export const RAIL_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  Activity, AlarmClock, Anchor, Archive, AtSign, Award,
  BarChart, BarChart3, Battery, Bell, Bike, Book, BookMarked, BookOpen,
  Bookmark, Box, Briefcase, Bug, Building,
  Calendar, Camera, Car, ChefHat, Cloud, CloudRain, Code, Coffee,
  Compass, Cpu, CreditCard,
  Database, Disc, DollarSign, Download, Dumbbell,
  Feather, Film, Flag, Flame, Flower, Folder,
  Gamepad2, Gauge, Gem, Gift, Globe, GraduationCap,
  Hammer, Hash, Headphones, Heart, Home,
  Image, Inbox,
  Key,
  Lamp, LayoutDashboard, Leaf, Lightbulb, Link, List, Lock,
  Mail, Map, MapPin, Megaphone, Mic, Moon, Mountain, Music,
  Newspaper,
  Package, Palette, PawPrint, Phone, PieChart, Pin, Pizza, Plane, Plug, Puzzle,
  Radio, Rocket, Ruler,
  Save, Scissors, Server, Settings, Shield, ShoppingBag, ShoppingCart,
  Smartphone, Smile, Speaker, Star, Sun,
  Tag, Target, Terminal, Thermometer, Timer, PenTool, Train, Trash, Trees,
  TrendingUp, Trophy, Truck, Tv,
  Umbrella, User, Users, Utensils,
  Video,
  Wallet, Watch, Wifi, Wrench,
  Zap,
};

const ICON_NAMES = Object.keys(RAIL_ICONS).sort();

export function IconPicker({ value, onChange, label }: Props) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ICON_NAMES;
    return ICON_NAMES.filter((name) => name.toLowerCase().includes(q));
  }, [query]);

  return (
    <div className="flex flex-col gap-2">
      {label && (
        <span className="text-[12px] font-medium text-text-muted">{label}</span>
      )}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search icons…"
          className="flex-1 rounded-md border border-surface-border bg-surface-raised px-2.5 py-1.5 text-[12px] text-text outline-none focus:border-accent/60"
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange(null)}
            className="rounded-md border border-surface-border px-2 py-1 text-[11px] text-text-muted hover:bg-surface-overlay"
            title="Clear icon"
          >
            Clear
          </button>
        )}
      </div>
      <div className="grid max-h-56 grid-cols-8 gap-1 overflow-auto rounded-md border border-surface-border bg-surface p-2">
        {filtered.map((name) => {
          const Icon = RAIL_ICONS[name];
          if (!Icon) return null;
          const active = value === name;
          return (
            <button
              key={name}
              type="button"
              onClick={() => onChange(name)}
              title={name}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-md border transition-colors",
                active
                  ? "border-accent/60 bg-accent/10 text-accent"
                  : "border-transparent text-text-muted hover:bg-surface-overlay",
              )}
            >
              <Icon size={16} />
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="col-span-8 py-4 text-center text-[12px] text-text-muted">
            No icons match "{query}"
          </div>
        )}
      </div>
    </div>
  );
}

/** Render a curated rail icon by name, falling back to LayoutDashboard for
 *  unknown names (stored name dropped from the set, etc.). Only icons in
 *  RAIL_ICONS are supported — tree-shake-friendly. */
export function LucideIconByName({
  name,
  size = 18,
  className,
}: {
  name: string | null | undefined;
  size?: number;
  className?: string;
}) {
  const Icon = (name && RAIL_ICONS[name]) || LayoutDashboard;
  return <Icon size={size} className={className} />;
}
