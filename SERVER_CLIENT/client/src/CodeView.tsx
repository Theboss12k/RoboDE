import Editor, { loader } from "@monaco-editor/react";
// The small API entry point does not eagerly register these editor services.
// Load them before language registration can initialize the standalone service
// collection (including when an Expert editor is opened after Simple mode).
import "monaco-editor/editor/contrib/codelens/browser/codeLensCache.js";
import "monaco-editor/editor/contrib/inlayHints/browser/inlayHintsController.js";
import "monaco-editor/editor/common/services/treeViewsDndService.js";
import "monaco-editor/editor/contrib/suggest/browser/suggestMemory.js";
import "monaco-editor/platform/actionWidget/browser/actionWidget.js";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/languages/definitions/python/register.js";
import "monaco-editor/languages/features/json/register.js";
import JSONWorker from "monaco-editor/languages/features/json/json.worker.js?worker";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import { Download, FileCode2, LockKeyhole } from "lucide-react";
import { download } from "./api";
import type { Plan } from "./types";
(globalThis as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorker: (_:string,label:string) => label==="json"?new JSONWorker():new EditorWorker(),
};
loader.config({ monaco });
export function AdapterCodeEditor({ value, disabled, onChange, language="python", label="LLM adapter code" }: {
  value: string; disabled: boolean; onChange: (value: string) => void; language?:"python"|"json"; label?:string;
}) {
  return <Editor height="330px" language={language} theme="vs-dark" value={value}
    onChange={(text) => onChange(text ?? "")}
    options={{ ariaLabel: label, readOnly: disabled,
      minimap: { enabled: false }, fontSize: 12, lineHeight: 20,
      automaticLayout: true, scrollBeyondLastLine: false, wordWrap: "on",
      padding: { top: 12 }, tabSize: 4 }} />;
}
export default function CodeView({ plan }: { plan: Plan | null }) {
  if (!plan)
    return (
      <div className="empty-state">
        <FileCode2 size={28} />
        <p>No generated implementation yet.</p>
        <span>
          Generate a plan to inspect its task manifest and runtime references.
        </span>
      </div>
    );
  return (
    <div className="code-view">
      <div className="code-bar">
        <span>
          <FileCode2 size={13} /> plans/{plan.definition_id ?? plan.id}
          /revisions/{plan.id}/{plan.motion_manifest?.schema_version===2?"commands.json":"generated.py"}
        </span>
        <button
          onClick={() => download(plan.motion_manifest?.schema_version===2?"commands.json":"generated.py", plan.code, plan.motion_manifest?.schema_version===2?"application/json":"text/x-python")}
        >
          <Download size={13} /> Export
        </button>
      </div>
      <Editor
        height="100%"
        language={plan.motion_manifest?.schema_version===2?"json":"python"}
        value={plan.code}
        theme="vs-dark"
        beforeMount={(m) =>
          m.editor.defineTheme("robot-dark", {
            base: "vs-dark",
            inherit: true,
            rules: [],
            colors: {
              "editor.background": "#0c111b",
              "editorLineNumber.foreground": "#51617a",
            },
          })
        }
        onMount={(_, m) => m.editor.setTheme("robot-dark")}
        options={{
          readOnly: true,
          minimap: { enabled: false },
          fontSize: 12,
          lineHeight: 21,
          padding: { top: 16 },
          scrollBeyondLastLine: false,
          wordWrap: "on",
          renderLineHighlight: "none",
          fontFamily: '"SFMono-Regular", Consolas, monospace',
          automaticLayout: true,
        }}
      />
      <div className="code-foot">
        <LockKeyhole size={12} /> Runtime executes registered, validated plans.
        This source is an inspectable export.
      </div>
    </div>
  );
}
