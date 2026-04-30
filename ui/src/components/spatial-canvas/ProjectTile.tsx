import { useId, useMemo, type ReactNode } from "react";
import { FolderGit2 } from "lucide-react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { WorkspaceMapObjectState } from "../../api/types/workspaceMapState";
import { ObjectStatusPill, mapCueIntent, statusRingClass } from "./SpatialObjectStatus";
import {
  projectBodyTraits,
  projectMoonRenderProps,
  type ProjectBodyTraits,
} from "./projectCosmicBody";

interface ProjectTileProps {
  node: SpatialNode;
  zoom: number;
  extraScale?: number;
  workState?: WorkspaceMapObjectState | null;
  onSelect?: () => void;
  onOpen?: () => void;
}

const DOT_THRESHOLD = 0.34;
const SNAPSHOT_THRESHOLD = 0.86;
const OVERVIEW_MIN_DOT_SCREEN_PX = 36;
const OVERVIEW_MIN_LABEL_SCREEN_PX = 14;

function projectName(node: SpatialNode): string {
  return node.project?.name || "Project";
}

function projectChannelCount(node: SpatialNode, workState?: WorkspaceMapObjectState | null): number {
  return node.project?.attached_channel_count ?? workState?.counts.channels ?? 0;
}

export function ProjectTile({ node, zoom, extraScale = 1, workState, onSelect, onOpen }: ProjectTileProps) {
  const effectiveZoom = zoom * extraScale;
  if (effectiveZoom < DOT_THRESHOLD) {
    return <ProjectSystemDot node={node} zoom={zoom} extraScale={extraScale} workState={workState} onSelect={onSelect} onOpen={onOpen} />;
  }
  if (effectiveZoom < SNAPSHOT_THRESHOLD) {
    return <ProjectPlanetView node={node} workState={workState} onSelect={onSelect} onOpen={onOpen} tier="preview" />;
  }
  return <ProjectPlanetView node={node} workState={workState} onSelect={onSelect} onOpen={onOpen} tier="snapshot" />;
}

function ProjectShell({
  node,
  children,
  onSelect,
  onOpen,
}: {
  node: SpatialNode;
  children: ReactNode;
  onSelect?: () => void;
  onOpen?: () => void;
}) {
  const name = projectName(node);
  return (
    <div
      data-tile-kind="project"
      data-spatial-object-id={node.project_id ?? node.id}
      data-spatial-object-label={name}
      className="group relative h-full w-full cursor-pointer outline-none"
      onClick={(event) => {
        event.stopPropagation();
        onSelect?.();
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onOpen?.();
      }}
      role="button"
      tabIndex={0}
      aria-label={`Project ${name}`}
    >
      {children}
    </div>
  );
}

function ProjectSystemDot({
  node,
  zoom,
  extraScale,
  workState,
  onSelect,
  onOpen,
}: {
  node: SpatialNode;
  zoom: number;
  extraScale: number;
  workState?: WorkspaceMapObjectState | null;
  onSelect?: () => void;
  onOpen?: () => void;
}) {
  const name = projectName(node);
  const count = projectChannelCount(node, workState);
  const traits = useMemo(() => projectBodyTraits(node.project_id ?? node.id, count), [count, node.id, node.project_id]);
  const effectiveScale = Math.max(0.05, zoom) * Math.max(0.05, extraScale);
  const dotScale = Math.min(4.8, Math.max(1, OVERVIEW_MIN_DOT_SCREEN_PX / (132 * effectiveScale)));
  const labelScale = Math.min(12, Math.max(1, OVERVIEW_MIN_LABEL_SCREEN_PX / (16 * effectiveScale)));
  return (
    <ProjectShell node={node} onSelect={onSelect} onOpen={onOpen}>
      <div className="absolute left-1/2 top-1/2 flex w-[300px] -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center gap-3">
        <div
          className={`relative h-[132px] w-[132px] rounded-full ${statusRingClass(workState)}`}
          style={{ transform: `scale(${dotScale})`, transformOrigin: "center center" }}
        >
          <ProjectPlanetSvg traits={traits} channelCount={count} tier="dot" />
        </div>
        <div
          className="max-w-full truncate px-2 text-base font-semibold text-text"
          style={{ transform: `scale(${labelScale})`, transformOrigin: "center top" }}
        >
          {name}
        </div>
      </div>
    </ProjectShell>
  );
}

