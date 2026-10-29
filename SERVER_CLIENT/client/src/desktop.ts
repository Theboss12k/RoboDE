export type IsaacFileKind = "launcher" | "catalog" | "manifest";
declare global {
  interface Window {
    robotIdeDesktop?: {
      platform: string;
      chooseIsaacFile: (kind: IsaacFileKind) => Promise<string | null>;
      workspaceAccessCode: () => Promise<{access_code: string | null}>;
    };
  }
}
export const desktop = window.robotIdeDesktop;
