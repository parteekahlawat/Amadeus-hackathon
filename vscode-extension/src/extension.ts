import * as vscode from "vscode";
import * as https from "https";
import * as path from "path";
import * as fs from "fs";
import { execSync } from "child_process";

const OUTPUT_CHANNEL = vscode.window.createOutputChannel("KubeQA");
let autoGenEnabled = false;
let statusBarItem: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext) {
  OUTPUT_CHANNEL.appendLine("KubeQA Autonomous Test Generator activated");

  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBarItem.text = "$(beaker) KubeQA";
  statusBarItem.tooltip = "KubeQA — Click to generate tests";
  statusBarItem.command = "kubeqa.generateTests";
  statusBarItem.show();

  context.subscriptions.push(
    vscode.commands.registerCommand("kubeqa.generateTests", () =>
      generateTestsForFile()
    ),
    vscode.commands.registerCommand("kubeqa.generateTestsForFunction", () =>
      generateTestsForSelection()
    ),
    vscode.commands.registerCommand("kubeqa.generateTestsForDiff", () =>
      generateTestsForDiff()
    ),
    vscode.commands.registerCommand("kubeqa.runSecurityScan", () =>
      runSecurityScan()
    ),
    vscode.commands.registerCommand("kubeqa.toggleAutoGen", () =>
      toggleAutoGen()
    ),
    statusBarItem
  );

  vscode.workspace.onDidSaveTextDocument((doc) => {
    const config = vscode.workspace.getConfiguration("kubeqa");
    if (config.get<boolean>("autoGenerateOnSave") || autoGenEnabled) {
      generateTestsForDocument(doc);
    }
  });
}

function getConfig() {
  const config = vscode.workspace.getConfiguration("kubeqa");
  return {
    apiKey: config.get<string>("groqApiKey") || process.env.GROQ_API_KEY || "",
    model: config.get<string>("groqModel") || "llama-3.1-70b-versatile",
    framework: config.get<string>("testFramework") || "pytest",
    outputDir: config.get<string>("outputDirectory") || "tests",
  };
}

async function callGroq(
  systemPrompt: string,
  userPrompt: string
): Promise<any> {
  const config = getConfig();
  if (!config.apiKey) {
    vscode.window.showErrorMessage(
      "KubeQA: Set your Groq API key in settings (kubeqa.groqApiKey)"
    );
    return null;
  }

  const body = JSON.stringify({
    model: config.model,
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ],
    temperature: 0.1,
    max_tokens: 4096,
    response_format: { type: "json_object" },
  });

  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: "api.groq.com",
        path: "/openai/v1/chat/completions",
        method: "POST",
        headers: {
          Authorization: `Bearer ${config.apiKey}`,
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          try {
            const json = JSON.parse(data);
            const content = json.choices?.[0]?.message?.content;
            resolve(content ? JSON.parse(content) : null);
          } catch (e) {
            reject(e);
          }
        });
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

const TEST_GEN_SYSTEM = `You are an expert test engineer. Generate comprehensive unit tests for the given code.

You MUST respond with JSON:
{
  "test_file_name": "test_module_name.py",
  "test_code": "full test code",
  "test_count": 8,
  "coverage_areas": ["function_a", "function_b"],
  "edge_cases_tested": ["empty input", "null values", "boundary conditions"]
}

Guidelines:
- Use the specified test framework
- Test happy paths AND edge cases
- Include setup/teardown where needed
- Mock external dependencies
- Test error handling paths
- Use descriptive test names that explain what is being tested
- Include type-specific edge cases (empty strings, 0, negative numbers, None/null, max values)
- For async code, use appropriate async test patterns`;

const SECURITY_SCAN_SYSTEM = `You are a security engineer performing OWASP-based code review.

Analyze the code for vulnerabilities against:
- OWASP Web Top 10 (A01-A10): access control, crypto, injection, design, misconfig, components, auth, integrity, logging, SSRF
- OWASP LLM Top 10 (LLM01-LLM10): prompt injection, output handling, data poisoning, DoS, supply chain, info disclosure, plugins, agency, overreliance, theft

You MUST respond with JSON:
{
  "findings": [
    {
      "owasp_ref": "A03",
      "severity": "HIGH",
      "title": "SQL Injection",
      "line": 42,
      "code": "vulnerable code",
      "explanation": "why this is vulnerable",
      "fix": "how to fix it with code example"
    }
  ],
  "risk_score": 6.5,
  "summary": "one-line summary"
}`;

