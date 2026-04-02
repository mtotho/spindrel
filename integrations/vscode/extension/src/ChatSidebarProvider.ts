import * as vscode from "vscode";
import {
  readConfig,
  watchConfig,
  cancelRequest,
  streamChat,
  ChatConfig,
  SSEEvent,
} from "./api";
import { getWebviewContent } from "./webview";

export class ChatSidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "spindrel-chat.sidebar";

  private _view?: vscode.WebviewView;
  private _config: ChatConfig | null = null;
  private _clientId: string;
  private _abortController: AbortController | null = null;
  private _configWatcher: ReturnType<typeof watchConfig> = null;
  private _lastActiveEditor: vscode.TextEditor | undefined;

  constructor(private readonly _extensionUri: vscode.Uri, private readonly _context: vscode.ExtensionContext) {
    this._clientId = `vscode:${vscode.env.machineId}`;

    // Track last active text editor (goes undefined when webview gets focus)
    this._lastActiveEditor = vscode.window.activeTextEditor;
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor) {
        this._lastActiveEditor = editor;
      }
    });
  }

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    webviewView.webview.html = getWebviewContent(
      webviewView.webview,
      this._extensionUri
    );

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case "webviewReady":
          await this._initialize();
          break;
        case "sendMessage":
          await this._sendMessage(msg.text);
          break;
        case "attachContext":
          this._attachContext();
          break;
        case "cancel":
          this._cancel();
          break;
      }
    });

    // Clean up config watcher on dispose
    webviewView.onDidDispose(() => {
      if (this._configWatcher) {
        this._configWatcher.close();
        this._configWatcher = null;
      }
    });
  }

  private async _initialize(): Promise<void> {
    this._config = readConfig();

    // Watch for config changes (token refresh, channel rebind)
    this._configWatcher = watchConfig((newConfig) => {
      const channelChanged = newConfig?.channelId !== this._config?.channelId;
      this._config = newConfig;
      if (newConfig) {
        this._postMessage({
          type: "ready",
          channelId: newConfig.channelId || null,
        });
        if (channelChanged) {
          // Reset the webview for the new channel
          this._resetWebview();
        }
      }
    });

    if (this._config) {
      if (this._config.channelId) {
        this._postMessage({
          type: "ready",
          channelId: this._config.channelId,
        });
      } else {
        this._postMessage({ type: "noChannel" });
      }
    } else {
      this._postMessage({ type: "noConfig" });
    }
  }

  private _getBotId(): string {
    // Config file (from channel's actual bot) > VS Code setting > default
    return (
      this._config?.botId ||
      vscode.workspace
        .getConfiguration("spindrel")
        .get<string>("botId") ||
      "default"
    );
  }

  private _getChannelId(): string | null {
    return this._config?.channelId || null;
  }

  private async _sendMessage(text: string): Promise<void> {
    if (!this._config) {
      this._postMessage({
        type: "error",
        text: "No server configuration. Please open this editor through the workspace UI.",
      });
      return;
    }

    const channelId = this._getChannelId();
    if (!channelId) {
      this._postMessage({
        type: "error",
        text: "No channel bound. Please open this editor from a channel workspace tab.",
      });
      return;
    }

    try {
      this._postMessage({ type: "streamStart" });

      this._abortController = streamChat(
        this._config,
        {
          message: text,
          channelId,
          botId: this._getBotId(),
          clientId: this._clientId,
        },
        (event: SSEEvent) => this._handleSSEEvent(event),
        () => this._postMessage({ type: "streamEnd" }),
        (error: Error) => {
          this._postMessage({ type: "error", text: error.message });
          this._postMessage({ type: "streamEnd" });
        }
      );
    } catch (err: any) {
      this._postMessage({
        type: "error",
        text: err.message || "Failed to send message",
      });
    }
  }

  private _handleSSEEvent(event: SSEEvent): void {
    const { event: eventType, data } = event;

    switch (eventType) {
      case "assistant_text":
        if (data.delta) {
          this._postMessage({ type: "textDelta", text: data.delta });
        }
        break;

      case "response":
        // Final response text — if we missed deltas, show full text
        if (data.text && !data.delta) {
          this._postMessage({ type: "textDelta", text: data.text });
        }
        break;

      case "tool_start":
        this._postMessage({
          type: "toolStart",
          name: data.name || data.tool_name || "tool",
        });
        break;

      case "tool_result":
        this._postMessage({
          type: "toolResult",
          name: data.name || data.tool_name || "tool",
          result: data.result || data.output || null,
        });
        break;

      case "thinking_content":
        if (data.text || data.delta) {
          this._postMessage({
            type: "thinking",
            text: data.text || data.delta,
          });
        }
        break;

      case "error":
        this._postMessage({
          type: "error",
          text: data.message || data.error || "Unknown error",
        });
        break;
    }
  }

  private _attachContext(): void {
    const editor = this._lastActiveEditor || vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showInformationMessage("No active editor to attach context from.");
      return;
    }

    const doc = editor.document;
    const selection = editor.selection;
    const relativePath =
      vscode.workspace.asRelativePath(doc.uri) || doc.fileName;

    const context: any = { path: relativePath };
    if (!selection.isEmpty) {
      context.selection = doc.getText(selection);
    }

    this._postMessage({ type: "context", context });
  }

  private _cancel(): void {
    if (this._abortController) {
      this._abortController.abort();
      this._abortController = null;
    }
    if (this._config) {
      const channelId = this._getChannelId();
      if (channelId) {
        cancelRequest(this._config, this._clientId, this._getBotId()).catch(
          () => {}
        );
      }
    }
  }

  /** Reset the webview (e.g. when channel changes). */
  public resetWebview(): void {
    this._resetWebview();
  }

  private _resetWebview(): void {
    if (this._view) {
      this._view.webview.html = getWebviewContent(
        this._view.webview,
        this._extensionUri
      );
    }
  }

  private _postMessage(msg: any): void {
    this._view?.webview.postMessage(msg);
  }
}
