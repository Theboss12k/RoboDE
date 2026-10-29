import logoUrl from '../../../server/web/static/robot-logo.svg';
import './robot-logo.css';

export { logoUrl };
/** The user's robot/code mark, shared by Electron, hosted IDE and Business App. */
export default function RobotLogo() {
  return <img className="robot-brand-logo" src={logoUrl} alt="" aria-hidden="true" draggable={false} />;
}

export function installBrandIcon() {
  const icon = document.createElement('link');
  icon.rel = 'icon'; icon.type = 'image/svg+xml'; icon.href = logoUrl;
  document.head.append(icon);
}