async function generateTestsForFile() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("No active file");
    return;
  }

  const doc = editor.document;
  await generateTestsForDocument(doc);
}

async function generateTestsForDocument(doc: vscode.TextDocument) {
  const config = getConfig();
  const code = doc.getText();
  const fileName = path.basename(doc.fileName);
  const lang = doc.languageId;

  statusBarItem.text = "$(loading~spin) KubeQA generating...";

  const prompt = `## File: ${fileName}
## Language: ${lang}
## Test Framework: ${config.framework}

\`\`\`${lang}
${code.substring(0, 15000)}
\`\`\`

Generate comprehensive unit tests for this code. Cover all public functions, edge cases, and error paths.`;

  try {
    const result = await callGroq(TEST_GEN_SYSTEM, prompt);
    if (!result) return;

    const workspaceRoot =
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";
    const testDir = path.join(workspaceRoot, config.outputDir);

    if (!fs.existsSync(testDir)) {
      fs.mkdirSync(testDir, { recursive: true });
    }

    const testFileName =
      result.test_file_name || `test_${fileName.replace(/\.[^.]+$/, "")}.py`;
    const testPath = path.join(testDir, testFileName);

    fs.writeFileSync(testPath, result.test_code);

    const testDoc = await vscode.workspace.openTextDocument(testPath);
    await vscode.window.showTextDocument(testDoc, vscode.ViewColumn.Beside);

    vscode.window.showInformationMessage(
      `KubeQA: Generated ${result.test_count} tests → ${testFileName}`
    );

    OUTPUT_CHANNEL.appendLine(
      `Generated ${result.test_count} tests for ${fileName}`
    );
    OUTPUT_CHANNEL.appendLine(
      `  Coverage: ${result.coverage_areas?.join(", ")}`
    );
    OUTPUT_CHANNEL.appendLine(
      `  Edge cases: ${result.edge_cases_tested?.join(", ")}`
    );
  } catch (e: any) {
    vscode.window.showErrorMessage(`KubeQA error: ${e.message}`);
  } finally {
    statusBarItem.text = "$(beaker) KubeQA";
  }
}

async function generateTestsForSelection() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.selection.isEmpty) {
    vscode.window.showWarningMessage("Select a function or code block first");
    return;
  }

  const config = getConfig();
  const selection = editor.document.getText(editor.selection);
  const fileName = path.basename(editor.document.fileName);
  const lang = editor.document.languageId;

  statusBarItem.text = "$(loading~spin) KubeQA generating...";

  const prompt = `## File: ${fileName}
## Language: ${lang}
## Test Framework: ${config.framework}
## Selected Code (function/block to test):

\`\`\`${lang}
${selection.substring(0, 10000)}
\`\`\`

Generate focused unit tests for this specific function/code block. Test every branch, edge case, and error path.`;

  try {
    const result = await callGroq(TEST_GEN_SYSTEM, prompt);
    if (!result) return;

    const workspaceRoot =
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";
    const testDir = path.join(workspaceRoot, config.outputDir);
    if (!fs.existsSync(testDir)) {
      fs.mkdirSync(testDir, { recursive: true });
    }

    const testFileName =
      result.test_file_name ||
      `test_${fileName.replace(/\.[^.]+$/, "")}_selection.py`;
    const testPath = path.join(testDir, testFileName);

    fs.writeFileSync(testPath, result.test_code);
    const testDoc = await vscode.workspace.openTextDocument(testPath);
    await vscode.window.showTextDocument(testDoc, vscode.ViewColumn.Beside);

    vscode.window.showInformationMessage(
      `KubeQA: Generated ${result.test_count} tests for selection`
    );
  } catch (e: any) {
    vscode.window.showErrorMessage(`KubeQA error: ${e.message}`);
  } finally {
    statusBarItem.text = "$(beaker) KubeQA";
  }
}

