/** Whether to show the "synthetic data only" banner. On unless the setting is explicitly "false", so a missing or mistyped value keeps the notice. */
export function showDemoBanner(setting: string | undefined): boolean {
  return (setting ?? "").trim().toLowerCase() !== "false";
}
