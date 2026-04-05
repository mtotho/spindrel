import { useThemeTokens } from "@/src/theme/tokens";

export function FileModeOnlyBanner({
  historyMode,
}: {
  historyMode: string;
}) {
  const t = useThemeTokens();
  const isFileMode = historyMode === "file";

  return (
    <div style={{ marginTop: 8, marginBottom: 4 }}>
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          marginBottom: 4,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
          Section Index
        </span>
        <div
          style={{
            backgroundColor: isFileMode
              ? t.accentSubtle
              : "rgba(100,100,100,0.15)",
            paddingLeft: 7,
            paddingRight: 7,
            paddingTop: 2,
            paddingBottom: 2,
            borderRadius: 4,
          }}
        >
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              color: isFileMode ? t.accent : t.textDim,
            }}
          >
            file mode only
          </span>
        </div>
      </div>
      {!isFileMode && (
        <span style={{ fontSize: 11, color: t.textDim, lineHeight: "17px" }}>
          These settings only apply when History Mode is "file". Current mode:
          "{historyMode}".
        </span>
      )}
    </div>
  );
}
