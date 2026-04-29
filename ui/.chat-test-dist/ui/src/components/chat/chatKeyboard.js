export function isEditableKeyboardTarget(target) {
    const el = target;
    const tag = typeof el?.tagName === "string" ? el.tagName.toUpperCase() : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT")
        return true;
    if (el?.isContentEditable)
        return true;
    return !!el?.closest?.('[contenteditable="true"], [role="textbox"]');
}
