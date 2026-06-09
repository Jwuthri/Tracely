// Shared auth types — safe to import from client components (no server-only side effects here).

export type Role = "OWNER" | "ADMIN" | "MEMBER" | string;
export type AuthMode = "dev" | "local" | "clerk";

export type ProjectRef = { id: string; name: string; slug: string; role: Role };

export type Me = {
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  role: Role | null;
  project_id: string;
  project_name: string | null;
  projects: ProjectRef[];
  ingest_keys: string[];
};

export type Session = { token: string };
