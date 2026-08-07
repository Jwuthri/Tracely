import { redirect } from "next/navigation";

/** The OpenRouter key now lives with the ingest keys on one "API keys" page. Several banners and
 *  inline notices link here, so the route stays as a redirect rather than becoming a 404. */
export default function LlmSettingsPage() {
  redirect("/settings/api-keys");
}
