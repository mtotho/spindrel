import test from "node:test";
import assert from "node:assert/strict";
import { getChatShortcutLabel, isCloseActiveChatTabShortcut, isEditableKeyboardTarget, isKeyboardHelpShortcut, isSwitchSessionsShortcut, } from "./chatKeyboard.js";
test("editable keyboard guard catches form controls", () => {
    assert.equal(isEditableKeyboardTarget({ tagName: "input" }), true);
    assert.equal(isEditableKeyboardTarget({ tagName: "TEXTAREA" }), true);
    assert.equal(isEditableKeyboardTarget({ tagName: "select" }), true);
});
test("editable keyboard guard catches contenteditable and textbox ancestors", () => {
    assert.equal(isEditableKeyboardTarget({ isContentEditable: true }), true);
    assert.equal(isEditableKeyboardTarget({ closest: () => ({}) }), true);
});
test("editable keyboard guard allows normal page targets", () => {
    assert.equal(isEditableKeyboardTarget(null), false);
    assert.equal(isEditableKeyboardTarget({ tagName: "DIV", closest: () => null }), false);
});
test("switch sessions shortcut uses browser-safe modifier chord", () => {
    assert.equal(isSwitchSessionsShortcut({ key: "s", metaKey: true, altKey: true }), true);
    assert.equal(isSwitchSessionsShortcut({ key: "S", ctrlKey: true, altKey: true }), true);
    assert.equal(isSwitchSessionsShortcut({ key: "s", ctrlKey: true }), false);
    assert.equal(isSwitchSessionsShortcut({ key: "s", ctrlKey: true, altKey: true, shiftKey: true }), false);
    assert.equal(isSwitchSessionsShortcut({ key: "s", ctrlKey: true, altKey: true, repeat: true }), false);
});
test("keyboard help shortcut stays plain question mark only", () => {
    assert.equal(isKeyboardHelpShortcut({ key: "?" }), true);
    assert.equal(isKeyboardHelpShortcut({ key: "?", ctrlKey: true }), false);
    assert.equal(isKeyboardHelpShortcut({ key: "/", shiftKey: true }), false);
});
test("close active chat tab shortcut uses plain mod+w", () => {
    assert.equal(isCloseActiveChatTabShortcut({ key: "w", metaKey: true }), true);
    assert.equal(isCloseActiveChatTabShortcut({ key: "W", ctrlKey: true }), true);
    assert.equal(isCloseActiveChatTabShortcut({ key: "w", ctrlKey: true, shiftKey: true }), false);
    assert.equal(isCloseActiveChatTabShortcut({ key: "w", ctrlKey: true, altKey: true }), false);
    assert.equal(isCloseActiveChatTabShortcut({ key: "w", ctrlKey: true, repeat: true }), false);
});
test("shortcut labels follow platform conventions", () => {
    assert.equal(getChatShortcutLabel("switchSessions", "Macintosh"), "⌘⌥S");
    assert.equal(getChatShortcutLabel("switchSessions", "Windows NT"), "Ctrl+Alt+S");
    assert.equal(getChatShortcutLabel("closeActiveTab", "Macintosh"), "⌘W");
});