async function generateTestsForDiff() {
  const config = getConfig();
  const workspaceRoot =
    vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";

  let diff: string;
  try {
    diff = execSync("git diff HEAD", {
      cwd: workspaceRoot,
      encoding: "utf-8",
      timeout: 10000,
    });
  } catch {
    try {
      diff = execSync("git diff --cached", {
        cwd: workspaceRoot,
        encoding: "utf-8",
        timeout: 10000,
      });
    } catch {
      vscode.window.showErrorMessage(
        "KubeQA: Not a git repo or no changes found"
      );
      return;
    }
  }

  if (!diff.trim()) {
    vscode.window.showInformationMessage("No uncommitted changes to test");
    return;
  }

  statusBarItem.text = "$(loading~spin) KubeQA analyzing diff...";

  const prompt = `## Git Diff (uncommitted changes)
## Test Framework: ${config.framework}

\`\`\`diff
${diff.substring(0, 15000)}
\`\`\`

Generate tests that specifically cover the CHANGED code in this diff. Focus on:
1. New functions/methods added
2. Modified logic paths
3. Edge cases for the changes
4. Regression tests for modified behavior`;

  try {
    const result = await callGroq(TEST_GEN_SYSTEM, prompt);
    if (!result) return;

    const testDir = path.join(workspaceRoot, config.outputDir);
    if (!fs.existsSync(testDir)) {
      fs.mkdirSync(testDir, { recursive: true });
    }

    const testFileName = result.test_file_name || "test_diff_changes.py";
    const testPath = path.join(testDir, testFileName);

    fs.writeFileSync(testPath, result.test_code);
    const testDoc = await vscode.workspace.openTextDocument(testPath);
    await vscode.window.showTextDocument(testDoc, vscode.ViewColumn.Beside);

    vscode.window.showInformationMessage(
      `KubeQA: Generated ${result.test_count} tests for diff changes`
    );
  } catch (e: any) {
    vscode.window.showErrorMessage(`KubeQA error: ${e.message}`);
  } finally {
    statusBarItem.text = "$(beaker) KubeQA";
  }
}

async function runSecurityScan() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("No active file");
    return;
  }

  const code = editor.document.getText();
  const fileName = path.basename(editor.document.fileName);
  const lang = editor.document.languageId;

  statusBarItem.text = "$(shield) KubeQA scanning...";

  const prompt = `## File: ${fileName}
## Language: ${lang}

\`\`\`${lang}
${code.substring(0, 15000)}
\`\`\`

Perform OWASP security analysis on this code.`;

  try {
    const result = await callGroq(SECURITY_SCAN_SYSTEM, prompt);
    if (!result) return;

    const diagnostics: vscode.Diagnostic[] = [];
    const collection =
      vscode.languages.createDiagnosticCollection("kubeqa-security");

    for (const finding of result.findings || []) {
      const line = Math.max(0, (finding.line || 1) - 1);
      const range = new vscode.Range(line, 0, line, 1000);

      const severity =
        finding.severity === "CRITICAL" || finding.severity === "HIGH"
          ? vscode.DiagnosticSeverity.Error
          : finding.severity === "MEDIUM"
            ? vscode.DiagnosticSeverity.Warning
            : vscode.DiagnosticSeverity.Information;

      const diag = new vscode.Diagnostic(
        range,
        `[${finding.owasp_ref}] ${finding.title}: ${finding.explanation}\nFix: ${finding.fix}`,
        severity
      );
      diag.source = "KubeQA OWASP";
      diagnostics.push(diag);
    }

    collection.set(editor.document.uri, diagnostics);

    const findingCount = result.findings?.length || 0;
    const risk = result.risk_score || 0;
    vscode.window.showInformationMessage(
      `KubeQA Security: ${findingCount} findings, risk score ${risk}/10`
    );

    OUTPUT_CHANNEL.appendLine(`\nSecurity scan: ${fileName}`);
    OUTPUT_CHANNEL.appendLine(`Risk score: ${risk}/10`);
    OUTPUT_CHANNEL.appendLine(`Summary: ${result.summary}`);
    for (const f of result.findings || []) {
      OUTPUT_CHANNEL.appendLine(
        `  [${f.severity}] ${f.owasp_ref}: ${f.title} (line ${f.line})`
      );
    }
    OUTPUT_CHANNEL.show();
  } catch (e: any) {
    vscode.window.showErrorMessage(`KubeQA error: ${e.message}`);
  } finally {
    statusBarItem.text = "$(beaker) KubeQA";
  }
}

function toggleAutoGen() {
  autoGenEnabled = !autoGenEnabled;
  const state = autoGenEnabled ? "ON" : "OFF";
  statusBarItem.text = autoGenEnabled
    ? "$(beaker~spin) KubeQA AUTO"
    : "$(beaker) KubeQA";
  vscode.window.showInformationMessage(
    `KubeQA: Auto-generate on save is now ${state}`
  );
}

export function deactivate() {
  statusBarItem?.dispose();
}