function ProjectPlanetView({
  node,
  workState,
  onSelect,
  onOpen,
  tier,
}: {
  node: SpatialNode;
  workState?: WorkspaceMapObjectState | null;
  onSelect?: () => void;
  onOpen?: () => void;
  tier: "preview" | "snapshot";
}) {
  const name = projectName(node);
  const count = projectChannelCount(node, workState);
  const traits = useMemo(() => projectBodyTraits(node.project_id ?? node.id, count), [count, node.id, node.project_id]);
  const cue = workState?.cue ? mapCueIntent(workState) : null;
  const projectMeta = count === 1 ? "1 channel" : `${count} channels`;
  return (
    <ProjectShell node={node} onSelect={onSelect} onOpen={onOpen}>
      <ProjectPlanetSvg traits={traits} channelCount={count} tier={tier} />
      <div className="absolute inset-x-8 top-6 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 rounded-full bg-surface/64 px-2.5 py-1 text-text ring-1 ring-surface-border/40 backdrop-blur-sm">
          <FolderGit2 size={tier === "snapshot" ? 16 : 14} className="shrink-0 text-text-muted" strokeWidth={2} />
          <span className="truncate text-sm font-semibold leading-tight">{name}</span>
        </div>
        {tier === "snapshot" && <ObjectStatusPill state={workState} compact iconOnly />}
      </div>
      <div className="absolute inset-x-10 bottom-8 flex items-center justify-center gap-2">
        <div className="max-w-[220px] truncate rounded-full bg-surface/70 px-2.5 py-1 text-[11px] font-medium text-text-muted ring-1 ring-surface-border/45 backdrop-blur-sm">
          {projectMeta}
        </div>
        {tier === "snapshot" && cue && (
          <div className="max-w-[130px] truncate rounded-full bg-surface/70 px-2 py-1 text-[10px] font-medium text-text-dim ring-1 ring-surface-border/40 backdrop-blur-sm">
            {workState?.cue?.label}
          </div>
        )}
      </div>
    </ProjectShell>
  );
}

