import * as vscode from "vscode";
import { ChatSidebarProvider } from "./ChatSidebarProvider";

let sidebarProvider: ChatSidebarProvider;

export function activate(context: vscode.ExtensionContext): void {
  sidebarProvider = new ChatSidebarProvider(context.extensionUri, context);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      ChatSidebarProvider.viewType,
      sidebarProvider
    )
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("spindrel-chat.attachContext", () => {
      // Open the sidebar then let the webview handle it
      vscode.commands.executeCommand(
        "workbench.view.extension.spindrel-chat"
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("spindrel-chat.cancel", () => {
      // Cancel is handled via webview postMessage
    })
  );
}

export function deactivate(): void {
  // Cleanup handled by disposables
}
