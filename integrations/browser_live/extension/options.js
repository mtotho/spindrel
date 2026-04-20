const $ = (id) => document.getElementById(id);

(async () => {
  const { server_url = "", token = "" } = await chrome.storage.local.get([
    "server_url",
    "token",
  ]);
  $("server_url").value = server_url;
  $("token").value = token;
})();

$("save").addEventListener("click", async () => {
  await chrome.storage.local.set({
    server_url: $("server_url").value.trim().replace(/\/$/, ""),
    token: $("token").value.trim(),
  });
  $("status").textContent = "Saved. Reconnecting…";
});
