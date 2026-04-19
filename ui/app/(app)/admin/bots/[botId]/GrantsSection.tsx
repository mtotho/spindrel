import { useMemo, useState } from "react";
import { Trash2, UserPlus, Users } from "lucide-react";
import { Spinner } from "@/src/components/shared/Spinner";
import { UserSelect } from "@/src/components/shared/UserSelect";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import {
  useBotGrants,
  useCreateBotGrant,
  useDeleteBotGrant,
} from "@/src/api/hooks/useBotGrants";
import { useThemeTokens } from "@/src/theme/tokens";

/** Non-admin users who should be able to use this bot. Admins always have
 *  access, so they're filtered out of the picker. The bot owner is listed
 *  read-only for context. */
export function GrantsSection({
  botId,
  ownerUserId,
}: {
  botId: string | undefined;
  ownerUserId: string | null | undefined;
}) {
  const t = useThemeTokens();
  const { data: grants, isLoading } = useBotGrants(botId);
  const { data: users } = useAdminUsers();
  const createMut = useCreateBotGrant(botId);
  const deleteMut = useDeleteBotGrant(botId);
  const [pickedUser, setPickedUser] = useState<string | null>(null);

  const owner = useMemo(
    () => users?.find((u) => u.id === ownerUserId),
    [users, ownerUserId],
  );
  const grantedIds = useMemo(
    () => new Set((grants ?? []).map((g) => g.user_id)),
    [grants],
  );

  // Users who are neither admin, the owner, nor already granted
  const candidateUsers = useMemo(() => {
    if (!users) return [];
    return users.filter(
      (u) => !u.is_admin && u.id !== ownerUserId && !grantedIds.has(u.id),
    );
  }, [users, ownerUserId, grantedIds]);

  const canAdd = pickedUser && candidateUsers.some((u) => u.id === pickedUser);

  const handleAdd = async () => {
    if (!pickedUser) return;
    await createMut.mutateAsync({ user_id: pickedUser, role: "view" });
    setPickedUser(null);
  };

  if (!botId) {
    return (
      <div className="text-text-dim text-sm">
        Save the bot before managing grants.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="text-text text-base font-bold">Grants</div>
        <div className="text-text-dim text-xs mt-1">
          Let non-admin users talk to this bot and use widgets it emits. Admins
          always have access. The bot owner (set in Identity) also has access
          automatically.
        </div>
      </div>

      {owner && (
        <div className="flex flex-row items-center gap-3 bg-surface-raised border border-surface-border rounded-lg px-3 py-2">
          <Users size={14} color={t.textMuted} />
          <div className="flex-1 min-w-0">
            <div className="text-text text-sm">
              {owner.display_name}
              <span className="ml-2 text-text-dim text-xs">({owner.email})</span>
            </div>
            <div className="text-text-dim text-[11px]">Owner · implicit access</div>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <div className="text-text-muted text-[11px] uppercase tracking-wider">
          Granted users
        </div>

        {isLoading ? (
          <Spinner color={t.accent} />
        ) : grants && grants.length > 0 ? (
          <div className="flex flex-col gap-2">
            {grants.map((g) => (
              <div
                key={g.user_id}
                className="flex flex-row items-center gap-3 bg-surface-raised border border-surface-border rounded-lg px-3 py-2"
              >
                <UserPlus size={14} color={t.accent} />
                <div className="flex-1 min-w-0">
                  <div className="text-text text-sm">
                    {g.user_display_name}
                    <span className="ml-2 text-text-dim text-xs">
                      ({g.user_email})
                    </span>
                  </div>
                  <div className="text-text-dim text-[11px]">
                    {g.role} · granted {new Date(g.created_at).toLocaleDateString()}
                    {g.granted_by_display_name
                      ? ` by ${g.granted_by_display_name}`
                      : ""}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => deleteMut.mutate(g.user_id)}
                  disabled={deleteMut.isPending}
                  className="p-2 rounded hover:bg-surface-overlay disabled:opacity-50"
                  title="Revoke"
                >
                  <Trash2 size={14} color={t.textMuted} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-text-dim text-sm">
            No grants yet. Non-admin users will see a 403 when their viewer tries
            to fetch data from this bot's widgets.
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2 pt-2 border-t border-surface-border">
        <div className="text-text-muted text-[11px] uppercase tracking-wider">
          Grant access
        </div>
        {candidateUsers.length === 0 ? (
          <div className="text-text-dim text-xs">
            Every non-admin user already has access (or the user list is empty).
          </div>
        ) : (
          <div className="flex flex-row items-center gap-2">
            <div className="flex-1">
              <UserSelect
                value={pickedUser}
                onChange={setPickedUser}
                noneLabel="Pick a user…"
              />
            </div>
            <button
              type="button"
              onClick={handleAdd}
              disabled={!canAdd || createMut.isPending}
              className="px-3 py-2 rounded bg-accent text-white text-sm disabled:opacity-50"
            >
              {createMut.isPending ? "Granting…" : "Grant access"}
            </button>
          </div>
        )}
        {createMut.isError && (
          <div className="text-red-400 text-xs">
            {(createMut.error as Error)?.message ?? "Grant failed."}
          </div>
        )}
      </div>
    </div>
  );
}
