import NvidiaLogo from "./branding/NvidiaLogo";
export default function IsaacRobotGuide() {
  return (
    <details className="isaac-robot-guide">
      <summary>
        <span className="nvidia-tool-heading">
          <NvidiaLogo />
          How robot models are imported into Isaac Sim
        </span>
      </summary>
      <ol>
        <li>
          On the NVIDIA GPU host, import the manufacturer’s URDF and referenced
          meshes through Isaac Sim’s URDF importer, or load an existing robot
          USD asset.
        </li>
        <li>
          Configure its articulation root, fixed or mobile base, collision
          shapes, mass/inertia, joint limits and position drives. Verify joint
          names, axes, signs and gripper behavior in Isaac Sim, then save the
          robot USD with a default prim.
        </li>
        <li>
          Register the matching BOT model in RoboDE and add project
          instances. The BOT definition supplies limits and control metadata; it
          does not create the native robot geometry.
        </li>
        <li>
          Deploy the matching model files and instance configuration to the
          worker. Its approved asset catalog maps each model to a checksummed
          USD, an articulation root and every actuator’s DOF name. The managed
          worker loads one reference per project instance. A fixed cell manifest
          remains supported.
        </li>
        <li>
          Start the authenticated Isaac worker, then choose Environment → NVIDIA
          Isaac Sim. Use Isaac Sim setup to choose GCP or a local installation, save the worker connection and enable Load
          project robots on connect for a managed worker. Native controls and
          box object editing are available after connecting. Pose tasks require
          configured IK; direct joint tasks bypass it.
        </li>
      </ol>
      <p>
        The included cell builder creates educational demo-arm geometry. The
        built-in command test window exercises the adapter’s simulated
        transport; native GPU physics needs its own validation.
      </p>
      <a
        href="https://docs.isaacsim.omniverse.nvidia.com/6.2.0/importer_exporter/ext_isaacsim_asset_importer_urdf.html"
        target="_blank"
        rel="noreferrer"
      >
        NVIDIA URDF importer documentation ↗
      </a>
    </details>
  );
}
