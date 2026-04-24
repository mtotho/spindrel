export function sessionMachineTargetPath(sessionId: string): string {
  return `/api/v1/sessions/${sessionId}/machine-target`;
}

export function sessionMachineTargetLeasePath(sessionId: string): string {
  return `/api/v1/sessions/${sessionId}/machine-target/lease`;
}

export function adminMachinesPath(): string {
  return "/api/v1/admin/machines";
}

export function adminMachineEnrollPath(providerId: string): string {
  return `/api/v1/admin/machines/providers/${encodeURIComponent(providerId)}/enroll`;
}

export function adminMachineTargetPath(providerId: string, targetId: string): string {
  return `/api/v1/admin/machines/providers/${encodeURIComponent(providerId)}/targets/${encodeURIComponent(targetId)}`;
}

export function adminMachineProfilesPath(providerId: string): string {
  return `/api/v1/admin/machines/providers/${encodeURIComponent(providerId)}/profiles`;
}

export function adminMachineProfilePath(providerId: string, profileId: string): string {
  return `/api/v1/admin/machines/providers/${encodeURIComponent(providerId)}/profiles/${encodeURIComponent(profileId)}`;
}
