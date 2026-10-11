/**
 * Sign-in with Amazon Cognito (email + password), no extra dependency: the browser calls the
 * Cognito Identity Provider API directly, exactly as the AWS SDKs do.
 *
 *   VITE_COGNITO_CLIENT_ID   app client id (stack output UserPoolClientId). Without it, sign-in is off.
 *   VITE_COGNITO_REGION      defaults to ap-south-1
 *   VITE_AUTH_MODE=mock      LOCAL DEVELOPMENT ONLY: any email works, the token is "mock:<email>" and
 *                            only scripts/local_api.py accepts it. Never set this in Amplify.
 *
 * Tokens live in localStorage (the usual trade-off for a browser-only app: an XSS bug could read
 * them). The ID token is 1 hour; the refresh token 30 days. getIdToken() refreshes quietly.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { setTokenProvider } from "./api";

const CLIENT_ID = (import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined) ?? "";
const REGION = (import.meta.env.VITE_COGNITO_REGION as string | undefined) ?? "ap-south-1";
export const MOCK = import.meta.env.VITE_AUTH_MODE === "mock";
export const authEnabled = MOCK || !!CLIENT_ID;

const KEY = "session";
interface Session { idToken: string; refreshToken: string; expiresAt: number; email: string }
export interface User { email: string; groups: string[] }

export class AuthError extends Error {
  /** "needs_confirmation" lets the UI jump to the code step. */
  constructor(message: string, public code = "") { super(message); }
}

const FRIENDLY: Record<string, string> = {
  UsernameExistsException: "An account with this email already exists. Try signing in.",
  NotAuthorizedException: "Wrong email or password.",
  UserNotFoundException: "Wrong email or password.",
  CodeMismatchException: "That code is not right. Check the latest email.",
  ExpiredCodeException: "That code has expired. Ask for a new one.",
  InvalidPasswordException: "Use at least 8 characters with a number and a lowercase letter.",
  LimitExceededException: "Too many attempts. Wait a few minutes and try again.",
  TooManyRequestsException: "Too many attempts. Wait a few minutes and try again.",
  InvalidParameterException: "Please check the email and password format.",
};

async function idp<T>(op: string, body: Record<string, unknown>): Promise<T> {
  if (!CLIENT_ID) throw new AuthError("Sign-in is not set up on this deployment.");
  let r: Response;
  try {
    r = await fetch(`https://cognito-idp.${REGION}.amazonaws.com/`, {
      method: "POST",
      headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${op}` },
      body: JSON.stringify({ ClientId: CLIENT_ID, ...body }),
    });
  } catch {
    throw new AuthError("Can't reach the sign-in service. Check your connection.");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const type = String(data.__type ?? "").split("#").pop() ?? "";
    if (type === "UserNotConfirmedException") throw new AuthError("Please confirm your email first.", "needs_confirmation");
    throw new AuthError(FRIENDLY[type] ?? data.message ?? `Sign-in failed (${r.status}).`, type);
  }
  return data as T;
}

function decode(jwt: string): Record<string, unknown> {
  try {
    const p = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(p))));
  } catch {
    return {};
  }
}

function load(): Session | null {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) ?? "null") as Session | null;
    return s?.idToken && s.refreshToken ? s : null;
  } catch {
    return null;
  }
}
function save(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: the session just lasts until the tab closes */
  }
}

interface AuthResult { AuthenticationResult?: { IdToken: string; RefreshToken?: string; ExpiresIn: number } }

function toSession(res: AuthResult, email: string, prevRefresh?: string): Session {
  const a = res.AuthenticationResult;
  if (!a) throw new AuthError("Sign-in did not complete. Please try again.");
  return { idToken: a.IdToken, refreshToken: a.RefreshToken ?? prevRefresh ?? "", expiresAt: Date.now() + a.ExpiresIn * 1000, email };
}

let memory: Session | null = load();
let refreshing: Promise<string | null> | null = null;

/** A valid ID token, refreshing it if it is about to expire. Null when signed out. */
export async function getIdToken(): Promise<string | null> {
  const s = memory;
  if (!s) return null;
  if (MOCK || s.expiresAt - 60_000 > Date.now()) return s.idToken;
  refreshing ??= idp<AuthResult>("InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", AuthParameters: { REFRESH_TOKEN: s.refreshToken } })
    .then((res) => { memory = toSession(res, s.email, s.refreshToken); save(memory); return memory.idToken; })
    .catch(() => { memory = null; save(null); window.dispatchEvent(new Event("auth-changed")); return null; })
    .finally(() => { refreshing = null; });
  return refreshing;
}
setTokenProvider(getIdToken);

export const authApi = {
  async signUp(email: string, password: string) {
    if (MOCK) return;
    await idp("SignUp", { Username: email, Password: password, UserAttributes: [{ Name: "email", Value: email }] });
  },
  async confirm(email: string, code: string) {
    if (MOCK) return;
    await idp("ConfirmSignUp", { Username: email, ConfirmationCode: code.trim() });
  },
  async resend(email: string) {
    if (MOCK) return;
    await idp("ResendConfirmationCode", { Username: email });
  },
  async signIn(email: string, password: string) {
    if (MOCK) {
      memory = { idToken: `mock:${email}`, refreshToken: "mock", expiresAt: Date.now() + 36e5, email };
    } else {
      memory = toSession(await idp<AuthResult>("InitiateAuth", { AuthFlow: "USER_PASSWORD_AUTH", AuthParameters: { USERNAME: email, PASSWORD: password } }), email);
    }
    save(memory);
    window.dispatchEvent(new Event("auth-changed"));
  },
  async forgot(email: string) {
    if (MOCK) return;
    await idp("ForgotPassword", { Username: email });
  },
  async resetPassword(email: string, code: string, password: string) {
    if (MOCK) return;
    await idp("ConfirmForgotPassword", { Username: email, ConfirmationCode: code.trim(), Password: password });
  },
  signOut() {
    memory = null;
    save(null);
    window.dispatchEvent(new Event("auth-changed"));
  },
};

interface Ctx { user: User | null; ready: boolean }
const AuthCtx = createContext<Ctx>({ user: null, ready: true });
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const read = useCallback((): User | null => {
    if (!memory) return null;
    const c = decode(memory.idToken);
    const groups = c["cognito:groups"];
    return { email: String(c.email ?? memory.email), groups: Array.isArray(groups) ? (groups as string[]) : [] };
  }, []);
  const [user, setUser] = useState<User | null>(read);
  const [ready, setReady] = useState(!memory);

  useEffect(() => {
    const sync = () => setUser(read());
    window.addEventListener("auth-changed", sync);
    // Refresh once on start so an expired token is renewed (or cleared) before the first API call.
    if (memory) getIdToken().then(() => { sync(); setReady(true); });
    return () => window.removeEventListener("auth-changed", sync);
  }, [read]);

  const value = useMemo(() => ({ user, ready }), [user, ready]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}
