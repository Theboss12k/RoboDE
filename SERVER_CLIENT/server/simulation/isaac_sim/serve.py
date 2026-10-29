"""Run with Isaac Sim's Python on a supported GPU host, from SERVER_CLIENT/server."""
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--manifest')
    source.add_argument('--asset-catalog',help='Approved USD models; load project robots on connect')
    source.add_argument('--project-scene',action='store_true',help='Automatically build project scenes; demo robot assets require no catalog')
    parser.add_argument('--gui',action='store_true',help='Open Isaac UI in the VM remote desktop')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=9100)
    args = parser.parse_args()
    token = os.getenv('ISAAC_WORKER_TOKEN','')
    if len(token) < 16:
        parser.error('Set ISAAC_WORKER_TOKEN to at least 16 characters')
    import threading
    from isaacsim import SimulationApp
    configuration={'headless':not args.gui}
    if os.getenv('ROBOT_IDE_KIT_ROOT'):
        from pathlib import Path
        kit_root=Path(os.environ['ROBOT_IDE_KIT_ROOT']).expanduser().resolve()
        kit_root.mkdir(parents=True,exist_ok=True)
        configuration['extra_args']=['--portable-root',str(kit_root)]
    simulation = SimulationApp(configuration)
    try:
        # Isaac imports must follow SimulationApp initialization, on this main thread.
        import uvicorn
        from simulation.isaac_sim.native import NativeCell
        from simulation.isaac_sim.worker import create_worker
        if args.asset_catalog or args.project_scene:
            from simulation.isaac_sim.managed import ManagedNativeCell
            backend=ManagedNativeCell(args.asset_catalog)
        else:backend = NativeCell(args.manifest)
        from simulation.isaac_sim.recording import RecordingBackend
        backend=RecordingBackend(backend)
        from simulation.isaac_sim.bridge import MainThreadBridge
        bridge=MainThreadBridge(backend)
        server=uvicorn.Server(uvicorn.Config(create_worker(bridge,token),host=args.host,port=args.port,workers=1))
        thread=threading.Thread(target=server.run,name='isaac-http',daemon=True)
        thread.start()
        # HTTP and its asyncio loop run separately. World.step/reset and all USD/
        # tensor access stay on this main thread, outside the HTTP event loop.
        while thread.is_alive() and simulation.is_running():
            try:
                bridge.pump(timeout=.01)
                backend.recorder.tick()
                if args.gui:
                    native=getattr(backend.backend,'cell',backend.backend)
                    if native is not None:native.world.render()
                    else:simulation.update()
            except KeyboardInterrupt:
                server.should_exit=True
        server.should_exit=True
        try:backend.stop()
        finally:backend.recorder.close()
    finally:
        simulation.close()


if __name__ == '__main__':
    main()
