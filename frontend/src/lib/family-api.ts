import { apiFetch } from "./api";
import type { PermissionScope } from "./scopes";

export interface FamilyMemberOut {
  id: number;
  user_id: number;
  email: string;
  scopes: PermissionScope[];
  created_at: string;
}

export interface FamilyInviteOut {
  id: number;
  family_id: number;
  family_name: string;
  owner_email: string;
  email: string;
  scopes: PermissionScope[];
  expires_at: string;
  created_at: string;
}

export interface FamilyOverviewOut {
  is_owner: boolean;
  family_id: number | null;
  family_name: string | null;
  owner_email: string | null;
  my_scopes: PermissionScope[];
  members: FamilyMemberOut[];
  outgoing_invites: FamilyInviteOut[];
  incoming_invites: FamilyInviteOut[];
}

export function fetchFamily(): Promise<FamilyOverviewOut> {
  return apiFetch<FamilyOverviewOut>("/family");
}

export function addFamilyMember(params: {
  email: string;
  scopes: PermissionScope[];
  initial_password?: string;
}): Promise<FamilyOverviewOut> {
  return apiFetch<FamilyOverviewOut>("/family/members", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export function updateFamilyMemberScopes(
  memberId: number,
  scopes: PermissionScope[],
): Promise<FamilyMemberOut> {
  return apiFetch<FamilyMemberOut>(`/family/members/${memberId}`, {
    method: "PATCH",
    body: JSON.stringify({ scopes }),
  });
}

export function removeFamilyMember(memberId: number): Promise<void> {
  return apiFetch<void>(`/family/members/${memberId}`, {
    method: "DELETE",
  });
}

export function acceptFamilyInvite(inviteId: number): Promise<{ message: string }> {
  return apiFetch<{ message: string }>(`/family/invites/${inviteId}/accept`, {
    method: "POST",
  });
}

export function deleteFamilyInvite(inviteId: number): Promise<void> {
  return apiFetch<void>(`/family/invites/${inviteId}`, {
    method: "DELETE",
  });
}
