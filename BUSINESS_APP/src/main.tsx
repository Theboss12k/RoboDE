import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Welcome from "../../SERVER_CLIENT/client/src/ui/Welcome";
import "./styles.css";
import "../../SERVER_CLIENT/client/src/ui/theme.css";
import {installBrandIcon} from "../../SERVER_CLIENT/client/src/branding/RobotLogo";
installBrandIcon();
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Welcome business><App /></Welcome>
  </React.StrictMode>,
);
