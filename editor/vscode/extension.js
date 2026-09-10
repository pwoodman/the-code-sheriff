const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

function activate(context) {
  const collection = vscode.languages.createDiagnosticCollection("the-code-sheriff");
  const refresh = () => loadDiagnostics(collection);
  context.subscriptions.push(
    vscode.commands.registerCommand("theCodeSheriff.refresh", refresh),
    collection,
  );
  refresh();
}

function loadDiagnostics(collection) {
  const folders = vscode.workspace.workspaceFolders || [];
  collection.clear();
  for (const folder of folders) {
    const report = path.join(folder.uri.fsPath, ".quality-reports", "diagnostics.json");
    if (!fs.existsSync(report)) {
      continue;
    }
    let payload;
    try {
      payload = JSON.parse(fs.readFileSync(report, "utf8"));
    } catch {
      continue;
    }
    const items = payload.diagnostics || payload.findings || [];
    const byFile = new Map();
    for (const item of items) {
      if (!item.path) continue;
      const file = path.join(folder.uri.fsPath, item.path);
      const list = byFile.get(file) || [];
      const range = new vscode.Range(
        Math.max(0, (item.line || 1) - 1),
        0,
        Math.max(0, (item.line || 1) - 1),
        200,
      );
      const severity =
        item.severity === "error"
          ? vscode.DiagnosticSeverity.Error
          : item.severity === "warning"
            ? vscode.DiagnosticSeverity.Warning
            : vscode.DiagnosticSeverity.Information;
      list.push(new vscode.Diagnostic(range, item.message || "finding", severity));
      byFile.set(file, list);
    }
    for (const [file, list] of byFile) {
      collection.set(vscode.Uri.file(file), list);
    }
  }
}

function deactivate() {
  return undefined;
}

module.exports = { activate, deactivate };
