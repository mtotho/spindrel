```bash
docker build -t agent-python:latest -f dockerfiles/agent-python .
```

Add **`GITHUB_TOKEN`** to the **sandbox profile** env in admin (injected as `docker -e` when the container starts). The image does **not** need the token at build time. Git calls the bundled helper when you push; you do not run any extra auth commands.

No entrypoint — the server still starts the container with `sleep infinity` as usual.
