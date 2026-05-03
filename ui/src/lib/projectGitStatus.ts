import type { ProjectGitRepoStatus } from "@/src/types/api";

type LegacyProjectGitRepoStatus = ProjectGitRepoStatus & {
  clean?: boolean;
  files?: string[];
  errors?: string[];
};

export function projectGitRepoError(repo: ProjectGitRepoStatus): string | null {
  const legacy = repo as LegacyProjectGitRepoStatus;
  return repo.error || legacy.errors?.filter(Boolean).join("\n") || null;
}

export function projectGitStatusLines(repo: ProjectGitRepoStatus): string[] {
  const legacy = repo as LegacyProjectGitRepoStatus;
  return repo.status_lines ?? legacy.files ?? [];
}

export function projectGitRepoDirty(repo: ProjectGitRepoStatus): boolean {
  const legacy = repo as LegacyProjectGitRepoStatus;
  return repo.dirty ?? !legacy.clean;
}
