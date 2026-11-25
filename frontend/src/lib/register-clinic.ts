import { isValidTimeZone } from "./setup";

/**
 * Rules for the "Register a clinic" form. They mirror the API (ClinicCreate in backend/app/api/v1/clinics.py) so people get
 * feedback before sending, but the API checks again and is the authority.
 */
export const NAME_MIN = 2;
export const NAME_MAX = 200;
export const SLUG_MIN = 3;
export const SLUG_MAX = 63;
/** Same pattern as the API: starts and ends with a letter or digit, hyphens allowed inside, 3 to 63 characters. */
export const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/;

export interface RegistrationForm { name: string; slug: string; timezone: string }
export type RegistrationErrors = Partial<Record<keyof RegistrationForm, string>>;

/** A web address suggested from the clinic's name: "Lakeside Family Clinic" becomes "lakeside-family-clinic". Accents are dropped
 *  ("Café" becomes "cafe"); letters with no Latin form are dropped too, so a name with none gives "" and the person types an address. */
export function slugFromName(name: string): string {
  return name
    .normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, SLUG_MAX)
    .replace(/-+$/g, "");
}

/** The visitor's own time zone when the browser knows a valid one, otherwise UTC. */
export function defaultTimeZone(): string {
  try {
    const zone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone && isValidTimeZone(zone) ? zone : "UTC";
  } catch {
    return "UTC";
  }
}

export function validateRegistration(form: RegistrationForm): RegistrationErrors {
  const errors: RegistrationErrors = {};
  const name = form.name.trim();
  if (name.length < NAME_MIN) errors.name = `Enter the clinic's name (at least ${NAME_MIN} characters).`;
  else if (name.length > NAME_MAX) errors.name = `Use ${NAME_MAX} characters or fewer.`;

  const slug = form.slug.trim().toLowerCase();
  if (slug.length < SLUG_MIN) errors.slug = `Use at least ${SLUG_MIN} characters.`;
  else if (slug.length > SLUG_MAX) errors.slug = `Use ${SLUG_MAX} characters or fewer.`;
  else if (!SLUG_PATTERN.test(slug)) errors.slug = "Use lowercase letters, digits and hyphens only, starting and ending with a letter or digit.";

  if (!isValidTimeZone(form.timezone.trim())) errors.timezone = "Choose a time zone from the list, for example Asia/Dhaka.";
  return errors;
}

/** The exact body the API accepts, with surrounding spaces removed and the address in lower case. */
export function registrationBody(form: RegistrationForm): RegistrationForm {
  return { name: form.name.trim(), slug: form.slug.trim().toLowerCase(), timezone: form.timezone.trim() };
}

/** What to tell a clinic's own staff while it cannot yet be used. `null` means it is open and needs no note. */
export function clinicStatusNote(status: string | undefined): string | null {
  if (status === "PENDING") return "Waiting for approval by a platform administrator";
  if (status === "SUSPENDED") return "Closed by a platform administrator";
  return null;
}
