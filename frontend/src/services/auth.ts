import { api } from "@/lib/api";
import type { AuthResponse, MeResponse, User } from "@/types/api";

export const authService = {
  me: () => api.get<MeResponse>("/auth/me"),
  login: (email: string, password: string) => api.post<AuthResponse>("/auth/login", { email, password }),
  register: (body: { email: string; password: string; full_name: string; phone?: string }) =>
    api.post<User>("/auth/register", body),
  logout: () => api.post<void>("/auth/logout"),
};
