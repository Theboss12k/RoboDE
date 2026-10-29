// A workspace preference only; registry review and connection checks remain authoritative.
const key = (project: string, robot: string) =>
  `robot-ide.adapter.${project}.${robot}`;
export const preferredAdapter = (project: string, robot: string) =>
  localStorage.getItem(key(project, robot));
export const rememberAdapter = (
  project: string,
  robot: string,
  adapter: string,
) => localStorage.setItem(key(project, robot), adapter);
