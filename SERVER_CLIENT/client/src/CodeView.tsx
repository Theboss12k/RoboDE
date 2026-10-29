import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/languages/definitions/python/register.js";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import { Download, FileCode2, LockKeyhole } from "lucide-react";
import { download } from "./api";
import type { Plan } from "./types";
(globalThis as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
};
loader.config({ monaco });
export function AdapterCodeEditor({ value, disabled, onChange }: {
  value: string; disabled: boolean; onChange: (value: string) => void;
}) {
  return <Editor height="330px" language="python" theme="vs-dark" value={value}
    onChange={(text) => onChange(text ?? "")}
    options={{ ariaLabel: "LLM adapter code", readOnly: disabled,
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
          /revisions/{plan.id}/generated.py
        </span>
        <button
          onClick={() => download("generated.py", plan.code, "text/x-python")}
        >
          <Download size={13} /> Export
        </button>
      </div>
      <Editor
        height="100%"
        defaultLanguage="python"
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