function ProjectPlanetSvg({
  traits,
  channelCount,
  tier,
}: {
  traits: ProjectBodyTraits;
  channelCount: number;
  tier: "dot" | "preview" | "snapshot";
}) {
  const uid = useId().replace(/[:]/g, "");
  const moons = traits.moons.map((moon) => projectMoonRenderProps(moon, traits.hue));
  const showDetail = tier !== "dot";
  const showOverflow = traits.overflowCount > 0 && tier !== "dot";
  const haloAlpha = tier === "snapshot" ? 0.34 : tier === "preview" ? 0.27 : 0.2;
  return (
    <svg
      aria-hidden
      viewBox="0 0 220 180"
      preserveAspectRatio="xMidYMid meet"
      className="absolute inset-0 h-full w-full pointer-events-none"
      style={{ overflow: "visible" }}
    >
      <defs>
        <radialGradient id={`project-atm-${uid}`} cx="50%" cy="46%" r="58%">
          <stop offset="0%" stopColor={`hsla(${traits.hue}, 72%, 64%, 0)`} />
          <stop offset="58%" stopColor={`hsla(${traits.hue}, 72%, 64%, 0)`} />
          <stop offset="76%" stopColor={`hsla(${traits.hue}, 84%, 72%, ${haloAlpha})`} />
          <stop offset="100%" stopColor={`hsla(${traits.hue}, 84%, 72%, 0)`} />
        </radialGradient>
        <radialGradient id={`project-core-${uid}`} cx="34%" cy="30%" r="72%">
          <stop offset="0%" stopColor={`hsl(${traits.hue}, 78%, 80%)`} />
          <stop offset="42%" stopColor={`hsl(${traits.hue}, 62%, 54%)`} />
          <stop offset="76%" stopColor={`hsl(${traits.accentHue}, 54%, 28%)`} />
          <stop offset="100%" stopColor={`hsl(${traits.accentHue}, 48%, 15%)`} />
        </radialGradient>
        <linearGradient id={`project-shell-${uid}`} x1="20%" y1="0%" x2="80%" y2="100%">
          <stop offset="0%" stopColor={`hsla(${traits.hue}, 70%, 80%, 0.78)`} />
          <stop offset="56%" stopColor={`hsla(${traits.accentHue}, 60%, 62%, 0.34)`} />
          <stop offset="100%" stopColor={`hsla(${traits.accentHue}, 56%, 38%, 0.05)`} />
        </linearGradient>
        <clipPath id={`project-clip-${uid}`}>
          <circle cx="110" cy="78" r="55" />
        </clipPath>
        <clipPath id={`project-shell-front-${uid}`}>
          <rect x="0" y="78" width="220" height="102" />
        </clipPath>
      </defs>

      <ellipse cx="110" cy="78" rx="92" ry="62" fill={`url(#project-atm-${uid})`} />

      {showDetail && (
        <>
          <ellipse
            cx="110"
            cy="78"
            rx="86"
            ry={traits.shellRy}
            fill="none"
            stroke={`url(#project-shell-${uid})`}
            strokeWidth="2.4"
            strokeOpacity="0.7"
            transform={`rotate(${traits.shellTiltDeg.toFixed(1)} 110 78)`}
          />
          <ellipse
            cx="110"
            cy="78"
            rx="108"
            ry={(traits.shellRy + 17).toFixed(1)}
            fill="none"
            stroke={`hsla(${traits.hue}, 70%, 74%, 0.17)`}
            strokeWidth="1.2"
            strokeDasharray="5 9"
            transform={`rotate(${(traits.shellTiltDeg - 8).toFixed(1)} 110 78)`}
          />
        </>
      )}

      {moons.map((moon, index) => (
        <g key={index}>
          <circle cx={moon.cx.toFixed(2)} cy={moon.cy.toFixed(2)} r={moon.r.toFixed(2)} fill={moon.fill} opacity="0.96" />
          <circle
            cx={(moon.cx + moon.r * 0.38).toFixed(2)}
            cy={(moon.cy + moon.r * 0.4).toFixed(2)}
            r={(moon.r * 0.66).toFixed(2)}
            fill={moon.shadowFill}
            opacity="0.44"
          />
        </g>
      ))}

      <circle cx="110" cy="78" r="55" fill={`url(#project-core-${uid})`} />

      <g clipPath={`url(#project-clip-${uid})`}>
        {traits.bands.map((band, index) => (
          <ellipse
            key={index}
            cx="110"
            cy={band.y.toFixed(2)}
            rx="70"
            ry={band.height.toFixed(2)}
            fill={`hsla(${traits.accentHue}, 64%, 72%, ${band.alpha.toFixed(3)})`}
            transform={`rotate(${(traits.shellTiltDeg * 0.42).toFixed(1)} 110 ${band.y.toFixed(2)})`}
          />
        ))}
        <path
          d="M58 91 C78 70, 101 74, 119 62 C137 50, 151 60, 164 47 L172 67 C151 70, 138 82, 121 88 C97 96, 77 91, 61 110 Z"
          fill={`hsla(${traits.hue}, 68%, 76%, 0.16)`}
        />
        {traits.craters.map((crater, index) => (
          <circle
            key={index}
            cx={crater.x.toFixed(2)}
            cy={crater.y.toFixed(2)}
            r={crater.r.toFixed(2)}
            fill={`rgba(0, 0, 0, ${crater.alpha.toFixed(3)})`}
          />
        ))}
      </g>

      <ellipse cx="91" cy="54" rx="15" ry="9" fill="rgba(255, 255, 255, 0.22)" />
      <circle cx="110" cy="78" r="55" fill="none" stroke="rgba(255, 255, 255, 0.13)" strokeWidth="1" />

      {showDetail && (
        <ellipse
          cx="110"
          cy="78"
          rx="86"
          ry={traits.shellRy}
          fill="none"
          stroke={`hsla(${traits.hue}, 72%, 78%, 0.58)`}
          strokeWidth="2"
          transform={`rotate(${traits.shellTiltDeg.toFixed(1)} 110 78)`}
          clipPath={`url(#project-shell-front-${uid})`}
        />
      )}

      {showOverflow && (
        <g>
          <circle cx="171" cy="126" r="11" fill="rgb(var(--color-surface))" opacity="0.86" />
          <circle cx="171" cy="126" r="11" fill={`hsla(${traits.hue}, 70%, 70%, 0.22)`} />
          <text x="171" y="130" textAnchor="middle" fontSize="9" fontWeight="700" fill="rgb(var(--color-text-muted))">
            +{traits.overflowCount}
          </text>
        </g>
      )}

      {tier === "dot" && channelCount > 0 && (
        <circle cx="154" cy="41" r="7" fill={`hsl(${traits.accentHue}, 60%, 66%)`} opacity="0.9" />
      )}
    </svg>
  );
}
