import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import Welcome from "./ui/Welcome";
import "./styles.css";
import "./ui/theme.css";
import "./ui/workspace.css";
import {installBrandIcon} from "./branding/RobotLogo";
installBrandIcon();
document.documentElement.classList.toggle(
  "desktop-mac",
  /Mac/.test(navigator.platform) && /Electron/.test(navigator.userAgent),
);
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Welcome><App /></Welcome>
  </React.StrictMode>,
);
