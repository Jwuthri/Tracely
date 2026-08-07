// Shared auth types — safe to import from client components (no server-only side effects here).

export type Role = "OWNER" | "ADMIN" | "MEMBER" | string;
export type AuthMode = "dev" | "local" | "clerk";

export type OrgKind = "personal" | "company";

export type ProjectRef = {
  id: string;
  name: string;
  slug: string;
  role: Role;
  organization_id: string | null;
};

/** An account: `personal` holds one workspace and can't be joined, `company` is a team. */
export type OrgRef = {
  id: string;
  name: string;
  slug: string;
  kind: OrgKind;
  plan: string;
  role: Role;
};

export type Me = {
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  role: Role | null; // role in the ACTIVE organization
  project_id: string;
  project_name: string | null;
  organization_id: string | null;
  organization_name: string | null;
  organization_kind: OrgKind | null;
  organization_plan: string | null;
  projects: ProjectRef[];
  organizations: OrgRef[];
  ingest_keys: string[];
};

export type Member = {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
};

export type Session = { token: string };
