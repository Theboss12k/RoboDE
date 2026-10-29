"""Local filesystem projects and immutable artifacts, indexed by SQLite."""
import hashlib
import json
import re
import sqlite3
import uuid
import shutil
from pathlib import Path
import yaml
from shared.models.domain import Plan, PlanDefinition, TaskDefinition, Run, WorldObject, Log, Lifecycle, now
from services.validation.registry import ROOT, MODEL_ROOT, component, load_instance, load_model, read_yaml


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", value):
        raise ValueError("Invalid resource ID")
    return value


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False))
    temp.replace(path)


class Storage:
    def __init__(self, root: Path | None = None):
        import os
        use_bundled_examples = root is None and not os.getenv('ROBOT_IDE_DATA_DIR')
        root = Path(root or os.getenv('ROBOT_IDE_DATA_DIR') or ROOT).expanduser().resolve()
        self.root = root
        self.projects = root / "projects"
        self.runtime = root / "robot_system/runtime"
        # A clean source checkout gets examples once; saved projects stay private
        # and are never overwritten. Explicit/installed data roots seed separately.
        if use_bundled_examples and not self.projects.exists():
            shutil.copytree(ROOT / "examples/projects", self.projects)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.db = self.runtime / "catalog.sqlite3"
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, project_id TEXT, status TEXT, started_at TEXT, artifact TEXT)")

    def connection(self):
        return sqlite3.connect(self.db)

    def project_folder(self, project_id):
        return self.projects / safe_id(project_id)

    def model_folder(self, model_id):
        imported = self.runtime/'imported_models'/safe_id(model_id)
        return imported if imported.exists() else MODEL_ROOT/safe_id(model_id)

    def models(self):
        from services.planning.kinematics import supports_model
        folders = list(MODEL_ROOT.glob('*/robot.yaml')) + list((self.runtime/'imported_models').glob('*/robot.yaml'))
        result = []
        # Runtime copies override bundled definitions without duplicate library entries.
        unique={path.parent.name:path for path in folders}
        for _,path in sorted(unique.items()):
            model = load_model(path.parent)
            instance = load_instance(path.parent/'instances/instance.yaml',model)
            result.append({**model,'planning_supported':supports_model(model),'initial_configuration':instance['initial_configuration'],
                'imported':path.is_relative_to(self.runtime)})
        return result

    def load_project(self, project_id):
        folder = self.project_folder(project_id)
        project = read_yaml(folder / "project.yaml")
        instances, models = [], []
        for path in project["robots"]:
            instance_path = component(folder, path)
            raw = read_yaml(instance_path)
            model_id = safe_id(raw["robot_model"]["id"])
            model = load_model(self.model_folder(model_id))
            from services.planning.kinematics import supports_model
            model["planning_supported"] = supports_model(model)
            instance = load_instance(instance_path, model)
            instances.append(instance)
            models.append(model)
        world = read_yaml(component(folder, project["environment"]))
        objects = [WorldObject.model_validate(o) for o in world["objects"]]
        if len({o.id for o in objects}) != len(objects):
            raise ValueError("World contains duplicate object IDs")
        if any(getattr(o.size, axis) <= 0 for o in objects for axis in ("x", "y", "z")):
            raise ValueError("Object dimensions must be positive")
        from services.api.assets import validate_asset_refs
        validate_asset_refs(self, project_id, objects)
        return project, instances, models, objects

    def list_projects(self):
        return [read_yaml(p) for p in sorted(self.projects.glob("*/project.yaml"))]

    def create_project(self, name: str, source="apple_transfer"):
        # New project references the BOT registry, with its own instance and world.
        import shutil
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:45] or "project"
        slug = f"{slug}_{uuid.uuid4().hex[:6]}"
        source_dir = self.project_folder(source)
        project = read_yaml(source_dir / "project.yaml")
        folder = self.project_folder(slug)
        folder.mkdir()
        for relative in [*project["robots"], project["environment"]]:
            original = component(source_dir, relative)
            target = folder / original.relative_to(source_dir.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        # Imported meshes are project-owned and must survive cloning the scene.
        world = read_yaml(component(source_dir, project["environment"]))
        for asset_id in {o["mesh"]["asset_id"] for o in world["objects"] if o.get("mesh")}:
            from services.api.assets import asset_folder, asset_record
            asset_record(self, source, asset_id)
            shutil.copytree(asset_folder(self, source, asset_id), asset_folder(self, slug, asset_id))
        project.update(id=slug, name=name)
        (folder / "project.yaml").write_text(yaml.safe_dump(project, sort_keys=False))
        return project

    def save_plan(self, plan: Plan, snapshot: dict):
        # Legacy compilers also produce a first-class definition, without changing
        # their historical action IDs or the revision referenced by existing runs.
        if not plan.definition_id:
            definition = self.definition_from_revision(plan)
            self.save_definition(definition)
            plan.definition_id = definition.id
            plan.definition_version = definition.version
        folder = self.project_folder(plan.project_id) / "plans" / safe_id(plan.definition_id) / "revisions" / safe_id(plan.id)
        if (folder / "plan.json").exists():
            raise ValueError("Compiled revisions are immutable; compile a new revision")
        atomic_json(folder / "plan.json", plan.model_dump(mode="json"))
        atomic_json(folder / "snapshot.json", snapshot)
        (folder / "generated.py").write_text(plan.code)
        definition = self.get_definition(plan.project_id, plan.definition_id)
        definition.latest_revision_id = plan.id
        self.save_definition(definition)

    def get_plan(self, project_id, plan_id):
        self.migrate_plans(project_id)
        paths = list((self.project_folder(project_id) / "plans").glob(f"*/revisions/{safe_id(plan_id)}/plan.json"))
        if len(paths) != 1:
            raise FileNotFoundError("Revision not found")
        path = paths[0]
        plan = Plan.model_validate_json(path.read_text())
        if not plan.definition_id:
            plan.definition_id = path.parents[2].name
            plan.definition_version = 1
        return plan

    def list_plans(self, project_id):
        self.migrate_plans(project_id)
        paths = sorted((self.project_folder(project_id) / "plans").glob("*/revisions/*/plan.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [Plan.model_validate_json(p.read_text()) for p in paths[:30]]

    def definition_from_revision(self, plan):
        resources = {step.id: child.task.object_id for child in plan.workflow_tasks for step in plan.task.steps if step.id.startswith(child.id + ":")}
        destinations = {step.id: child.task.target_id for child in plan.workflow_tasks for step in plan.task.steps if step.id.startswith(child.id + ":")}
        tasks = [TaskDefinition(id=s.id, name=s.label, operation=s.operation,
                    robot_id=s.robot_id or plan.task.robot_id, dependencies=s.dependencies,
                    target=s.target, object_id=s.object_id or resources.get(s.id) or plan.task.object_id,
                    target_id=destinations.get(s.id) or plan.task.target_id)
                 for s in plan.task.steps]
        return PlanDefinition(id=plan.id, project_id=plan.project_id,
                              name=plan.task.description[:120], goal=plan.task.description,
                              tasks=tasks, latest_revision_id=plan.id, created_at=plan.created_at)

    def migrate_plans(self, project_id):
        """Copy before migration; legacy files and results are never rewritten."""
        project = self.project_folder(project_id)
        for source in (project / "tasks").glob("*/plan.json"):
            plan = Plan.model_validate_json(source.read_text())
            target = project / "plans" / safe_id(plan.id)
            if (target / "definition.json").exists():
                continue
            backup = project / "migration_backups/v1/tasks" / plan.id
            if not backup.exists():
                shutil.copytree(source.parent, backup)
            revision = target / "revisions" / plan.id
            revision.mkdir(parents=True, exist_ok=True)
            for item in source.parent.iterdir():
                if item.is_file():
                    shutil.copy2(item, revision / item.name)
            # Original compiled artifact bytes remain unchanged for historical runs.
            self.save_definition(self.definition_from_revision(plan))

    def save_definition(self, definition: PlanDefinition):
        atomic_json(self.project_folder(definition.project_id) / "plans" / safe_id(definition.id) / "definition.json",
                    definition.model_dump(mode="json"))

    def get_definition(self, project_id, definition_id):
        self.migrate_plans(project_id)
        return PlanDefinition.model_validate_json((self.project_folder(project_id) / "plans" / safe_id(definition_id) / "definition.json").read_text())

    def list_definitions(self, project_id):
        self.migrate_plans(project_id)
        return [PlanDefinition.model_validate_json(p.read_text()) for p in sorted(
            (self.project_folder(project_id) / "plans").glob("*/definition.json"), key=lambda p:p.stat().st_mtime, reverse=True)]

    def delete_definition(self, project_id, definition_id):
        definition = self.get_definition(project_id, definition_id)
        source = self.project_folder(project_id) / "plans" / safe_id(definition.id)
        # Archive retains immutable revision lookup for run history.
        atomic_json(source / "archived.json", {"archived_at": now()})

    def definition_archived(self, project_id, definition_id):
        return (self.project_folder(project_id) / "plans" / safe_id(definition_id) / "archived.json").exists()

    def save_run(self, run: Run):
        artifact = self.project_folder(run.project_id) / "results" / f"{safe_id(run.id)}.json"
        atomic_json(artifact, run.model_dump(mode="json"))
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?)",
                       (run.id, run.project_id, run.status.value, run.started_at, str(artifact.relative_to(self.root))))

    def get_run(self, run_id):
        with self.connection() as db:
            row = db.execute("SELECT artifact FROM runs WHERE id = ?", (safe_id(run_id),)).fetchone()
        if not row:
            raise FileNotFoundError("Run not found")
        return Run.model_validate_json((self.root / row[0]).read_text())

    def list_runs(self, project_id):
        with self.connection() as db:
            rows = list(db.execute("SELECT id, status, started_at FROM runs WHERE project_id = ? ORDER BY started_at DESC LIMIT 30", (project_id,)))
        result=[]
        for run_id,status,started_at in rows:
            run=self.get_run(run_id)
            result.append({"id":run_id,"status":status,"started_at":started_at,"plan_id":run.plan_id,
                           "definition_id":run.definition_id or run.plan_id,"revision_id":run.revision_id or run.plan_id})
        return result

    def recover_interrupted_runs(self):
        terminal = {"SIMULATION_PASSED", "FAILED", "TIMED_OUT", "CANCELLED", "COMPLETED"}
        with self.connection() as db:
            rows = db.execute("SELECT id, status FROM runs").fetchall()
        for run_id, status in rows:
            if status in terminal:
                continue
            run = self.get_run(run_id)
            run.status = Lifecycle.FAILED
            run.finished_at = now()
            run.stopped_verified = False
            run.logs.append(Log(level="error", message="Runtime restarted before this run finished. Completion and stop were not verified; reset the preview before retrying."))
            run.evidence.update({"interrupted": True, "postcondition_passed": False,
                                 "hardware_authorized": False, "stopped_verified": False})
            self.save_run(run)


def fingerprint(snapshot: dict):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()
