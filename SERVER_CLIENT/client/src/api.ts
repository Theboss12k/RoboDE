export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (response.status===401){window.location.assign("/login");throw new Error("Sign in to the shared workspace again.");}
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail ?? `Request failed (${response.status})`),
      Array.isArray(data.errors) ? data.errors : [],
    );
  }
  return response.json();
}
/** A failed request; `errors` lists every problem by field when the server checked a whole form. */
export class ApiError extends Error {
  constructor(message: string, readonly errors: { field: string; message: string }[] = []) { super(message); }
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export function download(
  filename: string,
  data: string,
  type = "application/json",
) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
