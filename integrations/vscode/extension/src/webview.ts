import * as vscode from "vscode";

export function getWebviewContent(
  webview: vscode.Webview,
  extensionUri: vscode.Uri
): string {
  // code-server webview iframes mangle nonces, so use 'unsafe-inline' for compatibility.
  // The webview is already sandboxed in an iframe — this is safe.
  const cspSource = webview.cspSource;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'unsafe-inline';">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    #messages {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
    }
    .message {
      margin-bottom: 12px;
      line-height: 1.5;
    }
    .message.user {
      background: var(--vscode-input-background);
      border-radius: 8px;
      padding: 8px 12px;
    }
    .message.assistant {
      padding: 4px 0;
    }
    .message.assistant pre {
      background: var(--vscode-textCodeBlock-background);
      border-radius: 4px;
      padding: 8px;
      overflow-x: auto;
      margin: 4px 0;
      font-family: var(--vscode-editor-font-family);
      font-size: var(--vscode-editor-font-size);
    }
    .message.assistant code {
      background: var(--vscode-textCodeBlock-background);
      padding: 1px 4px;
      border-radius: 3px;
      font-family: var(--vscode-editor-font-family);
      font-size: var(--vscode-editor-font-size);
    }
    .message.assistant pre code {
      background: none;
      padding: 0;
    }
    .tool-call {
      font-size: 0.85em;
      color: var(--vscode-descriptionForeground);
      border-left: 2px solid var(--vscode-activityBar-activeBorder);
      padding: 4px 8px;
      margin: 4px 0;
      cursor: pointer;
    }
    .tool-call .tool-result {
      display: none;
      margin-top: 4px;
      white-space: pre-wrap;
      font-family: var(--vscode-editor-font-family);
      font-size: var(--vscode-editor-font-size);
      max-height: 200px;
      overflow-y: auto;
    }
    .tool-call.expanded .tool-result {
      display: block;
    }
    .thinking {
      font-style: italic;
      color: var(--vscode-descriptionForeground);
      margin: 4px 0;
    }
    .error {
      color: var(--vscode-errorForeground);
      background: var(--vscode-inputValidation-errorBackground);
      border-radius: 4px;
      padding: 8px;
      margin: 4px 0;
    }
    .context-badge {
      display: inline-block;
      font-size: 0.8em;
      background: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      padding: 2px 6px;
      border-radius: 3px;
      margin: 2px 4px 2px 0;
    }
    #input-area {
      border-top: 1px solid var(--vscode-panel-border);
      padding: 8px;
    }
    #context-bar {
      display: none;
      padding: 4px 0;
      gap: 4px;
      flex-wrap: wrap;
    }
    #context-bar.has-context {
      display: flex;
    }
    .context-item {
      display: flex;
      align-items: center;
      gap: 4px;
      background: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 0.8em;
    }
    .context-item .remove {
      cursor: pointer;
      opacity: 0.7;
    }
    .context-item .remove:hover { opacity: 1; }
    #input-row {
      display: flex;
      gap: 4px;
      align-items: flex-end;
    }
    #message-input {
      flex: 1;
      resize: none;
      border: 1px solid var(--vscode-input-border);
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      padding: 6px 8px;
      border-radius: 4px;
      min-height: 36px;
      max-height: 150px;
      outline: none;
    }
    #message-input:focus {
      border-color: var(--vscode-focusBorder);
    }
    button {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      padding: 6px 12px;
      border-radius: 4px;
      cursor: pointer;
      font-size: var(--vscode-font-size);
    }
    button:hover {
      background: var(--vscode-button-hoverBackground);
    }
    button.secondary {
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
    }
    button.secondary:hover {
      background: var(--vscode-button-secondaryHoverBackground);
    }
    .status {
      text-align: center;
      padding: 16px;
      color: var(--vscode-descriptionForeground);
    }
    @keyframes pulse {
      0%, 100% { opacity: 0.4; }
      50% { opacity: 1; }
    }
    .streaming-indicator {
      display: inline-block;
      width: 6px;
      height: 14px;
      background: var(--vscode-activityBar-activeBorder);
      animation: pulse 1s infinite;
      vertical-align: text-bottom;
      margin-left: 2px;
    }
    .spinner::after {
      content: '';
      display: inline-block;
      width: 12px;
      height: 12px;
      border: 2px solid var(--vscode-descriptionForeground);
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      vertical-align: middle;
      margin-right: 6px;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  </style>
</head>
<body>
  <div id="messages">
    <div class="status" id="status">Connecting...</div>
  </div>
  <div id="input-area">
    <div id="context-bar"></div>
    <div id="input-row">
      <button class="secondary" id="attach-btn" title="Attach context">+</button>
      <textarea id="message-input" rows="1" placeholder="Send a message..."></textarea>
      <button id="send-btn">Send</button>
    </div>
  </div>

  <script>
    const vscode = acquireVsCodeApi();
    const messagesEl = document.getElementById('messages');
    const statusEl = document.getElementById('status');
    const inputEl = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const attachBtn = document.getElementById('attach-btn');
    const contextBar = document.getElementById('context-bar');

    let streaming = false;
    let currentAssistantEl = null;
    let currentText = '';
    let attachedContexts = [];

    // Auto-resize textarea
    inputEl.addEventListener('input', () => {
      inputEl.style.height = 'auto';
      inputEl.style.height = Math.min(inputEl.scrollHeight, 150) + 'px';
    });

    // Send on Enter (Shift+Enter for newline)
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    sendBtn.addEventListener('click', sendMessage);
    attachBtn.addEventListener('click', () => {
      vscode.postMessage({ type: 'attachContext' });
    });

    function sendMessage() {
      const text = inputEl.value.trim();
      if (!text || streaming) return;

      // Build message with context prefix
      let fullMessage = text;
      if (attachedContexts.length > 0) {
        const ctxParts = attachedContexts.map(c => {
          if (c.selection) {
            return '[Context: ' + c.path + ' (selection)]\\n' + c.selection;
          }
          return '[Context: ' + c.path + ']';
        });
        fullMessage = ctxParts.join('\\n') + '\\n\\n' + text;
      }

      addMessage('user', text, attachedContexts);
      inputEl.value = '';
      inputEl.style.height = 'auto';
      clearContexts();

      vscode.postMessage({ type: 'sendMessage', text: fullMessage });
    }

    function loadHistory(messages) {
      if (statusEl.parentElement) statusEl.remove();
      messages.forEach(m => {
        const div = document.createElement('div');
        div.className = 'message ' + (m.role === 'user' ? 'user' : 'assistant');
        if (m.role === 'user') {
          div.appendChild(document.createTextNode(m.content || ''));
        } else {
          div.innerHTML = renderMarkdown(m.content || '');
        }
        messagesEl.appendChild(div);
      });
      scrollToBottom();
    }

    function addMessage(role, text, contexts) {
      if (statusEl.parentElement) statusEl.remove();

      const div = document.createElement('div');
      div.className = 'message ' + role;

      if (role === 'user') {
        if (contexts && contexts.length) {
          contexts.forEach(c => {
            const badge = document.createElement('span');
            badge.className = 'context-badge';
            badge.textContent = c.path.split('/').pop();
            div.appendChild(badge);
          });
          div.appendChild(document.createElement('br'));
        }
        div.appendChild(document.createTextNode(text));
      } else {
        div.innerHTML = renderMarkdown(text);
      }

      messagesEl.appendChild(div);
      scrollToBottom();
      return div;
    }

    function startStreaming() {
      streaming = true;
      sendBtn.textContent = 'Stop';
      sendBtn.onclick = () => {
        vscode.postMessage({ type: 'cancel' });
      };
      currentText = '';
      currentAssistantEl = document.createElement('div');
      currentAssistantEl.className = 'message assistant';
      if (statusEl.parentElement) statusEl.remove();
      messagesEl.appendChild(currentAssistantEl);
    }

    function appendText(text) {
      currentText += text;
      if (currentAssistantEl) {
        currentAssistantEl.innerHTML = renderMarkdown(currentText) + '<span class="streaming-indicator"></span>';
        scrollToBottom();
      }
    }

    function addToolCall(name) {
      const div = document.createElement('div');
      div.className = 'tool-call';
      div.innerHTML = '<span class="spinner"></span>' + escapeHtml(name);
      div.dataset.toolName = name;
      if (currentAssistantEl) {
        currentAssistantEl.appendChild(div);
      } else {
        messagesEl.appendChild(div);
      }
      scrollToBottom();
      return div;
    }

    function resolveToolCall(name, result) {
      const tools = document.querySelectorAll('.tool-call');
      for (let i = tools.length - 1; i >= 0; i--) {
        if (tools[i].dataset.toolName === name) {
          const toolEl = tools[i];
          // Remove spinner
          const spinner = toolEl.querySelector('.spinner');
          if (spinner) spinner.remove();
          toolEl.innerHTML = '\\u2713 ' + escapeHtml(name);
          toolEl.dataset.toolName = name;

          if (result) {
            const resultEl = document.createElement('div');
            resultEl.className = 'tool-result';
            resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
            toolEl.appendChild(resultEl);
            toolEl.addEventListener('click', () => toolEl.classList.toggle('expanded'));
          }
          break;
        }
      }
    }

    function addThinking(text) {
      const div = document.createElement('div');
      div.className = 'thinking';
      div.textContent = text;
      if (currentAssistantEl) {
        currentAssistantEl.appendChild(div);
      }
    }

    function stopStreaming() {
      streaming = false;
      sendBtn.textContent = 'Send';
      sendBtn.onclick = sendMessage;
      // Remove streaming indicator
      if (currentAssistantEl) {
        const indicator = currentAssistantEl.querySelector('.streaming-indicator');
        if (indicator) indicator.remove();
        // Re-render without indicator
        if (currentText) {
          // Keep tool calls and thinking, update text content
          const toolCalls = currentAssistantEl.querySelectorAll('.tool-call, .thinking');
          currentAssistantEl.innerHTML = renderMarkdown(currentText);
          toolCalls.forEach(tc => currentAssistantEl.appendChild(tc));
        }
      }
      currentAssistantEl = null;
      currentText = '';
    }

    function addError(text) {
      const div = document.createElement('div');
      div.className = 'error';
      div.textContent = text;
      messagesEl.appendChild(div);
      scrollToBottom();
    }

    function addContext(ctx) {
      attachedContexts.push(ctx);
      renderContextBar();
    }

    function clearContexts() {
      attachedContexts = [];
      renderContextBar();
    }

    function renderContextBar() {
      contextBar.innerHTML = '';
      if (attachedContexts.length === 0) {
        contextBar.classList.remove('has-context');
        return;
      }
      contextBar.classList.add('has-context');
      attachedContexts.forEach((ctx, i) => {
        const item = document.createElement('span');
        item.className = 'context-item';
        const name = ctx.path.split('/').pop();
        item.innerHTML = escapeHtml(name) + (ctx.selection ? ' (sel)' : '') +
          ' <span class="remove" data-idx="' + i + '">\\u00d7</span>';
        item.querySelector('.remove').addEventListener('click', () => {
          attachedContexts.splice(i, 1);
          renderContextBar();
        });
        contextBar.appendChild(item);
      });
    }

    function scrollToBottom() {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function escapeHtml(str) {
      const div = document.createElement('div');
      div.appendChild(document.createTextNode(str));
      return div.innerHTML;
    }

    /** Minimal markdown renderer — handles code blocks, inline code, bold, italic, links, paragraphs. */
    function renderMarkdown(text) {
      if (!text) return '';
      var BT = String.fromCharCode(96); // backtick — can't use literal inside template string
      let html = escapeHtml(text);

      // Code blocks
      html = html.replace(new RegExp(BT+BT+BT+'(\\\\w*?)\\\\n([\\\\s\\\\S]*?)'+BT+BT+BT, 'g'), function(_, lang, code) {
        return '<pre><code>' + code + '</code></pre>';
      });

      // Inline code
      html = html.replace(new RegExp(BT+'([^'+BT+']+?)'+BT, 'g'), '<code>$1</code>');

      // Bold
      html = html.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');

      // Italic
      html = html.replace(/\\*(.+?)\\*/g, '<em>$1</em>');

      // Line breaks → paragraphs
      html = html.replace(/\\n\\n/g, '</p><p>');
      html = html.replace(/\\n/g, '<br>');
      html = '<p>' + html + '</p>';

      return html;
    }

    // Handle messages from extension host
    window.addEventListener('message', (event) => {
      const msg = event.data;
      switch (msg.type) {
        case 'ready':
          statusEl.textContent = 'Ready — send a message to continue the conversation';
          break;
        case 'noConfig':
          statusEl.textContent = 'No server configuration found. Please open this editor from the workspace UI.';
          break;
        case 'noChannel':
          statusEl.textContent = 'No channel bound. Please open this editor from a channel workspace tab.';
          break;
        case 'streamStart':
          startStreaming();
          break;
        case 'textDelta':
          appendText(msg.text);
          break;
        case 'toolStart':
          addToolCall(msg.name);
          break;
        case 'toolResult':
          resolveToolCall(msg.name, msg.result);
          break;
        case 'thinking':
          addThinking(msg.text);
          break;
        case 'streamEnd':
          stopStreaming();
          break;
        case 'error':
          addError(msg.text);
          if (streaming) stopStreaming();
          break;
        case 'context':
          addContext(msg.context);
          break;
        case 'history':
          loadHistory(msg.messages);
          break;
      }
    });

    // Signal ready
    vscode.postMessage({ type: 'webviewReady' });
  </script>
</body>
</html>`;
}
