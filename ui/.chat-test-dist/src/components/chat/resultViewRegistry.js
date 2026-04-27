export class ResultViewRegistry {
    views = new Map();
    register(viewKey, renderers) {
        const current = this.views.get(viewKey) ?? {};
        this.views.set(viewKey, { ...current, ...renderers });
    }
    resolve(viewKey, mode) {
        const renderers = this.views.get(viewKey);
        if (!renderers)
            return null;
        return renderers[mode] ?? renderers.any ?? null;
    }
    has(viewKey) {
        return this.views.has(viewKey);
    }
}
export function createResultViewRegistry() {
    return new ResultViewRegistry();
}
export function contentTypeToViewKey(contentType) {
    switch (contentType) {
        case "text/markdown":
            return "core.markdown";
        case "application/json":
            return "core.json";
        case "text/html":
            return "core.html";
        case "application/vnd.spindrel.html+interactive":
            return "core.interactive_html";
        case "application/vnd.spindrel.diff+text":
            return "core.diff";
        case "application/vnd.spindrel.file-listing+json":
            return "core.file_listing";
        case "application/vnd.spindrel.components+json":
            return "core.components";
        case "application/vnd.spindrel.native-app+json":
            return "core.native_app";
        case "application/vnd.spindrel.plan+json":
            return "core.plan";
        case "text/plain":
        default:
            return "core.text";
    }
}
export function envelopeViewKey(envelope) {
    return envelope.view_key || contentTypeToViewKey(envelope.content_type);
}
