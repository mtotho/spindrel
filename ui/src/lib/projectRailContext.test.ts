import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { projectRailContextForLocation } from "./projectRailContext.js";

describe("project rail context", () => {
  it("is hidden on the projects list and blueprint routes", () => {
    assert.equal(projectRailContextForLocation("/admin/projects"), null);
    assert.equal(projectRailContextForLocation("/admin/projects/blueprints/blueprint-1"), null);
  });

  it("shows the current project child context on project detail routes", () => {
    assert.deepEqual(projectRailContextForLocation("/admin/projects/project-1", "#feed"), {
      projectId: "project-1",
      activeChild: "feed",
    });
    assert.deepEqual(projectRailContextForLocation("/admin/projects/project-1/runs/task-1"), {
      projectId: "project-1",
      activeChild: "runs",
    });
  });

  it("defaults project detail to overview", () => {
    assert.deepEqual(projectRailContextForLocation("/admin/projects/project-1", ""), {
      projectId: "project-1",
      activeChild: "overview",
    });
  });
});
