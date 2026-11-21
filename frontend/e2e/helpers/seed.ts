import { readFileSync } from "node:fs";
import path from "node:path";

export const BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";
/** Synthetic accounts only. Never reuse a real password. */
export const PASSWORD = "E2e-Clinic-Passw0rd!2026";

const dir = path.resolve(__dirname, "..");
export const seedFile = path.join(dir, ".seed.json");
export const authFile = (role: Role): string => path.join(dir, ".auth", `${role}.json`);

/** The platform administrator (created with `python -m app.cli create-superadmin`), signed in once by global setup. */
export const platformAuthFile = path.join(dir, ".auth", "platform.json");

export type Role = "admin" | "reception" | "doctor" | "patient";

export interface Seed {
  run: string;
  clinicId: string;
  clinicName: string;
  doctorId: string;
  patientName: string;
  emails: Record<Role, string>;
}

export const readSeed = (): Seed => JSON.parse(readFileSync(seedFile, "utf8")) as Seed;
