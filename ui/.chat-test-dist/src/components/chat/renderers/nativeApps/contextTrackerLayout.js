export function deriveContextTrackerLayoutProfile(layout, gridDimensions) {
    const width = gridDimensions?.width ?? 0;
    const height = gridDimensions?.height ?? 0;
    if (layout === "header" || layout === "chip" || layout === "rail") {
        return {
            mode: "compact",
            statColumns: 2,
            categoryLimit: 1,
            activityLimit: 0,
            splitSecondary: false,
            showBreakdown: true,
            showActivity: false,
            showTurnsInContext: false,
        };
    }
    if ((width > 0 && width < 300) || (height > 0 && height < 170)) {
        return {
            mode: "compact",
            statColumns: 2,
            categoryLimit: 2,
            activityLimit: 0,
            splitSecondary: false,
            showBreakdown: true,
            showActivity: false,
            showTurnsInContext: false,
        };
    }
    if (width >= 560 && height >= 180) {
        return {
            mode: "wide",
            statColumns: 4,
            categoryLimit: height >= 260 ? 5 : 4,
            activityLimit: height >= 260 ? 4 : 3,
            splitSecondary: true,
            showBreakdown: true,
            showActivity: true,
            showTurnsInContext: true,
        };
    }
    if (height >= 260) {
        return {
            mode: "tall",
            statColumns: 4,
            categoryLimit: 5,
            activityLimit: 4,
            splitSecondary: false,
            showBreakdown: true,
            showActivity: true,
            showTurnsInContext: true,
        };
    }
    return {
        mode: "standard",
        statColumns: 3,
        categoryLimit: 4,
        activityLimit: 2,
        splitSecondary: false,
        showBreakdown: true,
        showActivity: true,
        showTurnsInContext: false,
    };
}
